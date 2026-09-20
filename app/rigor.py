"""Part-level deformation for the pet: two row-mapping primitives, no new deps.

Everything that makes the sprite feel alive is expressed as a per-row horizontal
shift (secondary motion, gaze) or a per-row vertical resample (blink, breathing).
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def _alpha_composite_zero(rgb: np.ndarray) -> np.ndarray:
    rgb[rgb[:, :, 3] == 0, :3] = 0
    return rgb


def shear_rows(image: Image.Image, offsets) -> Image.Image:
    """Shift row y horizontally by offsets[y] pixels, sub-pixel blended."""
    arr = np.array(image.convert("RGBA"), dtype=np.uint8)
    height, width = arr.shape[:2]
    off = np.zeros(height, dtype=float)
    flat = np.asarray(offsets, dtype=float).ravel()
    off[: min(height, flat.size)] = flat[: min(height, flat.size)]
    sign = np.sign(off)
    whole = np.abs(off).astype(int)
    frac = np.abs(off) - whole
    shift1 = (whole * sign).astype(int)[:, None]
    shift2 = ((whole + 1) * sign).astype(int)[:, None]
    xs = np.arange(width)[None, :]
    rows = np.arange(height)[:, None]
    near = np.clip(xs - shift1, 0, width - 1)
    far = np.clip(xs - shift2, 0, width - 1)
    a = arr[rows, near].astype(np.int16)
    b = arr[rows, far].astype(np.int16)
    w = frac[:, None, None]
    out = np.clip(a + (b - a) * w, 0, 255).astype(np.uint8)
    return Image.fromarray(_alpha_composite_zero(out), "RGBA")


def band_scale(image: Image.Image, top: float, bottom: float, factor: float) -> Image.Image:
    """Squash or stretch the rows between top and bottom about that band's centre."""
    arr = np.array(image.convert("RGBA"), dtype=np.uint8)
    height, width = arr.shape[:2]
    top_i, bottom_i = max(0, int(top)), min(height, int(bottom))
    if bottom_i - top_i < 2 or factor <= 0:
        return image
    centre = (top_i + bottom_i) / 2.0
    ys = np.arange(height, dtype=float)
    inside = (ys >= top_i) & (ys < bottom_i)
    ys[inside] = centre + (ys[inside] - centre) / factor
    ys = np.clip(ys, 0, height - 1)
    y0 = np.floor(ys).astype(int)
    y1 = np.minimum(y0 + 1, height - 1)
    blend = (ys - y0)[:, None, None]
    a = arr[y0].astype(np.int16)
    b = arr[y1].astype(np.int16)
    out = np.clip(a + (b - a) * blend, 0, 255).astype(np.uint8)
    return Image.fromarray(_alpha_composite_zero(out), "RGBA")


def simple_pendulum(height: int, pivot: float, amp: float) -> np.ndarray:
    """Same-sign lean above and below the pivot, like swaying on a string."""
    ys = np.arange(height, dtype=float)
    return amp * np.clip(np.abs(ys - pivot) / max(1.0, max(pivot, height - pivot)), 0, 1)


def head_follow_profile(height: int, head_bottom: float, amp: float, shoulder: float = 14.0) -> np.ndarray:
    """Move only the head: full shift above the neck, ramping to zero at the shoulders."""
    ys = np.arange(height, dtype=float)
    ramp = np.clip((head_bottom - ys) / max(1.0, shoulder), 0.0, 1.0)
    return amp * ramp
