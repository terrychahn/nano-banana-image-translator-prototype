import io
from typing import Tuple
from PIL import Image
from google import genai
from google.genai import types

def evaluate_translation(
    client: genai.Client,
    original_image: Image.Image,
    translated_image: Image.Image,
    evaluation_prompt: str
) -> Tuple[bool, str]:
    """
    Evaluates the translation quality by comparing the original and translated images.
    Returns True if the translation is acceptable, False otherwise.
    """
    # 1. Convert PIL Images to bytes
    orig_byte_arr = io.BytesIO()
    original_image.save(orig_byte_arr, format='PNG')
    orig_bytes = orig_byte_arr.getvalue()

    trans_byte_arr = io.BytesIO()
    translated_image.save(trans_byte_arr, format='PNG')
    trans_bytes = trans_byte_arr.getvalue()

    # 2. Prepare parts for the API call
    orig_part = types.Part.from_bytes(
        data=orig_bytes,
        mime_type="image/png",
    )
    trans_part = types.Part.from_bytes(
        data=trans_bytes,
        mime_type="image/png",
    )
    prompt_part = types.Part.from_text(
        text=evaluation_prompt
    )

    # 3. Configure and call the model
    model = "gemini-3.1-pro-preview"
    contents = [types.Content(role="user", parts=[orig_part, trans_part, prompt_part])]
    generate_content_config = types.GenerateContentConfig(
        # We expect a simple text response like "True" or "False", 
        # but since we want to evaluate, we might ask for a reasoning too.
        # For simplicity, let's assume the prompt asks for a boolean-like response.
        response_modalities=["TEXT"],
    )

    print("Evaluating translation quality...")
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=generate_content_config,
        )
        
        if response.candidates and response.candidates[0].content.parts:
            original_text = response.candidates[0].content.parts[0].text.strip()
            response_text = original_text.lower()
            print("Evaluation response (raw output):")
            print(original_text)
            
            if "true" in response_text:
                return True, original_text
            else:
                return False, original_text
        else:
            print("Warning: Evaluation failed. No response from API.")
            return False, "Evaluation failed. No response from API."
    except Exception as e:
        print(f"Error during evaluation: {e}")
        return False, f"Error during evaluation: {e}"
