import os
import io
import argparse
from PIL import Image
from google import genai
from google.genai import types
from google.genai.types import HttpOptions



# Import the function from the standalone splitter file
from standalone_image_splitter import split_image
from standalone_image_splitter import save_chunks_for_debug
from pathlib import Path
import time
import concurrent.futures
from evaluator import evaluate_translation
import subprocess

def translate_image_chunk(client, image_chunk: Image.Image, prompt_text: str, chunk_num: int = None) -> Image.Image:
    """
    Translates a single image chunk using Nano Banana model.
    """
    # 1. Convert PIL Image to bytes
    img_byte_arr = io.BytesIO()
    image_chunk.save(img_byte_arr, format='PNG')
    img_byte_arr = img_byte_arr.getvalue()

    # 2. Prepare parts for the API call
    image_part = types.Part.from_bytes(
        data=img_byte_arr,
        mime_type="image/png",
    )
    prompt_part = types.Part.from_text(
        text=prompt_text
    )

    # 3. Configure and call the model
    model = "gemini-3.1-flash-image-preview"
    contents = [types.Content(role="user", parts=[image_part, prompt_part])]
    generate_content_config = types.GenerateContentConfig(
        #temperature=0.2, # Lower temperature for more deterministic translation
        #max_output_tokens=8192, # A reasonable limit
        response_modalities=["IMAGE"], # We only need the image back
    )

    chunk_label = f" #{chunk_num}" if chunk_num is not None else ""
    print(f"Translating a chunk{chunk_label}...")
    response = None # Define response outside the try block
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=generate_content_config,
            )
            break # Success, exit retry loop
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2) # Wait a bit before retrying
            else:
                print("Max retries reached. Returning original chunk.")
                return image_chunk

    try:
        if not response.candidates:
            print("Warning: Translation failed. API returned no candidates. Returning original chunk.")
            print("Full Response:", response)
            return image_chunk

        # Explicitly check if the parts attribute is None
        if response.candidates[0].content.parts is None:
            print("Warning: Translation failed. API response content has no parts. This might be due to safety filters.")
            print("Full Response:", response)
            return image_chunk

        # Iterate through parts of the first candidate's content
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                translated_image_bytes = part.inline_data.data
                translated_image = Image.open(io.BytesIO(translated_image_bytes))
                print(f"Chunk{chunk_label} translated successfully.")
                return translated_image
            elif part.text:
                print("Warning: Translation failed. API returned text instead of an image.")
                print("API returned the following text:", part.text)
                return image_chunk
        
        print("Warning: Translation failed. API response parts did not contain image or text. Returning original chunk.")
        print("Full Response:", response)
        return image_chunk

    except Exception as e:
        # This catch block might not be reached due to the inner try-except for the API call, 
        # but keeping it for safety in case of other errors during response processing.
        print(f"An error occurred during response processing: {e}")
        if response:
            print("--- Full Response at time of error ---")
            print(response)
            print("-------------------------------------")
        print("Warning: Returning original chunk.")
        return image_chunk


def merge_images_vertically(images: list[Image.Image], original_width: int) -> Image.Image:
    """
    Merges a list of PIL Images vertically.
    Each image is resized to match the original_width while maintaining aspect ratio.
    """
    if not images:
        return None

    resized_images = []
    for img in images:
        if img.width != original_width:
            # Calculate new height to maintain aspect ratio
            new_height = int(img.height * (original_width / img.width))
            # Resize the image using a high-quality downsampling filter
            resized_img = img.resize((original_width, new_height), Image.Resampling.LANCZOS)
            resized_images.append(resized_img)
        else:
            resized_images.append(img)

    # Calculate total height from the (potentially resized) images
    total_height = sum(r_img.height for r_img in resized_images)

    # Create a new image with the final dimensions
    merged_image = Image.new('RGB', (original_width, total_height))

    current_y = 0
    for r_img in resized_images:
        merged_image.paste(r_img, (0, current_y))
        current_y += r_img.height

    return merged_image

def translate_and_evaluate_chunk(client, image_chunk: Image.Image, chunk_num: int, prompt_text: str, evaluation_prompt: str) -> Image.Image:
    """
    Translates a single image chunk and evaluates its quality.
    Retries up to 5 times if evaluation fails.
    """
    max_eval_retries = 5
    for attempt in range(max_eval_retries):
        print(f"\n--- Chunk #{chunk_num} Evaluation Attempt {attempt + 1}/{max_eval_retries} ---")
        translated_chunk = translate_image_chunk(client, image_chunk, prompt_text, chunk_num)
        
        print(f"Evaluating chunk #{chunk_num}...")
        evaluation_result, evaluation_details = evaluate_translation(client, image_chunk, translated_chunk, evaluation_prompt)
        print(f"Chunk #{chunk_num} Evaluation Result: {evaluation_result}")
        print(f"Chunk #{chunk_num} Evaluation Details:\n{evaluation_details}")
        
        if evaluation_result:
            print(f"Chunk #{chunk_num} evaluation succeeded.")
            return translated_chunk
        else:
            print(f"Chunk #{chunk_num} evaluation failed. Retrying...")

    print(f"Max eval retries reached for chunk #{chunk_num}. Returning last translation.")
    return translated_chunk

def main(input_path: str, output_path: str, project_id: str, location: str, prompt_file: str, prompt: str = None):
    """
    Main function to split, translate, and merge an image.
    """
    # Step 1: Calculate dynamic max height and split the input image
    print(f"Reading image to calculate dynamic chunk height: {input_path}")
    try:
        with Image.open(input_path) as img:
            width, _ = img.size
    except FileNotFoundError:
        print(f"Error: Input image not found at {input_path}")
        return
    except Exception as e:
        print(f"Error opening image to get width: {e}")
        return

    # Calculate dynamic max_height based on width (16:9 aspect ratio)
    dynamic_max_height = int((width * 16) / 9)
    print(f"Image width: {width}px, Dynamic max height for chunks: {dynamic_max_height}px")

    print(f"Splitting image...")
    image_chunks = split_image(input_path, max_height=dynamic_max_height)

    if not image_chunks:
        print("No chunks were created. Exiting.")
        return

    # Step 1.5 : Optional. Save chunks for debugging
    debug_chunks_dir = Path("debug_chunks")
    save_chunks_for_debug(image_chunks, input_path, debug_chunks_dir)

    # Determine Project ID
    final_project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
    if not final_project_id:
        try:
            # Try to get project ID from gcloud
            result = subprocess.run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, check=True)
            final_project_id = result.stdout.strip()
            if final_project_id:
                print(f"Automatically detected Project ID: {final_project_id}")
        except Exception as e:
            print(f"Failed to auto-detect Project ID: {e}")

    if not final_project_id:
        print("Error: Google Cloud Project ID is not set.")
        print("Please provide it via the --project_id argument or set the GOOGLE_CLOUD_PROJECT_ID environment variable.")
        return

    print(f"Using Google Cloud Project ID: {final_project_id}")
    print(f"Using Google Cloud Location: {location}")

    # Initialize the Gemini client
    try:
        client = genai.Client(
            vertexai=True,
            project=final_project_id,
            location=location,
            #http_options=HttpOptions(timeout=60 * 10), # 10 minutes timeout
        )
    except Exception as e:
        print(f"Error initializing Gemini client: {e}")
        print("Please ensure you have authenticated with Google Cloud CLI (gcloud auth application-default login).")
        return

    # Read prompt
    if prompt:
        prompt_text = prompt
        print("Using prompt provided via argument.")
    else:
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                prompt_text = f.read().strip()
            print(f"Loaded prompt from: {prompt_file}")
        except FileNotFoundError:
            print(f"Error: Prompt file not found at {prompt_file}")
            return
        except Exception as e:
            print(f"Error reading prompt file: {e}")
            return

    # Construct evaluation prompt (English prompt, Korean output)
    evaluation_prompt = f"""
    You are an expert evaluator of image translations.
    The following instructions were used to translate the text in the image:
    ---
    {prompt_text}
    ---

    Based on these instructions, compare the original image segment and the translated image segment.
    Provide a detailed evaluation of whether the translated image segment faithfully reflects the instructions.
    Break down your evaluation into the following items:
    1. **Text Accuracy:** Are all required text elements translated accurately and naturally?
    2. **Typography:** Does the new text mimic the original typography (style, color, size, alignment)?
    3. **Exclusions / Inclusions:** Did you ensure that only the allowed text was replaced (e.g., no product labels)? No new visual elements added?

    For each item, provide your assessment and evidence from the images.
    **CRITICAL:** Provide your detailed evaluation, assessment, and explanations in Korean (한국어). The headings can remain in English.
    Finally, conclude with a clear verdict:
    Result: True (Pass) or False (Fail)
    """

    # Step 2: Translate each chunk (Parallel Processing)
    print(f"Starting translation of {len(image_chunks)} chunks with 4 parallel workers...")
    translated_chunks = [None] * len(image_chunks) # Pre-allocate list to maintain order

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all tasks
        future_to_index = {
            executor.submit(translate_and_evaluate_chunk, client, chunk, i + 1, prompt_text, evaluation_prompt): i 
            for i, chunk in enumerate(image_chunks)
        }
        
        for future in concurrent.futures.as_completed(future_to_index):
            i = future_to_index[future]
            try:
                translated_chunk = future.result()
                translated_chunks[i] = translated_chunk
                print(f"--- Chunk {i+1}/{len(image_chunks)} processing completed ---")
            except Exception as exc:
                print(f"Chunk {i+1} generated an exception: {exc}")
                translated_chunks[i] = image_chunks[i] # Fallback to original chunk on error

    # Step 2.5: Save ALL translated chunks for debug
    print("Saving ALL translated chunks for debug...")
    translated_debug_dir = Path("debug_translated_chunks")
    save_chunks_for_debug(translated_chunks, input_path, translated_debug_dir)

    # Step 3: Merge the translated chunks
    print("Merging translated chunks...")
    final_image = merge_images_vertically(translated_chunks, width)

    # Step 4: Save the final image
    if final_image:
        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        final_image.save(output_path)
        print(f"Successfully created translated image at: {output_path}")

        final_image.save(output_path)
        print(f"Successfully created translated image at: {output_path}")
    else:
        print("Failed to create the final image.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translate Korean text in an image to English.")
    parser.add_argument("input_image", help="Path to the input image file.")
    parser.add_argument("output_image", help="Path to save the output translated image.")
    parser.add_argument("--project_id", help="Your Google Cloud Project ID. If not set, defaults to GOOGLE_CLOUD_PROJECT_ID environment variable.")
    parser.add_argument("--location", default="global", help="The Google Cloud location (e.g., global, us-central1).")
    parser.add_argument("--prompt_file", default="prompt.txt", help="Path to the text file containing the prompt (default: prompt.txt).")
    parser.add_argument("--prompt", help="The prompt text. Overrides --prompt_file if provided.")
    args = parser.parse_args()

    main(args.input_image, args.output_image, args.project_id, args.location, args.prompt_file, args.prompt)