import io

import aiohttp
import cv2
import numpy as np
from PIL import Image

import log

from . import pre


def decode_image(image_bytes: bytes) -> np.ndarray:
    img_array = np.frombuffer(image_bytes, dtype=np.uint8)
    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img_cv is None:
        raise ValueError("Could not decode image bytes.")
    return img_cv


def to_png_bytes(img_rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img_rgb).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


async def process_image(
    image_url: str,
    template_gray: np.ndarray,
    mask: np.ndarray,
    padding: int = 10,
) -> bytes:

    async with aiohttp.ClientSession() as session:  # noqa: SIM117
        async with session.get(image_url) as response:
            if response.status != 200:
                raise ValueError(f"Failed to fetch image: HTTP {response.status}")
            image_bytes = await response.read()

    img_cv = decode_image(image_bytes)
    height, width = img_cv.shape[:2]

    search_y_start = int(height * 0.1)
    search_y_end = int(height * 0.3)
    search_x_end = int(width * 0.25)
    manual_y_start = int(height * 0.05)
    manual_x_end = int(width * 0.5)

    search_region = img_cv[search_y_start:search_y_end, :search_x_end]
    search_gray = cv2.cvtColor(search_region, cv2.COLOR_BGR2GRAY)

    match = await pre.find_shield(search_gray, template_gray, mask)

    if match is None:
        await log.warning("Shield not found, cropping manually")

        manual_crop = img_cv[manual_y_start:search_y_end, :manual_x_end]
        fallback_rgb = cv2.cvtColor(manual_crop, cv2.COLOR_BGR2RGB)
        return to_png_bytes(fallback_rgb)

    global_match_y = match.y + search_y_start

    crop_x1 = max(0, match.w + match.x - 5)
    crop_y1 = max(0, global_match_y - padding)
    crop_x2 = manual_x_end
    crop_y2 = min(search_y_end, global_match_y + match.h + padding)

    cropped_bgr = img_cv[crop_y1:crop_y2, crop_x1:crop_x2]
    cropped_rgb = cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2RGB)

    return to_png_bytes(cropped_rgb)
