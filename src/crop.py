import io
from pathlib import Path

import aiohttp
import cv2
import numpy as np
from PIL import Image

from helper import print_warning


def load_template(template_path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    assert template is not None, f"Could not load template from {template_path}"
    template_gray = cv2.cvtColor(template[:, :, :3], cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(template_gray, 10, 255, cv2.THRESH_BINARY)
    return template_gray, mask


def find_shield(img_gray: np.ndarray, template_gray: np.ndarray, mask: np.ndarray) -> tuple[int, int, int, int] | None:
    img_h, img_w = img_gray.shape
    t_h, t_w = template_gray.shape

    best_confidence = 0.0
    best_x, best_y = 0, 0
    best_scale = 1.0

    for scale in np.linspace(0.1, 1.5, 10):
        new_w = int(t_w * scale)
        new_h = int(t_h * scale)
        if new_w >= img_w or new_h >= img_h:
            continue

        scaled_template = cv2.resize(template_gray, (new_w, new_h))
        scaled_mask = cv2.resize(mask, (new_w, new_h))

        result = cv2.matchTemplate(img_gray, scaled_template, cv2.TM_CCOEFF_NORMED, mask=scaled_mask)
        _, confidence, _, location = cv2.minMaxLoc(result)

        if confidence > best_confidence:
            best_confidence = confidence
            best_x, best_y = int(location[0]), int(location[1])
            best_scale = scale

    print(f"Best confidence: {best_confidence:.2f} at scale {best_scale:.2f}")

    if best_confidence < 0.50:
        return None

    t_h_scaled = int(t_h * best_scale)
    t_w_scaled = int(t_w * best_scale)
    return (best_x, best_y, t_w_scaled, t_h_scaled)


async def process_image(image_url: str, template_gray: np.ndarray, mask: np.ndarray) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            image_bytes = await response.read()

    img_array = np.frombuffer(image_bytes, np.uint8)
    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    assert img_cv is not None, "Could not decode image"

    height, width = img_cv.shape[:2]
    img_gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    top_half = img_gray[:height // 2, :]

    match = find_shield(top_half, template_gray, mask)

    if match is None:
        await print_warning("Shield not found, returning full image")
        return image_bytes

    x, y, _, h = match
    padding = 10

    crop_x1 = max(0, x - padding)
    crop_y1 = max(0, y - padding)
    crop_x2 = min(width, x + int(width * 0.6))
    crop_y2 = min(height, y + h + int(h * 0.8))

    cropped = img_cv[crop_y1:crop_y2, crop_x1:crop_x2]

    buf = io.BytesIO()
    img_pil = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
    img_pil.save(buf, format="PNG")
    return buf.getvalue()
