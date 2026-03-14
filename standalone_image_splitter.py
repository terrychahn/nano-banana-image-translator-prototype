
from PIL import Image
from typing import List
from pathlib import Path
# from config.constants import Constants # Removed for standalone usage


def find_best_cut_position(
    image: Image.Image, target_y: int, search_radius: int = 50
) -> int:
    """
    Finds the best vertical position to cut the image to avoid splitting text.
    It searches for a line with the minimum number of unique colors around a target position.
    If multiple lines have the same minimum number of colors, it chooses the one closest to target_y.

    Args:
        image: The Pillow Image object.
        target_y: The initial target y-coordinate for the cut.
        search_radius: The number of pixels to search up and down from the target_y.

    Returns:
        The y-coordinate that is the best position for the cut.
    """
    min_colors = float("inf")
    best_y = target_y
    min_dist = float("inf")

    # Define the search range, ensuring it's within image bounds
    start_y = max(0, target_y - search_radius)
    end_y = min(image.height, target_y + search_radius)

    if start_y >= end_y:
        return target_y

    for y in range(start_y, end_y):
        # Crop a 1-pixel high row
        row = image.crop((0, y, image.width, y + 1))

        # getcolors() returns a list of (count, pixel) tuples.
        colors = row.getcolors(maxcolors=1024)

        if not colors:
            # If getcolors() returns None, it means there are more than maxcolors.
            # Treat it as a very complex line we want to avoid.
            num_colors = 1025
        else:
            num_colors = len(colors)

        dist = abs(y - target_y)

        # Prioritize lines with fewer colors.
        if num_colors < min_colors:
            min_colors = num_colors
            min_dist = dist
            best_y = y
        # If color count is the same, prioritize the one closer to the target.
        elif num_colors == min_colors:
            if dist < min_dist:
                min_dist = dist
                best_y = y

    # print(f"  - Best cut line near y={target_y} is y={best_y} with {min_colors} colors.")
    return best_y


# Original function signature:
# def split_image(
#     image_path: str, max_height: int = Constants.SPLITTER_DEFAULT_MAX_HEIGHT
# ) -> List[Image.Image]:
def split_image(
    image_path: str, max_height: int = 4000
) -> List[Image.Image]:
    """
    Splits a tall image into multiple smaller chunks. It tries to find the best
    cut position to avoid splitting text.

    Args:
        image_path: The path to the input image file.
        max_height: The maximum height of each chunk.

    Returns:
        A list of Pillow Image objects representing the chunks.
    """
    try:
        img = Image.open(image_path)
    except FileNotFoundError:
        print(f"Error: Image file not found at {image_path}")
        return []
    except Exception as e:
        print(f"Error opening image: {e}")
        return []

    width, height = img.size
    chunks = []

    if height <= max_height:
        print("Image height is within the limit, no splitting needed.")
        return [img]

    print(
        f"Image height ({height}px) exceeds max height ({max_height}px). Splitting smartly..."
    )

    current_y = 0
    while current_y < height:
        proposed_end_y = current_y + max_height

        if proposed_end_y >= height:
            # This is the last chunk
            box = (0, current_y, width, height)
            chunk = img.crop(box)
            chunks.append(chunk)
            print(f"  - Created final chunk {len(chunks)} with dimensions {chunk.size}")
            break

        # Find the best position to cut around the proposed end_y
        best_cut_y = find_best_cut_position(img, proposed_end_y, search_radius=100)

        # Ensure we are making progress and the chunk is not empty
        if best_cut_y <= current_y:
            # If the best cut is not after the current position, force a cut
            # at the proposed position to avoid an infinite loop.
            # print(f"  - Warning: Best cut position y={best_cut_y} is not advancing from current_y={current_y}. Forcing cut at {proposed_end_y}.")
            best_cut_y = proposed_end_y
            # Also ensure the forced cut is within bounds
            if best_cut_y >= height:
                best_cut_y = height

        box = (0, current_y, width, best_cut_y)
        chunk = img.crop(box)
        chunks.append(chunk)
        print(f"  - Created chunk {len(chunks)} with dimensions {chunk.size}")

        current_y = best_cut_y

    return chunks


def save_chunks_for_debug(
    chunks: List[Image.Image], original_filename: str, debug_dir: Path | str
):
    """
    Saves the split image chunks to the debug directory.
    Handles both str and Path objects for debug_dir.

    Args:
        chunks: A list of Pillow Image objects.
        original_filename: The filename of the original image to use for naming.
        debug_dir: The directory to save the debug images in (can be str or Path).
    """
    if not chunks:
        return

    # Ensure debug_dir is a Path object and the directory exists
    debug_path = Path(debug_dir)
    debug_path.mkdir(parents=True, exist_ok=True)

    base_name = Path(original_filename).stem
    for i, chunk in enumerate(chunks):
        chunk_filename = debug_path / f"{base_name}_chunk_{i+1:02d}.png"
        chunk.save(chunk_filename, "PNG")
        print(f"  - Saved debug chunk to {chunk_filename}")
