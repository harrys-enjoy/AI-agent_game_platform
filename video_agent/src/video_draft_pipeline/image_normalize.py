from io import BytesIO

from PIL import Image, UnidentifiedImageError

# Matches the real, empirically-confirmed output resolution of the Veo 3.1
# render backend (1280x720, exact 16:9) -- normalizing every manually
# uploaded fix image to this exact shape keeps it consistent with the
# pipeline's own generated candidates and avoids feeding Veo/LTX (and the
# downstream ffmpeg `-c copy` concat) an unpredictable input aspect ratio.
TARGET_WIDTH = 1280
TARGET_HEIGHT = 720


class ImageNormalizeError(Exception):
    pass


def normalize_image_bytes(
    data: bytes, target_width: int = TARGET_WIDTH, target_height: int = TARGET_HEIGHT
) -> bytes:
    try:
        image = Image.open(BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageNormalizeError(f"Uploaded file is not a readable image: {exc}") from exc

    image = image.convert("RGB")
    width, height = image.size
    target_ratio = target_width / target_height
    current_ratio = width / height

    if current_ratio > target_ratio:
        cropped_width = round(height * target_ratio)
        left = (width - cropped_width) // 2
        image = image.crop((left, 0, left + cropped_width, height))
    elif current_ratio < target_ratio:
        cropped_height = round(width / target_ratio)
        top = (height - cropped_height) // 2
        image = image.crop((0, top, width, top + cropped_height))

    image = image.resize((target_width, target_height), Image.LANCZOS)

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
