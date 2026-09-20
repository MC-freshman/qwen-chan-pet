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


def simple_pendulum(height: int, pivot: float, amp: float, rigid_above: float | None = None) -> np.ndarray:
    """Same-sign lean above and below the pivot, like swaying on a string.

    rigid_above freezes every row above that line at the neck's own offset: without
    it the head gets the largest displacement in the sprite and the gradient inside
    the head smears the hat brim into a streak.
    """
    ys = np.arange(height, dtype=float)
    reach = np.clip(np.abs(ys - pivot) / max(1.0, max(pivot, height - pivot)), 0, 1)
    if rigid_above is not None:
        cap = np.clip(abs(rigid_above - pivot) / max(1.0, max(pivot, height - pivot)), 0, 1)
        reach = np.minimum(reach, cap)
    return amp * reach


def head_follow_profile(height: int, head_bottom: float, amp: float, shoulder: float = 14.0) -> np.ndarray:
    """Move only the head: full shift above the neck, ramping to zero at the shoulders."""
    ys = np.arange(height, dtype=float)
    ramp = np.clip((head_bottom - ys) / max(1.0, shoulder), 0.0, 1.0)
    return amp * ramp


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def polar_twist(image, pivot, amp_deg, r_in, r_out, theta0, theta1, feather=22.0):
    """Rotate an annular sector about the pivot, feathered on every edge.

    This is the mask-free stand-in for a Live2D part deformer: the limb or hair
    tip turns around a real joint instead of the whole sprite sliding sideways.
    """
    arr = np.array(image.convert("RGBA"), dtype=np.float32)
    height, width = arr.shape[:2]
    px, py = pivot
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    dx = xs - px
    dy = ys - py
    radius = np.hypot(dx, dy)
    angle = np.degrees(np.arctan2(dy, dx))
    radial = _smoothstep((radius - r_in) / max(1.0, r_out - r_in))
    # keep the far edge from unwinding past the sector
    radial *= 1.0 - _smoothstep((radius - r_out) / max(1.0, r_out * 0.35)) * 0.35
    lo = np.arctan2(np.sin(np.radians(theta0)), np.cos(np.radians(theta0)))
    hi = np.arctan2(np.sin(np.radians(theta1)), np.cos(np.radians(theta1)))
    span = np.degrees((hi - lo) % (2 * np.pi))
    pos = (angle - np.degrees(lo)) % 360.0
    angular = _smoothstep(pos / max(1.0, feather)) * _smoothstep((span + feather - pos) / max(1.0, feather))
    shifted = np.radians(angle - amp_deg * radial * angular)
    src_x = px + radius * np.cos(shifted)
    src_y = py + radius * np.sin(shifted)
    x0 = np.floor(src_x).astype(np.int32)
    y0 = np.floor(src_y).astype(np.int32)
    fx = (src_x - x0)[..., None]
    fy = (src_y - y0)[..., None]
    x0 = np.clip(x0, 0, width - 1)
    y0 = np.clip(y0, 0, height - 1)
    x1 = np.clip(x0 + 1, 0, width - 1)
    y1 = np.clip(y0 + 1, 0, height - 1)
    a = arr[y0, x0] * (1 - fx) * (1 - fy) + arr[y0, x1] * fx * (1 - fy)
    b = arr[y1, x0] * (1 - fx) * fy + arr[y1, x1] * fx * fy
    out = np.clip(a + b, 0, 255).astype(np.uint8)
    out[out[:, :, 3] == 0, :3] = 0
    return Image.fromarray(out, "RGBA")


class Spring:
    """Critically tunable 1-D spring, stepped per frame to give parts overshoot."""

    __slots__ = ("x", "v", "k", "c")

    def __init__(self, k=42.0, c=6.5, value=0.0):
        self.x = value
        self.v = 0.0
        self.k = k      # stiffness
        self.c = c      # damping

    def step(self, target: float, dt: float) -> float:
        self.v += (self.k * (target - self.x) - self.c * self.v) * dt
        self.x += self.v * dt
        return self.x
