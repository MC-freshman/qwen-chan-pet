"""The pose source and the shared geometry every qwen-chan frame is built on.

Not a spritesheet builder: `build_motion.py` is the only producer, and it emits
per-state frame folders for the standalone pet. What lives here is the part that
script needs and the pet itself never recomputes - where the AI poses are, how they
get cut out and colour-matched, the authored keyframes, and the safe box a frame's
silhouette must stay inside.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "poses"

# Cell the choreography is authored in. The pet renders at a multiple of this and
# displays at a third scale, but every proportion below is cell pixels.
FRAME_W = 192
FRAME_H = 208
BASELINE = 12  # transparent pixels kept under the feet
PAD = 32       # working border used while rotating/squashing
SAFE_TOP = 34
SAFE_SIDE = 32
FOOT_MARGIN = 4  # feet may sink into the baseline reserve, but not past this

POSES = {
    "idle": "qwen-chibi-idle",
    "running-right": "qwen-chibi-running",
    "running-left": "qwen-chibi-running",
    "waving": "qwen-chibi-waving",
    "jumping": "qwen-chibi-jumping",
    "failed": "qwen-chibi-failed",
    "waiting": "qwen-chibi-waiting",
    "running": "qwen-chibi-running",
    "review": "qwen-chibi-review",
}

# (dx, dy, tilt_deg, squash) per keyframe; squash>0 stretches vertically.
# running-left is deliberately absent - it borrows running-right wholesale and the
# finished frames get flipped, because negating a directional amplitude is not a
# mirror (see MIRROR_SOURCE in build_motion.py).
MOTION = {
    "idle": [
        (0, 0, 0.0, 0.00),
        (0, -2, -1.0, 0.01),
        (1, -3, -1.5, 0.015),
        (1, -2, -0.5, 0.005),
        (0, -1, 0.8, -0.005),
        (0, 0, 0.0, 0.00),
    ],
    "running-right": [
        (-4, 0, 3.0, -0.02),
        (-2, -5, 4.0, 0.03),
        (0, -8, 4.5, 0.04),
        (2, -5, 4.0, 0.02),
        (4, 0, 3.0, -0.02),
        (2, -5, 4.0, 0.03),
        (0, -8, 4.5, 0.04),
        (-2, -5, 3.5, 0.02),
    ],
    "waving": [
        (0, 0, -2.5, 0.00),
        (0, -3, 2.5, 0.02),
        (0, -4, -2.0, 0.01),
        (0, -1, 2.0, 0.00),
    ],
    "jumping": [
        (0, 2, 0.0, -0.06),
        (0, -14, -3.0, 0.09),
        (0, -26, 0.0, 0.12),
        (0, -12, 3.0, 0.06),
        (0, 3, 0.0, -0.07),
    ],
    "failed": [
        (0, 0, 0.0, 0.00),
        (0, 1, -1.5, -0.01),
        (1, 3, -3.0, -0.02),
        (1, 5, -4.0, -0.025),
        (0, 6, -4.5, -0.03),
        (0, 5, -4.0, -0.025),
        (-1, 3, -2.5, -0.015),
        (0, 1, -1.0, -0.005),
    ],
    "waiting": [
        (0, 0, 0.0, 0.00),
        (0, 1, 1.0, -0.01),
        (1, 3, 2.0, -0.02),
        (1, 4, 2.5, -0.025),
        (0, 2, 1.0, -0.01),
        (0, 0, 0.0, 0.00),
    ],
    "running": [
        (0, 0, 0.0, -0.02),
        (0, -6, 1.5, 0.03),
        (0, -9, 0.0, 0.04),
        (0, -6, -1.5, 0.03),
        (0, 0, 0.0, -0.02),
        (0, -5, 1.0, 0.02),
    ],
    "review": [
        (0, 0, 0.0, 0.00),
        (-1, -1, -1.5, 0.01),
        (-2, -2, -2.5, 0.015),
        (-1, -1, -1.0, 0.005),
        (1, 0, 1.5, -0.005),
        (2, -1, 2.5, 0.01),
    ],
}

# Per-state sprite sizing: height inside the cell and horizontal bias.
FIT = {
    "idle": (176, 0),
    "running-right": (168, 2),
    "waving": (172, 0),
    "jumping": (168, 0),
    "failed": (172, 0),
    "waiting": (158, 0),
    "running": (164, 0),
    "review": (174, 0),
}


def palette_anchors(image: Image.Image):
    """(dark mean, hair mean, light mean) per channel, plus the hair band's luminance.

    The navy hat and cape come out of every generation within a couple of levels and
    so does the white petticoat, while the lavender hair wanders by up to twenty -
    the hair band is what needs pulling back, and the two flanking anchors say how far
    the correction has to fade out before it reaches them.
    """
    import numpy as np

    rgb = np.asarray(image.convert("RGB")).astype(float)
    alpha = np.asarray(image.getchannel("A")) > 128
    luma = rgb.mean(axis=2)
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    dark = alpha & (luma < 120)
    hair = alpha & (blue > red + 20) & (blue > 150) & (red > 90) & (red < 210)
    light = alpha & (rgb.min(axis=2) > 200)
    if dark.sum() < 20000 or hair.sum() < 20000 or light.sum() < 20000:
        return None
    return {
        "dark": rgb[dark].mean(axis=0),
        "hair": rgb[hair].mean(axis=0),
        "light": rgb[light].mean(axis=0),
        "luma": float(luma[hair].mean()),
        "dark_luma": float(luma[dark].mean()),
        "light_luma": float(luma[light].mean()),
    }


def match_palette(image: Image.Image, reference: Image.Image) -> Image.Image:
    """Pull a pose's hair band onto the reference palette, fading out before the navy
    and the whites.

    Each generation of AI art brings its own white balance, so two poses made in
    different runs alternate on screen as a hair colour flicker. Correcting the whole
    tonal range drags the hat and the petticoat with it, so the shift is applied at
    full strength only in the hair band and blended to zero at the two anchors around
    it - which is also why poses that are already in family are left byte-for-byte.
    """
    import numpy as np

    source = palette_anchors(image)
    target = palette_anchors(reference)
    if source is None or target is None:
        return image
    if float(np.abs(source["hair"] - target["hair"]).max()) < 6.0:
        return image

    rgb = np.asarray(image.convert("RGB")).astype(float)
    alpha = np.asarray(image.getchannel("A"))
    luma = rgb.mean(axis=2)

    def _fade(distance: np.ndarray, reach: float) -> np.ndarray:
        x = np.clip(1.0 - distance / max(1.0, reach), 0.0, 1.0)
        return x * x * (3.0 - 2.0 * x)

    below = max(20.0, source["luma"] - source["dark_luma"])
    above = max(20.0, source["light_luma"] - source["luma"])
    weight = _fade(np.maximum(0.0, source["luma"] - luma), below) * _fade(
        np.maximum(0.0, luma - source["luma"]), above
    )

    def _render(pixels: np.ndarray) -> Image.Image:
        out = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB")
        out.putalpha(Image.fromarray(alpha, "L"))
        return out

    # The band weight averages well under 1 across the hair mask, so one pass only
    # closes part of the gap; iterate on what the previous pass actually measured.
    pixels = rgb
    for _ in range(4):
        now = palette_anchors(_render(pixels))
        if now is None:
            return image
        residual = np.clip(target["hair"] - now["hair"], -30.0, 30.0)
        if float(np.abs(residual).max()) < 1.5:
            break
        pixels = pixels + residual[None, None, :] * weight[:, :, None]
    return _render(pixels)


def find_source(name: str) -> Path:
    hits = sorted(SRC.glob(f"{name}_*.png"))
    if not hits:
        raise FileNotFoundError(f"no generated pose for {name}")
    return hits[-1]


def cutout(path: Path, thresh: int = 16, min_area: int = 2000) -> Image.Image:
    """Drop the flat white studio background, keeping enclosed whites.

    R2 补丁：AI 出图会在背景上撒彩色噪点（孤立小连通域，grok娘 管线的
    drop_confetti 专治这个）。flood fill 只认与边角相连的近白区，彩噪既不白
    也不连边，会整个活下来、烙进每一帧，在深色桌面上就是一层雪花。
    按连通域面积剔除：主体是十万像素级，噪点是个位数像素级，2000 很安全。
    """
    import numpy as np
    from scipy import ndimage

    rgb = Image.open(path).convert("RGB")
    filled = rgb.copy()
    marker = (255, 0, 255)
    w, h = rgb.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        ImageDraw.floodfill(filled, corner, marker, thresh=thresh)
    inside = np.any(np.array(filled) != np.array(marker), axis=2)
    arr = np.array(rgb)
    alpha = (inside * 255).astype(np.uint8)
    solid = alpha >= 128
    lab, n = ndimage.label(solid)
    if n:
        sizes = ndimage.sum(solid, lab, range(1, n + 1))
        drop = np.isin(lab, np.nonzero(sizes < min_area)[0] + 1)
        alpha[drop] = 0
    out = np.dstack([arr, alpha])
    return Image.fromarray(out, "RGBA")


def trim(image: Image.Image) -> Image.Image:
    box = image.getchannel("A").getbbox()
    return image.crop(box) if box else image


def fit(image: Image.Image, height: int, max_width: int = FRAME_W - 6) -> Image.Image:
    scale = min(height / image.height, max_width / image.width)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def transform(
    image: Image.Image,
    dx: int,
    dy: int,
    tilt: float,
    squash: float,
    pad: int = PAD,
    foot: int = 6,
) -> Image.Image:
    """Squash and rotate on a padded layer so the sprite canvas never cuts hair or fan.

    pad/foot are cell pixels, so a caller rendering at 2x the cell passes 2x of each.
    """
    w, h = image.size
    src = image
    if squash:
        nw = max(1, round(w * (1 - squash * 0.45)))
        nh = max(1, round(h * (1 + squash)))
        stretched = src.resize((nw, nh), Image.Resampling.LANCZOS)
        src = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        src.alpha_composite(stretched, ((w - nw) // 2, h - nh))
    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    layer.alpha_composite(src, (pad, pad))
    if tilt:
        layer = layer.rotate(
            tilt,
            resample=Image.Resampling.BICUBIC,
            center=(pad + w // 2 + dx, pad + h - foot),
        )
    return layer


def clear_hidden_rgb(image: Image.Image) -> Image.Image:
    """Zero the RGB under fully transparent pixels: they never show, and leaving the
    key colour there would make two identical frames hash differently."""
    import numpy as np

    arr = np.array(image)
    arr[arr[:, :, 3] == 0, :3] = 0
    return Image.fromarray(arr)
