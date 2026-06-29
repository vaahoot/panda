import io
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import cv2
import numpy as np
from PIL import Image

from helper import print_info, print_warning


@dataclass
class ShieldMatch:
    x: int
    y: int
    w: int
    h: int
    confidence: float
    scale: float


def load_template(template_path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Loads template and extracts the true Alpha channel for masking if it exists."""
    path_str = str(template_path)

    # Load with IMREAD_UNCHANGED to preserve the Alpha transparency channel
    template = cv2.imread(path_str, cv2.IMREAD_UNCHANGED)
    if template is None:
        raise ValueError(f"Could not load template from {path_str}")

    # Check if the image has 4 channels (B, G, R, Alpha)
    if len(template.shape) == 3 and template.shape[2] == 4:
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGRA2GRAY)
        # Use the literal transparency channel as the mask
        _, mask = cv2.threshold(template[:, :, 3], 1, 255, cv2.THRESH_BINARY)
    else:
        # Fallback for JPEGs or flat PNGs: mask out pure black/dark background
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(template_gray, 10, 255, cv2.THRESH_BINARY)

    return template_gray, mask


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


async def find_shield(
    img_gray: np.ndarray,
    template_gray: np.ndarray,
    mask: np.ndarray,
    confidence_threshold: float = 0.8,
) -> ShieldMatch | None:
    img_h, img_w = img_gray.shape
    t_h, t_w = template_gray.shape

    # PHASE 1: COARSE SEARCH (Top-3 Candidates)
    downscale_factor = 0.25
    coarse_img = cv2.resize(
        img_gray, (0, 0), fx=downscale_factor, fy=downscale_factor, interpolation=cv2.INTER_AREA
    )

    # Dynamic scaling limit based on physical screenshot size
    max_scale = min(img_w / t_w, img_h / t_h) * 0.95
    max_scale = max(1.5, max_scale)

    num_steps = max(20, int((max_scale - 0.15) / 0.05))
    coarse_scales = np.linspace(0.15, max_scale, num_steps)

    coarse_candidates = []

    for scale in coarse_scales:
        eff_scale = scale * downscale_factor
        new_w, new_h = int(t_w * eff_scale), int(t_h * eff_scale)

        if new_w < 4 or new_h < 4 or new_w >= coarse_img.shape[1] or new_h >= coarse_img.shape[0]:
            continue

        scaled_t = cv2.resize(template_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
        scaled_m = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

        result = cv2.matchTemplate(coarse_img, scaled_t, cv2.TM_CCOEFF_NORMED, mask=scaled_m)
        _, conf, _, loc = cv2.minMaxLoc(result)

        if np.isnan(conf) or np.isinf(conf):
            continue

        coarse_candidates.append({"x": loc[0], "y": loc[1], "conf": conf, "scale": scale})

    if not coarse_candidates:
        return None

    # Sort all found scales by confidence and pass the Top 3 to Phase 2
    coarse_candidates.sort(key=lambda c: c["conf"], reverse=True)
    top_candidates = coarse_candidates[:3]

    # PHASE 2: FINE SEARCH (Check all top candidates)
    absolute_best_match: ShieldMatch | None = None

    for candidate in top_candidates:
        cx = int(candidate["x"] / downscale_factor)
        cy = int(candidate["y"] / downscale_factor)
        best_scale = candidate["scale"]

        rough_w = int(t_w * best_scale)
        rough_h = int(t_h * best_scale)

        pad = 80
        roi_x1 = max(0, cx - pad)
        roi_y1 = max(0, cy - pad)
        roi_x2 = min(img_w, cx + rough_w + pad)
        roi_y2 = min(img_h, cy + rough_h + pad)

        fine_img = img_gray[roi_y1:roi_y2, roi_x1:roi_x2]
        fine_scales = np.linspace(max(0.1, best_scale - 0.08), best_scale + 0.08, 7)

        for scale in fine_scales:
            new_w, new_h = int(t_w * scale), int(t_h * scale)

            if new_w >= fine_img.shape[1] or new_h >= fine_img.shape[0] or new_w < 4 or new_h < 4:
                continue

            scaled_t = cv2.resize(template_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
            scaled_m = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

            result = cv2.matchTemplate(fine_img, scaled_t, cv2.TM_CCOEFF_NORMED, mask=scaled_m)
            _, conf, _, loc = cv2.minMaxLoc(result)

            if np.isnan(conf) or np.isinf(conf):
                continue

            if absolute_best_match is None or conf > absolute_best_match.confidence:
                absolute_best_match = ShieldMatch(
                    x=roi_x1 + int(loc[0]),
                    y=roi_y1 + int(loc[1]),
                    w=new_w,
                    h=new_h,
                    confidence=float(conf),
                    scale=float(scale),
                )

    if absolute_best_match is None:
        return None

    await print_info(f"Final confidence: {absolute_best_match.confidence:.2f} at scale {absolute_best_match.scale:.2f}")

    return absolute_best_match if absolute_best_match.confidence >= confidence_threshold else None


async def process_image(
    image_url: str,
    template_gray: np.ndarray,
    mask: np.ndarray,
    padding: int = 10,
) -> bytes:

    # Fetch image bytes asynchronously
    async with aiohttp.ClientSession() as session:
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

    match = await find_shield(search_gray, template_gray, mask)

    if match is None:
        await print_warning("Shield not found, cropping manually")

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
