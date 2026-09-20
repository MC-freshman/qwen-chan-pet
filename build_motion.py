"""Dense, layered animation frames for the standalone pet.

The Qoder package is capped at 8 frames per row, so this emits two things from one
pass: app/frames/<state>/*.png at full frame rate for the pet, and a subsampled
spritesheet for the Qoder pet package. Secondary motion, breathing and blinking are
applied on top of the base choreography in build_qwen_spritesheet.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import build_qwen_spritesheet as base  # noqa: E402  (the pose/safe-area pipeline)
import rigor  # noqa: E402

FRAMES = {
    "idle": 16,
    "running-right": 12,
    "running-left": 12,
    "waving": 8,
    "jumping": 10,
    "failed": 16,
    "waiting": 16,
    "running": 12,
    "review": 12,
}
CALM = {"idle", "waiting", "review", "failed"}
HEAD_SECTOR = (-140.0, -40.0)   # image y grows down, so "up" is -90
SKIRT_SECTOR = (40.0, 140.0)
HIP_FRACTION = 0.66  # sway pivot, measured down the sprite
NECK_FRACTION = 0.30  # rows above this stay rigid, so the hat never smears
EYE_BAND = (0.155, 0.215)  # eyes sit here within the art height on a chibi
BLINK_WINDOW = 0.09

CELL_W, CELL_H = base.FRAME_W, base.FRAME_H
OUT_FRAMES = ROOT / "app" / "frames"
OUT_SHEET = ROOT / "out" / "spritesheet.webp"


def part_rig(sprite: Image.Image) -> dict:
    """Pivots and radii derived from the silhouette, so every pose rigs itself."""
    import numpy as np

    box = sprite.getchannel("A").getbbox() or (0, 0, sprite.width, sprite.height)
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    cx = left + w / 2
    return {
        "head": {"pivot": (cx, top + h * 0.34), "r_in": h * 0.02, "r_out": h * 0.34,
                 "sector": HEAD_SECTOR},
        "skirt": {"pivot": (cx, top + h * 0.60), "r_in": h * 0.06, "r_out": h * 0.46,
                  "sector": SKIRT_SECTOR},
    }


def spring_series(state: str, count: int) -> tuple[list, list]:
    """Run the springs across the loop twice so the recorded frames start settled."""
    head, skirt = [], []
    sh, ss = rigor.Spring(k=52.0, c=7.4), rigor.Spring(k=34.0, c=5.2)
    dt = 1.0 / 16.0   # 软弹簧：跑动的横向甩动交给速度驱动的钟摆剪切，这里只管滞后回弹
    for lap in range(3):
        head, skirt = [], []
        for index in range(count):
            ahead = motion_at(state, (index + 1) % count, count)
            behind = motion_at(state, (index - 1) % count, count)
            vx = (ahead[0] - behind[0]) * 0.5
            vy = (ahead[1] - behind[1]) * 0.5
            tilt_v = (ahead[2] - behind[2]) * 0.5
            # head fights the body, skirt trails it
            ht = -tilt_v * 2.2 - vx * 0.35
            st = -vx * 2.6 - vy * 0.5
            if lap == 2:
                head.append(sh.step(ht, dt))
                skirt.append(ss.step(st, dt))
            else:
                sh.step(ht, dt); ss.step(st, dt)
    return head, skirt


def face_lines(content: Image.Image) -> dict:
    """Locate the eyes as the only row band with two separated dark clusters.

    Fraction-of-art-height guesses land on the hat, which is what smeared the brim.
    """
    import numpy as np

    arr = np.array(content.convert("RGB")).astype(int)
    alpha = np.array(content.getchannel("A"))
    alpha[:44, :76] = 0
    ys, _ = np.nonzero(alpha)
    if len(ys) == 0:
        return {"eye": content.height * 0.2, "chin": content.height * 0.3}
    top, bottom = int(ys.min()), int(ys.max())
    height = max(1, bottom - top)
    dark = (arr.sum(axis=2) < 340) & (alpha > 128)
    best = None
    for y in range(top + int(height * 0.12), top + int(height * 0.42)):
        cols = np.flatnonzero(dark[y])
        if len(cols) < 8:
            continue
        gaps = np.flatnonzero(np.diff(cols) > 6)
        if len(gaps) < 1:
            continue
        left, right = cols[: gaps[0] + 1], cols[gaps[-1] + 1 :]
        if len(left) < 3 or len(right) < 3:
            continue
        spread = int(right.mean() - left.mean())
        if not 12 <= spread <= int(content.width * 0.7):
            continue
        # 真眼睛关于脸的中轴大致对称、两大小相近；帽子的花饰不满足
        centre = int(alpha[y].nonzero()[0].mean()) if alpha[y].any() else content.width // 2
        if abs((left.mean() + right.mean()) / 2 - centre) > content.width * 0.16:
            continue
        if min(len(left), len(right)) / max(len(left), len(right)) < 0.45:
            continue
        if best is None or (y - top) < best[0]:
            best = (y - top, y)
    if best is None:
        return {"eye": None, "chin": None}          # 不确定就不做眨眼，别压坏帽子
    eye = top + best[0]
    return {"eye": eye, "chin": eye + max(6, int(height * 0.09))}


def motion_at(state: str, index: int, count: int) -> tuple[float, float, float, float]:
    """Sample the hand-authored keyframes cyclically at a denser frame rate."""
    keys = base.MOTION[state]
    t = index / count * len(keys)
    i0 = int(t) % len(keys)
    i1 = (i0 + 1) % len(keys)
    f = t - int(t)
    return tuple(keys[i0][k] + (keys[i1][k] - keys[i0][k]) * f for k in range(4))


def place(content: Image.Image, dx: float, dy: float, state: str) -> Image.Image:
    frame = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    cw, ch = content.size
    x = round((CELL_W - cw) / 2 + dx + base.FIT[state][1])
    y = round(CELL_H - base.BASELINE - ch + dy)
    x = max(base.SAFE_SIDE, min(CELL_W - cw - base.SAFE_SIDE, x))
    y = max(base.SAFE_TOP, min(CELL_H - ch - base.FOOT_MARGIN, y))
    swing = max(-20.0, min(20.0, -(dx * 4.5)))
    frame.alpha_composite(base.draw_charm(swing=swing, droop=1.0 if state == "failed" else 0.0), (12, 0))
    frame.alpha_composite(content, (x, y))
    return frame


def art_span(content: Image.Image) -> tuple[int, int]:
    box = content.getchannel("A").getbbox() or (0, 0, 1, 1)
    return box[1], box[3]


def fit_state(state: str, count: int, sprite: Image.Image) -> Image.Image:
    """base.fit_state indexes the sparse keyframes, so re-derive the fit from the dense ones."""
    height = base.FIT[state][0]
    for _ in range(12):
        scaled = base.fit(sprite, height)
        need_h = need_w = 0
        for index in range(count):
            dx, dy, tilt, squash = motion_at(state, index, count)
            body = base.transform(scaled, dx, dy, tilt, squash)
            box = body.getchannel("A").getbbox()
            cw, ch = body.crop(box).size
            need_h = max(need_h, ch - min(dy, 0))
            need_w = max(need_w, cw + 2 * abs(dx + base.FIT[state][1]))
        if need_h <= CELL_H - base.BASELINE - base.SAFE_TOP and need_w <= CELL_W - base.SAFE_SIDE * 2:
            return scaled
        height = int(height * 0.96)
    return base.fit(sprite, height)


def animate(state: str, index: int, count: int, sprite: Image.Image,
            springs: tuple) -> Image.Image:
    dx, dy, tilt, squash = motion_at(state, index, count)
    body = base.transform(sprite, dx, dy, tilt, squash)
    box = body.getchannel("A").getbbox()
    content = body.crop(box)
    top, bottom = art_span(content)
    height = max(1, bottom - top)

    # Extremities trail the body: derive the sway from the motion's own velocity.
    ahead = motion_at(state, (index + 1) % count, count)
    behind = motion_at(state, (index - 1) % count, count)
    velocity_x = (ahead[0] - behind[0]) * 0.5
    velocity_y = (ahead[1] - behind[1]) * 0.5
    amp = -velocity_x * 1.9 - velocity_y * 0.5
    if abs(amp) > 0.15:
        content = rigor.shear_rows(
            content,
            rigor.simple_pendulum(
                content.height, top + height * HIP_FRACTION, amp,
                rigid_above=top + height * NECK_FRACTION,
            ),
        )

    # Real joints: the head counter-rotates to hold the gaze while the skirt trails.
    # Pivots come from the deformed silhouette, so they follow tilt and squash.
    rig = part_rig(content)
    head_amp, skirt_amp = springs
    for part, value in (("head", head_amp[index]), ("skirt", skirt_amp[index])):
        if abs(value) < 0.25:
            continue
        spec = rig[part]
        content = rigor.polar_twist(
            content, spec["pivot"], value,
            spec["r_in"], spec["r_out"], spec["sector"][0], spec["sector"][1],
        )

    phase = index / count
    if state in CALM:
        breath = 1.0 + 0.011 * math.sin(2 * math.pi * phase * 2)
        centre = top + height * 0.52
        content = rigor.band_scale(content, centre - height * 0.16, centre + height * 0.16, breath)

    # One blink per cycle, two frames wide, only where the loop is long enough.
    if count >= 12:
        offset = abs(math.sin(2 * math.pi * (phase + 0.37 * (index % 3))))
        if offset < BLINK_WINDOW:
            lines = face_lines(content)
            if lines["eye"] is not None:
                # 宽带 + 轻压：定位偏几行也只是柔和平移，不会拉出硬拖影
                content = rigor.band_scale(content, lines["eye"] - 6, lines["eye"] + 8, 0.55)
    return place(content, dx, dy, state)


def main() -> None:
    OUT_SHEET.parent.mkdir(exist_ok=True)
    (ROOT / "out" / "preview.png").parent.mkdir(exist_ok=True)
    sheet = Image.new("RGBA", (CELL_W * base.COLS, CELL_H * base.ROWS), (0, 0, 0, 0))
    rig_map = {}
    for row, state in enumerate(base.ROW_STATES if hasattr(base, "ROW_STATES") else [s for s, _ in base.STATES]):
        count = FRAMES[state]
        sprite = base.trim(base.cutout(base.find_source(base.POSES[state])))
        if state in base.MIRROR:
            sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        sprite = fit_state(state, count, sprite)
        springs = spring_series(state, count)
        folder = OUT_FRAMES / state
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.png"):
            old.unlink()
        frames = []
        for index in range(count):
            frame = base.clear_hidden_rgb(animate(state, index, count, sprite, springs))
            frame.save(folder / f"{index:02d}.png")
            frames.append(frame)
        rig_map[state] = face_lines(Image.open(sorted(folder.glob("*.png"))[0]).convert("RGBA"))
        keep = min(base.COLS, count)
        picks = [frames[round(k * (count - 1) / (keep - 1))] for k in range(keep)] if keep > 1 else frames
        for col, frame in enumerate(picks):
            sheet.alpha_composite(frame, (col * CELL_W, row * CELL_H))
        print(f"{state:14s} {count} frames -> sheet row {row} keeps {len(picks)}")
    import json
    (OUT_FRAMES / "rig.json").write_text(json.dumps(rig_map, ensure_ascii=False, indent=2), encoding="utf-8")
    for state, lines in rig_map.items():
        eye = lines["eye"]
        print(f"  {state:14s} eye={int(eye) if eye else None} chin={int(lines['chin']) if lines['chin'] else None}")
    sheet.save(OUT_SHEET, lossless=True)
    sheet.save(ROOT / "out" / "spritesheet.png")
    base.preview(ROOT / "out" / "preview.png")
    contact(ROOT / "out" / "contact.png")
    verify()
    print(f"sheet -> {OUT_SHEET}")


def contact(target: Path) -> None:
    states = ["idle", "running-right", "waiting"]
    tiles = []
    for state in states:
        folder = OUT_FRAMES / state
        files = sorted(folder.glob("*.png"))
        strip = Image.new("RGBA", (CELL_W * len(files), CELL_H), (250, 250, 252, 255))
        for col, path in enumerate(files):
            strip.alpha_composite(Image.open(path).convert("RGBA"), (col * CELL_W, 0))
        tiles.append((state, strip))
    canvas = Image.new("RGB", (max(t.width for _, t in tiles), sum(t.height for _, t in tiles)), (250, 250, 252))
    y = 0
    for _, strip in tiles:
        canvas.paste(strip.convert("RGB"), (0, y))
        y += strip.height
    canvas.save(target)


def verify() -> None:
    clear = {"left": 999, "right": 999, "top": 999, "bottom": 999}
    total = 0
    for state, count in FRAMES.items():
        for path in sorted((OUT_FRAMES / state).glob("*.png")):
            box = Image.open(path).getchannel("A").getbbox()
            if box is None:
                raise RuntimeError(f"empty frame {path}")
            left, top, right, bottom = box
            if left < 0 or top < 0 or right > CELL_W or bottom > CELL_H:
                raise RuntimeError(f"{path} overflows the cell: {box}")
            clear["left"] = min(clear["left"], left)
            clear["top"] = min(clear["top"], top)
            clear["right"] = min(clear["right"], CELL_W - right)
            clear["bottom"] = min(clear["bottom"], CELL_H - bottom)
            total += 1
    print(f"{total} frames, tightest clearance {clear}")


if __name__ == "__main__":
    main()
