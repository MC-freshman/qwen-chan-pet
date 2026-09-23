"""Part-level deformation for the pet: two row-mapping primitives, no new deps.

Everything that makes the sprite feel alive is expressed as a per-row horizontal
shift (secondary motion, gaze) or a per-row vertical resample (blink, breathing).

Each primitive ships in two versions. The numpy gather is exact and is what the
frame build uses offline. The piecewise-affine one is ~6x cheaper (1.7ms vs 9.5ms
on a 269x291 cell) because Pillow does the resampling in C, and is what the running
pet uses every frame: our profiles are piecewise linear anyway, so splitting at
their kinks makes the approximation near-exact.
"""

from __future__ import annotations

import math
import random
import time

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


def _profile(height: int, offsets) -> np.ndarray:
    off = np.zeros(height, dtype=float)
    flat = np.asarray(offsets, dtype=float).ravel()
    off[: min(height, flat.size)] = flat[: min(height, flat.size)]
    return off


def _band_edges(off: np.ndarray, max_bands: int) -> list[int]:
    """Split the profile where its slope changes, so every run is near-linear.

    simple_pendulum and head_follow_profile are exactly piecewise linear, so cutting
    at their kinks makes each band's chord the profile itself. A band that straddles
    a kink instead shears the head by up to half the swing, which is why this looks
    for slope *changes* and not just sign flips.
    """
    height = off.size
    slope = np.diff(off)
    change = np.abs(np.diff(slope))
    kinks = np.flatnonzero(change > 0.05) + 1
    budget = max(0, max_bands - 3)
    if kinks.size > budget:
        kinks = kinks[np.argsort(-change[kinks - 1])[:budget]]
    edges = np.unique(np.concatenate([
        np.linspace(0, height, max(2, min(max_bands, 3 + kinks.size)) + 1).astype(int),
        kinks,
        [0, height],
    ]))
    # A band narrower than a couple of rows gets skipped by the loop below, and a
    # skipped row inside the head is a visible one-row seam - merge them away.
    kept: list[int] = []
    for edge in (int(e) for e in edges):
        if not kept or edge - kept[-1] >= 3:
            kept.append(edge)
        else:
            kept[-1] = max(kept[-1], edge)
    if kept[-1] != height:
        if height - kept[-1] < 3 and len(kept) > 1:
            kept.pop()
        kept.append(height)
    return kept


def shear_rows_fast(image: Image.Image, offsets, max_bands: int = 12) -> Image.Image:
    """shear_rows for the running pet: one C-level affine resample per linear run."""
    height, width = image.height, image.width
    off = _profile(height, offsets)
    out = image.copy()
    edges = _band_edges(off, max_bands)
    for y0, y1 in zip(edges[:-1], edges[1:]):
        if y1 - y0 < 2:
            continue
        a, b = off[y0], off[y1 - 1]
        if abs(a) < 0.01 and abs(b) < 0.01:
            continue  # already in place; copying is the identity
        slope = (b - a) / (y1 - 1 - y0) if y1 - 1 > y0 else 0.0
        band = image.transform(
            (width, y1 - y0),
            Image.Transform.AFFINE,
            (1.0, -slope, -a, 0.0, 1.0, y0),
            resample=Image.Resampling.BILINEAR,
            fillcolor=(0, 0, 0, 0),
        )
        out.paste(band, (0, y0))
    return out


def band_scale_fast(image: Image.Image, top: float, bottom: float, factor: float) -> Image.Image:
    """band_scale for the running pet: a single vertical affine over the band."""
    height, width = image.height, image.width
    top_i, bottom_i = max(0, int(top)), min(height, int(bottom))
    if bottom_i - top_i < 2 or factor <= 0 or abs(factor - 1.0) < 1e-4:
        return image
    centre = (top_i + bottom_i) / 2.0
    band = image.transform(
        (width, bottom_i - top_i),
        Image.Transform.AFFINE,
        (1.0, 0.0, 0.0, 0.0, 1.0 / factor, centre + (top_i - centre) / factor),
        resample=Image.Resampling.BILINEAR,
        fillcolor=(0, 0, 0, 0),
    )
    out = image.copy()
    out.paste(band, (0, top_i))
    return out


def squash_stretch(image: Image.Image, vertical: float, anchor_row: float, bulge: float = 0.6) -> Image.Image:
    """Squash or stretch about one row, with the body bulging sideways to match.

    A vertical-only squash reads as a rubber sheet: she just gets shorter. Real
    weight-shifting also widens her, so the horizontal factor is derived from the
    vertical one at `bulge` of the volume-preserving amount.
    """
    if abs(vertical - 1.0) < 1e-4:
        return image
    fx = 1.0 + (1.0 / vertical - 1.0) * bulge
    cx = image.width / 2.0
    return image.transform(
        (image.width, image.height),
        Image.Transform.AFFINE,
        (
            1.0 / fx, 0.0, cx - cx / fx,
            0.0, 1.0 / vertical, anchor_row - anchor_row / vertical,
        ),
        resample=Image.Resampling.BILINEAR,
        fillcolor=(0, 0, 0, 0),
    )


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


class LifeLayer:
    """The never-repeating micro-motion she keeps while standing still.

    Baked frames loop, however many there are: at 24 frames over 4s a viewer learns
    the period inside a minute. This layer runs off-clock instead - three
    incommensurate sway periods, a slow breath, random blink gaps and an occasional
    deliberate head turn - so a calm state has no seam to find. Amplitudes are
    multiples of a 208px cell, so a 2x render needs no retuning.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.random = random.Random() if rng is None else rng
        self.t0 = time.time()
        self.phase = self.random.uniform(0.0, math.tau)
        self.next_blink = self.t0 + self.random.uniform(1.2, 3.5)
        self.blink_until = 0.0
        self.next_turn = self.t0 + self.random.uniform(7.0, 20.0)
        self.turn_from = 0.0
        self.turn_until = 0.0
        self.turn_dir = 1.0
        self.eye_row: float | None = None
        self.chin_row: float | None = None

    def set_landmarks(self, eye_row: float | None, chin_row: float | None) -> None:
        self.eye_row = eye_row
        self.chin_row = chin_row

    def offsets(self, height: int, now: float) -> np.ndarray:
        """Sway and any deliberate turn, added into one per-row profile.

        Every horizontal runtime effect - sway, gaze, turn, the lean from a throw - is
        a per-row shift, so the pet sums them and shears once instead of once each.
        Three gathers at 269x291 cost ~5ms; one costs 1.7ms.
        """
        unit = height / 208.0
        t = now - self.t0
        sway = (
            0.60 * math.sin(t * 0.90 + self.phase)
            + 0.29 * math.sin(t * 0.37 + 0.4)
            + 0.11 * math.sin(t * 1.73 + 1.1)
        ) * 2.4 * unit
        profile = simple_pendulum(height, height * 0.66, sway, rigid_above=height * 0.30)
        turn = self._turn(now, unit)
        if turn:
            profile = profile + head_follow_profile(
                height, self.chin_row, turn, shoulder=26.0 * unit
            )
        return profile

    def breath(self, now: float) -> float:
        t = now - self.t0
        return 1.0 + 0.012 * math.sin(t * (math.tau / 3.9) + self.phase) + 0.004 * math.sin(t * 0.21)

    def blink(self, now: float) -> float:
        if now >= self.next_blink:
            self.blink_until = now + 0.09
            self.next_blink = now + self.random.uniform(2.2, 7.5)
        return 0.55 if now < self.blink_until else 1.0

    def blink_band(self, height: int) -> tuple[float, float] | None:
        if self.eye_row is None:
            return None
        unit = height / 208.0
        return (self.eye_row - 6.0 * unit, self.eye_row + 8.0 * unit)

    def _turn(self, now: float, unit: float) -> float:
        """Envelope-shaped head turn: eases out and back, never a step."""
        if now >= self.next_turn:
            self.turn_from = now
            self.turn_until = now + self.random.uniform(0.8, 1.5)
            self.turn_dir = self.random.choice((-1.0, 1.0))
            self.next_turn = self.turn_until + self.random.uniform(6.0, 24.0)
        if not (self.turn_from <= now < self.turn_until) or self.chin_row is None:
            return 0.0
        progress = (now - self.turn_from) / (self.turn_until - self.turn_from)
        return self.turn_dir * 2.6 * unit * math.sin(math.pi * progress)


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


def drop_detached(image: Image.Image, limit_row: int, limit_col: int) -> Image.Image:
    """Erase alpha blobs that sit entirely inside the top-left corner.

    The sheet's charm hangs from the cell ceiling, which a free-floating window has
    no use for, but it swings and droops by state, so a fixed box either leaves a
    sliver behind or eats into the hat. Detachment is the reliable signal: anything
    connected to her body survives, an isolated corner ornament goes.
    """
    from collections import deque

    arr = np.array(image.convert("RGBA"))
    alpha = arr[:, :, 3] > 0
    seen = np.zeros(alpha.shape, dtype=bool)
    height, width = alpha.shape
    removed = 0
    for sy in range(min(limit_row, height)):
        for sx in range(min(limit_col, width)):
            if not alpha[sy, sx] or seen[sy, sx]:
                continue
            queue = deque([(sy, sx)])
            seen[sy, sx] = True
            blob = [(sy, sx)]
            while queue:
                y, x = queue.popleft()
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < height and 0 <= nx < width and alpha[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
                        blob.append((ny, nx))
            if max(b[0] for b in blob) < limit_row and max(b[1] for b in blob) < limit_col:
                for y, x in blob:
                    alpha[y, x] = False
                removed += len(blob)
    arr[:, :, 3] = np.where(alpha, 255, 0).astype(np.uint8)
    arr[arr[:, :, 3] == 0, :3] = 0
    return Image.fromarray(arr, "RGBA")
