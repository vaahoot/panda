import asyncio

import cv2
import numpy as np

import log

from . import pre


def decode_image(image_bytes: bytes) -> np.ndarray:
    img_array = np.frombuffer(image_bytes, dtype=np.uint8)
    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img_cv is None:
        raise ValueError("Could not decode image bytes.")
    return img_cv


def to_png_bytes(img_bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img_bgr)
    if not ok:
        raise ValueError("Could not encode image as PNG.")
    return buf.tobytes()


def _crop(
    image_bytes: bytes,
    template_gray: np.ndarray,
    mask: np.ndarray,
    padding: int,
) -> tuple[bytes, pre.ShieldMatch | None]:
    img_cv = decode_image(image_bytes)
    height, width = img_cv.shape[:2]

    search_y_start = int(height * 0.1)
    search_y_end = int(height * 0.3)
    search_x_end = int(width * 0.25)
    manual_y_start = int(height * 0.05)
    manual_x_end = int(width * 0.5)

    search_region = img_cv[search_y_start:search_y_end, :search_x_end]
    search_gray = cv2.cvtColor(search_region, cv2.COLOR_BGR2GRAY)

    match = pre.find_shield(search_gray, template_gray, mask, width)

    if match is None:
        manual_crop = img_cv[manual_y_start:search_y_end, :manual_x_end]
        return to_png_bytes(manual_crop), None

    global_match_y = match.y + search_y_start

    crop_x1 = max(0, match.w + match.x - 5)
    crop_y1 = max(0, global_match_y - padding)
    crop_x2 = manual_x_end
    crop_y2 = min(search_y_end, global_match_y + match.h + padding)

    return to_png_bytes(img_cv[crop_y1:crop_y2, crop_x1:crop_x2]), match


async def process_image(
    image_bytes: bytes,
    template_gray: np.ndarray,
    mask: np.ndarray,
    padding: int = 10,
) -> bytes:
    png_bytes, match = await asyncio.to_thread(
        _crop, image_bytes, template_gray, mask, padding
    )

    if match is None:
        await log.warning("Shield not found, cropping manually")
    else:
        await log.info(
            f"Final confidence: {match.confidence:.2f} at scale {match.scale:.2f}"
        )

    return png_bytes
