from io import BytesIO

import pytest
from PIL import Image

from video_draft_pipeline.image_normalize import (
    TARGET_HEIGHT,
    TARGET_WIDTH,
    ImageNormalizeError,
    normalize_image_bytes,
)


def _png_bytes(width: int, height: int, color=(200, 100, 50)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_normalize_produces_exact_target_dimensions_for_portrait_input():
    normalized = normalize_image_bytes(_png_bytes(768, 1408))

    image = Image.open(BytesIO(normalized))
    assert image.size == (TARGET_WIDTH, TARGET_HEIGHT)


def test_normalize_produces_exact_target_dimensions_for_wide_input():
    normalized = normalize_image_bytes(_png_bytes(4000, 3000))

    image = Image.open(BytesIO(normalized))
    assert image.size == (TARGET_WIDTH, TARGET_HEIGHT)


def test_normalize_produces_exact_target_dimensions_for_tiny_square_input():
    normalized = normalize_image_bytes(_png_bytes(200, 200))

    image = Image.open(BytesIO(normalized))
    assert image.size == (TARGET_WIDTH, TARGET_HEIGHT)


def test_normalize_center_crops_instead_of_distorting():
    # A wide image with a distinct color band only in its horizontal center
    # should keep that band after a center-crop-to-16:9 + resize; a naive
    # stretch-to-fit would smear the whole image instead of cropping it.
    width, height = 2000, 500
    image = Image.new("RGB", (width, height), (0, 0, 0))
    band_left = width // 2 - 10
    band_right = width // 2 + 10
    for x in range(band_left, band_right):
        for y in range(height):
            image.putpixel((x, y), (255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    normalized = normalize_image_bytes(buffer.getvalue())
    result = Image.open(BytesIO(normalized)).convert("RGB")

    center_pixel = result.getpixel((TARGET_WIDTH // 2, TARGET_HEIGHT // 2))
    corner_pixel = result.getpixel((5, 5))
    assert center_pixel == (255, 0, 0)
    assert corner_pixel == (0, 0, 0)


def test_normalize_rejects_unreadable_image_bytes():
    with pytest.raises(ImageNormalizeError):
        normalize_image_bytes(b"not-an-image-at-all")
