import pathlib
from dataclasses import dataclass

import cv2
import numpy as np

import log


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


async def find_shield(
    img_gray: np.ndarray,
    template_gray: np.ndarray,
    mask: np.ndarray,
    confidence_threshold: float = 0.8,
) -> ShieldMatch | None:
    img_h, img_w = img_gray.shape
    t_h, t_w = template_gray.shape

    downscale_factor = 0.25
    coarse_img = cv2.resize(
        img_gray,
        (0, 0),
        fx=downscale_factor,
        fy=downscale_factor,
        interpolation=cv2.INTER_AREA,
    )

    max_scale = min(img_w / t_w, img_h / t_h) * 0.95
    max_scale = max(1.5, max_scale)

    num_steps = max(20, int((max_scale - 0.15) / 0.05))
    coarse_scales = np.linspace(0.15, max_scale, num_steps)

    coarse_candidates = []

    for scale in coarse_scales:
        eff_scale = scale * downscale_factor
        new_w, new_h = int(t_w * eff_scale), int(t_h * eff_scale)

        if (
            new_w < 4
            or new_h < 4
            or new_w >= coarse_img.shape[1]
            or new_h >= coarse_img.shape[0]
        ):
            continue

        scaled_t = cv2.resize(
            template_gray, (new_w, new_h), interpolation=cv2.INTER_AREA
        )
        scaled_m = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

        result = cv2.matchTemplate(
            coarse_img, scaled_t, cv2.TM_CCOEFF_NORMED, mask=scaled_m
        )
        _, conf, _, loc = cv2.minMaxLoc(result)

        if np.isnan(conf) or np.isinf(conf):
            continue

        coarse_candidates.append(
            {"x": loc[0], "y": loc[1], "conf": conf, "scale": scale}
        )

    if not coarse_candidates:
        return None

    coarse_candidates.sort(key=lambda c: c["conf"], reverse=True)
    top_candidates = coarse_candidates[:3]

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

            if (
                new_w >= fine_img.shape[1]
                or new_h >= fine_img.shape[0]
                or new_w < 4
                or new_h < 4
            ):
                continue

            scaled_t = cv2.resize(
                template_gray, (new_w, new_h), interpolation=cv2.INTER_AREA
            )
            scaled_m = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

            result = cv2.matchTemplate(
                fine_img, scaled_t, cv2.TM_CCOEFF_NORMED, mask=scaled_m
            )
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

    await log.info(
        f"Final confidence: {absolute_best_match.confidence:.2f} at scale {absolute_best_match.scale:.2f}"
    )

    return (
        absolute_best_match
        if absolute_best_match.confidence >= confidence_threshold
        else None
    )
