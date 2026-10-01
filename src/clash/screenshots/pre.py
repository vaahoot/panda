import pathlib
from dataclasses import dataclass

import cv2
import numpy as np

# Shield scale relative to screenshot width, measured on real screenshots (0.826-0.845)
SCALE_PER_WIDTH = 0.000835
SCALE_SPREAD = 0.15

DOWNSCALE_FACTOR = 0.25
FINE_PAD = 32
FINE_RANGE = 0.08
FINE_STEP = 0.16 / 6
MERGE_PX = 3


@dataclass
class ShieldMatch:
    x: int
    y: int
    w: int
    h: int
    confidence: float
    scale: float


def load_template(template_path: str | pathlib.Path) -> tuple[np.ndarray, np.ndarray]:
    """Loads template and extracts the true Alpha channel for masking if it exists."""
    path_str = str(template_path)

    template = cv2.imread(path_str, cv2.IMREAD_UNCHANGED)
    if template is None:
        raise ValueError(f"Could not load template from {path_str}")

    if len(template.shape) == 3 and template.shape[2] == 4:
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGRA2GRAY)
        _, mask = cv2.threshold(template[:, :, 3], 1, 255, cv2.THRESH_BINARY)
    else:
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(template_gray, 10, 255, cv2.THRESH_BINARY)

    return template_gray, mask


def _match_at_scale(
    img: np.ndarray, template_gray: np.ndarray, mask: np.ndarray, scale: float
) -> tuple[float, tuple[int, int], int, int] | None:
    t_h, t_w = template_gray.shape
    new_w, new_h = int(t_w * scale), int(t_h * scale)

    if new_w < 4 or new_h < 4 or new_w >= img.shape[1] or new_h >= img.shape[0]:
        return None

    scaled_t = cv2.resize(template_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
    scaled_m = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

    result = cv2.matchTemplate(img, scaled_t, cv2.TM_CCOEFF_NORMED, mask=scaled_m)
    result[~np.isfinite(result)] = -1
    _, conf, _, loc = cv2.minMaxLoc(result)

    return conf, loc, new_w, new_h


def _search(
    img_gray: np.ndarray,
    template_gray: np.ndarray,
    mask: np.ndarray,
    coarse_scales: np.ndarray,
) -> ShieldMatch | None:
    img_h, img_w = img_gray.shape
    t_h, t_w = template_gray.shape

    coarse_img = cv2.resize(
        img_gray,
        (0, 0),
        fx=DOWNSCALE_FACTOR,
        fy=DOWNSCALE_FACTOR,
        interpolation=cv2.INTER_AREA,
    )

    coarse_candidates = []
    for scale in coarse_scales:
        match = _match_at_scale(
            coarse_img, template_gray, mask, scale * DOWNSCALE_FACTOR
        )
        if match is not None:
            conf, loc, _, _ = match
            coarse_candidates.append((conf, loc[0], loc[1], scale))

    if not coarse_candidates:
        return None

    coarse_candidates.sort(reverse=True)

    # The top candidates are usually the same spot at neighbouring scales,
    # so merge them into one region with a combined scale range
    groups: list[dict] = []
    for _, x, y, scale in coarse_candidates[:3]:
        for group in groups:
            if abs(group["x"] - x) <= MERGE_PX and abs(group["y"] - y) <= MERGE_PX:
                group["lo"] = min(group["lo"], scale)
                group["hi"] = max(group["hi"], scale)
                break
        else:
            groups.append({"x": x, "y": y, "lo": scale, "hi": scale})

    best: ShieldMatch | None = None

    for group in groups:
        cx = int(group["x"] / DOWNSCALE_FACTOR)
        cy = int(group["y"] / DOWNSCALE_FACTOR)
        lo = max(0.1, group["lo"] - FINE_RANGE)
        hi = group["hi"] + FINE_RANGE

        roi_x1 = max(0, cx - FINE_PAD)
        roi_y1 = max(0, cy - FINE_PAD)
        roi_x2 = min(img_w, cx + int(t_w * hi) + FINE_PAD)
        roi_y2 = min(img_h, cy + int(t_h * hi) + FINE_PAD)
        fine_img = img_gray[roi_y1:roi_y2, roi_x1:roi_x2]

        fine_scales = np.linspace(lo, hi, int(round((hi - lo) / FINE_STEP)) + 1)
        for scale in fine_scales:
            match = _match_at_scale(fine_img, template_gray, mask, scale)
            if match is None:
                continue

            conf, loc, new_w, new_h = match
            if best is None or conf > best.confidence:
                best = ShieldMatch(
                    x=roi_x1 + int(loc[0]),
                    y=roi_y1 + int(loc[1]),
                    w=new_w,
                    h=new_h,
                    confidence=float(conf),
                    scale=float(scale),
                )

    return best


def find_shield(
    img_gray: np.ndarray,
    template_gray: np.ndarray,
    mask: np.ndarray,
    screenshot_width: int,
    confidence_threshold: float = 0.8,
) -> ShieldMatch | None:
    """CPU-bound, run it in a thread."""
    # Fast path: the shield scales with screenshot width
    expected = screenshot_width * SCALE_PER_WIDTH
    match = _search(
        img_gray,
        template_gray,
        mask,
        np.linspace(expected * (1 - SCALE_SPREAD), expected * (1 + SCALE_SPREAD), 7),
    )
    if match is not None and match.confidence >= confidence_threshold:
        return match

    # Fallback: full scale range
    img_h, img_w = img_gray.shape
    t_h, t_w = template_gray.shape
    max_scale = max(1.5, min(img_w / t_w, img_h / t_h) * 0.95)
    num_steps = max(20, int((max_scale - 0.15) / 0.05))

    match = _search(
        img_gray, template_gray, mask, np.linspace(0.15, max_scale, num_steps)
    )
    if match is not None and match.confidence >= confidence_threshold:
        return match

    return None
