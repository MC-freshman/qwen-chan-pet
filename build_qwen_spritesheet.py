"""Build the Qoder desktop-pet spritesheet for the qwen-chan pet.

Layout matches the Petdex/Codex v1 sheet the existing pets use:
8 columns x 9 rows of 192x208 cells, one animation state per row.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "poses"
OUT = ROOT / "out"

FRAME_W = 192
FRAME_H = 208
COLS = 8
ROWS = 9
BASELINE = 12  # transparent pixels kept under the feet
PAD = 32  # working border used while rotating/squashing
# Qoder renders a 192x208 cell into a 128x176 window, and the fit mode is not
# documented. Keeping every frame inside a centred 128x176 box makes contain,
# cover, centre-crop and bottom-crop mappings all show her whole: a
# bottom-anchored 1:1 crop of this cell only ever reveals y >= 32.
SAFE_TOP = 34
SAFE_SIDE = 32
FOOT_MARGIN = 4  # feet may sink into the baseline reserve, but not past this

STATES = [
    ("idle", 6),
    ("running-right", 8),
    ("running-left", 8),
    ("waving", 4),
    ("jumping", 5),
    ("failed", 8),
    ("waiting", 6),
    ("running", 6),
    ("review", 6),
]

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

# (dx, dy, tilt_deg, squash) per frame; squash>0 stretches vertically.
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
    "running-left": [
        (4, 0, -3.0, -0.02),
        (2, -5, -4.0, 0.03),
        (0, -8, -4.5, 0.04),
        (-2, -5, -4.0, 0.02),
        (-4, 0, -3.0, -0.02),
        (-2, -5, -4.0, 0.03),
        (0, -8, -4.5, 0.04),
        (2, -5, -3.5, 0.02),
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
    "running-left": (168, -2),
    "waving": (172, 0),
    "jumping": (168, 0),
    "failed": (172, 0),
    "waiting": (158, 0),
    "running": (164, 0),
    "review": (174, 0),
}

MIRROR = {"running-left"}


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


def cutout(path: Path, thresh: int = 16) -> Image.Image:
    """Drop the flat white studio background, keeping enclosed whites."""
    import numpy as np

    rgb = Image.open(path).convert("RGB")
    filled = rgb.copy()
    marker = (255, 0, 255)
    w, h = rgb.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        ImageDraw.floodfill(filled, corner, marker, thresh=thresh)
    inside = np.any(np.array(filled) != np.array(marker), axis=2)
    arr = np.array(rgb)
    out = np.dstack([arr, (inside * 255).astype(np.uint8)])
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

    pad/foot are cell pixels, so a caller rendering at 2x the sheet passes 2x of each.
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


def draw_charm(swing: float, droop: float = 0.0, size: int = 64) -> Image.Image:
    """Qwen six-petal emblem on a short chain, drawn oversized then downscaled."""
    ss = 4
    layer = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = size * ss // 2
    chain_len = 20 + droop * 6
    top = (cx, 0)
    sway_x = math.sin(math.radians(swing)) * chain_len * 0.6
    sway_y = math.cos(math.radians(swing)) * chain_len
    px = cx + sway_x * ss
    py = sway_y * ss
    d.line([top[0], top[1], px, py], fill=(150, 160, 205, 200), width=2 * ss)
    ring_r = 9.0 * ss
    petal_r = 7.4 * ss
    d.ellipse([px - ring_r, py - ring_r, px + ring_r, py + ring_r], fill=(43, 55, 110, 255))
    for i in range(6):
        a = math.radians(60 * i - 90 + swing * 0.4)
        ex = px + math.cos(a) * petal_r * 0.52
        ey = py + math.sin(a) * petal_r * 0.52
        rr = petal_r * 0.46
        d.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], fill=(250, 251, 255, 255))
    core = 1.9 * ss
    d.ellipse([px - core, py - core, px + core, py + core], fill=(216, 178, 108, 255))
    return layer.resize((size, size), Image.Resampling.LANCZOS)


CLAMPED: list[str] = []


def frame_content(
    state: str, index: int, sprite: Image.Image
) -> tuple[Image.Image, int, int, float]:
    dx, dy, tilt, squash = MOTION[state][index]
    body = transform(sprite, dx, dy, tilt, squash)
    box = body.getchannel("A").getbbox()
    return body.crop(box), dx, dy, tilt


def fit_state(state: str, count: int, sprite: Image.Image) -> Image.Image:
    """Shrink a state's sprite until its widest/tallest frame still fits the cell."""
    height = FIT[state][0]
    for _ in range(12):
        scaled = fit(sprite, height)
        need_h = need_w = 0
        for index in range(count):
            content, dx, dy, _tilt = frame_content(state, index, scaled)
            cw, ch = content.size
            need_h = max(need_h, ch - min(dy, 0))
            need_w = max(need_w, cw + 2 * abs(dx + FIT[state][1]))
        if need_h <= FRAME_H - BASELINE - SAFE_TOP and need_w <= FRAME_W - SAFE_SIDE * 2:
            return scaled
        height = int(height * 0.96)
    return fit(sprite, height)


def compose(state: str, index: int, sprite: Image.Image) -> Image.Image:
    frame = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
    content, dx, dy, tilt = frame_content(state, index, sprite)
    cw, ch = content.size
    x = (FRAME_W - cw) // 2 + dx + FIT[state][1]
    y = FRAME_H - BASELINE - ch + dy
    clamped_x = max(SAFE_SIDE, min(FRAME_W - cw - SAFE_SIDE, x))
    clamped_y = max(SAFE_TOP, min(FRAME_H - ch - FOOT_MARGIN, y))
    if (clamped_x, clamped_y) != (x, y):
        CLAMPED.append(f"{state}/{index:02d}")
    swing = max(-20.0, min(20.0, -(dx * 4.5 + tilt * 3.0)))
    charm = draw_charm(swing=swing, droop=1.0 if state == "failed" else 0.0)
    frame.alpha_composite(charm, (44 - 32, 0))
    frame.alpha_composite(content, (clamped_x, clamped_y))
    return frame


def clear_hidden_rgb(image: Image.Image) -> Image.Image:
    import numpy as np

    arr = np.array(image)
    arr[arr[:, :, 3] == 0, :3] = 0
    return Image.fromarray(arr)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    sheet = Image.new("RGBA", (FRAME_W * COLS, FRAME_H * ROWS), (0, 0, 0, 0))
    qa_root = OUT / "qa"
    for row, (state, count) in enumerate(STATES):
        sprite = trim(cutout(find_source(POSES[state])))
        if state in MIRROR:
            sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        sprite = fit_state(state, count, sprite)
        state_dir = qa_root / state
        state_dir.mkdir(parents=True, exist_ok=True)
        for old in state_dir.glob("*.png"):
            old.unlink()
        for index in range(count):
            frame = clear_hidden_rgb(compose(state, index, sprite))
            frame.save(state_dir / f"{index:02d}.png")
            sheet.alpha_composite(frame, (index * FRAME_W, row * FRAME_H))
        print(f"{state}: {count} frames")
    sheet.save(OUT / "spritesheet.png")
    sheet.save(OUT / "spritesheet.webp", lossless=True)
    preview(OUT / "preview.png")
    (OUT / "pet.json").write_text(
        json.dumps(
            {
                "id": "qwen-chan",
                "displayName": "qwen娘",
                "description": "通义千问 Q 版桌宠：蓝发麻花辫、礼帽与六瓣徽记挂饰，持梅纹折扇，含待机/左右跑动/挥手/跳跃/沮丧/等待/小跑/审阅九组动作。",
                "spritesheetPath": "spritesheet.webp",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"sheet {sheet.size} -> {OUT / 'spritesheet.webp'}")
    verify()


def verify() -> None:
    clear = {"left": 99, "right": 99, "bottom": 99}
    for state, count in STATES:
        for index in range(count):
            path = OUT / "qa" / state / f"{index:02d}.png"
            box = Image.open(path).getchannel("A").getbbox()
            if box is None:
                raise RuntimeError(f"empty frame: {path}")
            left, _top, right, bottom = box
            clear["left"] = min(clear["left"], left)
            clear["right"] = min(clear["right"], FRAME_W - right)
            clear["bottom"] = min(clear["bottom"], FRAME_H - bottom)
    print(f"tightest edge clearance: {clear}")
    print(f"clamped frames: {CLAMPED or 'none'}")


def preview(target: Path) -> None:
    sheet = Image.open(OUT / "spritesheet.png").convert("RGBA")
    pad = 26
    canvas = Image.new("RGBA", (sheet.width + pad, sheet.height + pad * ROWS), (245, 246, 250, 255))
    try:
        font = ImageFont.truetype("arial.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(canvas)
    for row, (state, _) in enumerate(STATES):
        y = pad * row + row * FRAME_H
        draw.text((4, y + 4), f"{row} {state}", fill=(60, 60, 80, 255), font=font)
        canvas.alpha_composite(
            sheet.crop((0, row * FRAME_H, FRAME_W * COLS, (row + 1) * FRAME_H)), (pad, y)
        )
    canvas.save(target)


if __name__ == "__main__":
    main()
