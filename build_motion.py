"""Dense, layered animation frames for the standalone pet.

The Qoder package is capped at 8 frames per row of 192x208, so this emits two
things from one pass:

* app/frames/<state>/*.png at S x the sheet resolution, at full frame rate, and
  without the ceiling charm - a free-floating window has no ceiling to hang it from,
  and erasing it at load time used to cost a pixel flood-fill per frame.
* out/spritesheet.webp, the Qoder package sheet, downsampled back to 192x208 cells
  with the charm kept in-sheet.

Secondary motion, breathing and blinking are applied on top of the base
choreography in build_qwen_spritesheet. Playback timing comes from config.json so
the pet and this script never disagree about how long a loop lasts.
"""

from __future__ import annotations

import json
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

# Rendering runs at a multiple of the sheet cell because the source poses are
# 1024x1024: squeezing them straight into 192x208 threw away 5x of linear detail,
# and the pet then blew the result back up to ~269px for a 175%-DPI display.
S = 2

FRAMES = {
    "idle": 24,
    "running-right": 16,
    "running-left": 16,
    "waving": 16,
    "jumping": 16,
    "failed": 24,
    "waiting": 24,
    "running": 16,
    "review": 20,
}
CALM = {"idle", "waiting", "review", "failed"}
HEAD_SECTOR = (-140.0, -40.0)   # image y grows down, so "up" is -90
SKIRT_SECTOR = (40.0, 140.0)
HIP_FRACTION = 0.66  # sway pivot, measured down the sprite
NECK_FRACTION = 0.30  # rows above this stay rigid, so the hat never smears
BLINK_WINDOW = 0.09

CELL_W, CELL_H = base.FRAME_W * S, base.FRAME_H * S
SHEET_W, SHEET_H = base.FRAME_W, base.FRAME_H
SAFE_SIDE = base.SAFE_SIDE * S
SAFE_TOP = base.SAFE_TOP * S
BASELINE = base.BASELINE * S
FOOT_MARGIN = base.FOOT_MARGIN * S
PAD = base.PAD * S
FOOT = 6 * S          # tilt pivot, measured up from the sprite's feet
CHARM = 64 * S        # the emblem layer, in render pixels
CHARM_X = 12 * S
MASK_BOX = (44 * S, 76 * S)  # top-left corner: the charm, never her
SPREAD_MIN = 12 * S   # smallest credible eye separation for face_lines
GAP = 6 * S           # dark-pixel gap that counts as two separate clusters
BLINK_LIP = 6 * S     # how far the blink band reaches above the eye line
BLINK_CHIN = 8 * S

FIT = {state: (height * S, bias * S) for state, (height, bias) in base.FIT.items()}
MOTION = {
    state: [(dx * S, dy * S, tilt, squash) for dx, dy, tilt, squash in keys]
    for state, keys in base.MOTION.items()
}

OUT_FRAMES = ROOT / "app" / "frames"
OUT_SHEET = ROOT / "out" / "spritesheet.webp"
CONFIG = ROOT / "app" / "config.json"


def cycle_seconds() -> dict[str, float]:
    """How long one loop of each state lasts, shared with the running pet."""
    table = json.loads(CONFIG.read_text(encoding="utf-8"))["cycle_seconds"]
    missing = set(FRAMES) - set(table)
    if missing:
        raise KeyError(f"config.json 的 cycle_seconds 缺少状态：{sorted(missing)}")
    return table


def spring_series(state: str, count: int, cycle: float) -> tuple[list, list]:
    """Run the springs across the loop twice so the recorded frames start settled."""
    dt = cycle / count
    head, skirt = [], []
    sh, ss = rigor.Spring(k=52.0, c=7.4), rigor.Spring(k=34.0, c=5.2)
    # 软弹簧：跑动的横向甩动交给速度驱动的钟摆剪切，这里只管滞后回弹
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
                sh.step(ht, dt)
                ss.step(st, dt)
    return head, skirt


def face_lines(content: Image.Image) -> dict:
    """Locate the eyes as the only row band with two separated dark clusters.

    Fraction-of-art-height guesses land on the hat, which is what smeared the brim.
    """
    arr = np.array(content.convert("RGB")).astype(int)
    alpha = np.array(content.getchannel("A"))
    alpha[: MASK_BOX[0], : MASK_BOX[1]] = 0
    ys, _ = np.nonzero(alpha)
    if len(ys) == 0:
        return {"eye": content.height * 0.2, "chin": content.height * 0.3}
    top, bottom = int(ys.min()), int(ys.max())
    height = max(1, bottom - top)
    dark = (arr.sum(axis=2) < 340) & (alpha > 128)
    best = None
    for y in range(top + int(height * 0.12), top + int(height * 0.42)):
        cols = np.flatnonzero(dark[y])
        if len(cols) < 8 * S:
            continue
        gaps = np.flatnonzero(np.diff(cols) > GAP)
        if len(gaps) < 1:
            continue
        left, right = cols[: gaps[0] + 1], cols[gaps[-1] + 1 :]
        if len(left) < 3 or len(right) < 3:
            continue
        spread = int(right.mean() - left.mean())
        if not SPREAD_MIN <= spread <= int(content.width * 0.7):
            continue
        # 真眼睛关于脸的中轴大致对称、两叶大小相近；帽子的花饰不满足
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
    return {"eye": eye, "chin": eye + max(FOOT, int(height * 0.09))}


def motion_at(state: str, index: int, count: int) -> tuple[float, float, float, float]:
    """Sample the hand-authored keyframes cyclically at a denser frame rate."""
    keys = MOTION[state]
    t = index / count * len(keys)
    i0 = int(t) % len(keys)
    i1 = (i0 + 1) % len(keys)
    f = t - int(t)
    return tuple(keys[i0][k] + (keys[i1][k] - keys[i0][k]) * f for k in range(4))


def charm_layer(state: str, dx: float) -> Image.Image:
    return base.draw_charm(
        swing=max(-20.0, min(20.0, -(dx * 4.5))),
        droop=1.0 if state == "failed" else 0.0,
        size=CHARM,
    )


def place(content: Image.Image, dx: float, dy: float, state: str, charm: bool) -> Image.Image:
    frame = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    cw, ch = content.size
    x = round((CELL_W - cw) / 2 + dx + FIT[state][1])
    y = round(CELL_H - BASELINE - ch + dy)
    x = max(SAFE_SIDE, min(CELL_W - cw - SAFE_SIDE, x))
    y = max(SAFE_TOP, min(CELL_H - ch - FOOT_MARGIN, y))
    if charm:
        frame.alpha_composite(charm_layer(state, dx), (CHARM_X, 0))
    frame.alpha_composite(content, (x, y))
    return frame


def art_span(content: Image.Image) -> tuple[int, int]:
    box = content.getchannel("A").getbbox() or (0, 0, 1, 1)
    return box[1], box[3]


def render_state(state: str, count: int, sprite: Image.Image, height: int, cycle: float,
                 baked_life: bool = True):
    scaled = base.fit(sprite, height, max_width=CELL_W - 6 * S)
    springs = spring_series(state, count, cycle)
    return scaled, [
        animate(state, index, count, scaled, springs, cycle, charm=False, baked_life=baked_life)
        for index in range(count)
    ]


def art_box(frame: Image.Image) -> tuple[int, int, int, int]:
    """Her bounding box alone; the ceiling charm may legitimately touch y = 0."""
    alpha = np.array(frame.getchannel("A"))
    alpha[: MASK_BOX[0], : MASK_BOX[1]] = 0
    ys, xs = np.nonzero(alpha)
    if len(ys) == 0:
        return (0, 0, 0, 0)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def fit_state(state: str, count: int, sprite: Image.Image, cycle: float):
    """Shrink until the *finished* frames fit the safe box.

    The previous estimate looked only at the pre-deformation sprite, so the pendulum,
    joint twist and blink could still push the silhouette past the cell edge - that is
    why the raised fan kept getting cut while jumping. Measured with the baked life
    layer on, since that is the largest the silhouette ever gets.
    """
    height = FIT[state][0]
    scaled, frames = render_state(state, count, sprite, height, cycle, baked_life=True)
    box = (0, 0, 0, 0)
    for _ in range(5):
        boxes = [art_box(frame) for frame in frames]
        left = min(b[0] for b in boxes)
        top = min(b[1] for b in boxes)
        right = max(b[2] for b in boxes)
        bottom = max(b[3] for b in boxes)
        box = (left, top, right, bottom)
        need = max(SAFE_SIDE - left, right - (CELL_W - SAFE_SIDE), SAFE_TOP - top)
        if need <= 0:
            break
        span = max(1.0, bottom - top)
        height = max(110 * S, int(height * max(0.80, 1.0 - need / span) * 0.97))
        scaled, frames = render_state(state, count, sprite, height, cycle, baked_life=True)
    return scaled, frames, box


def animate(
    state: str, index: int, count: int, sprite: Image.Image, springs: tuple,
    cycle: float, charm: bool = True, baked_life: bool = True,
) -> Image.Image:
    dx, dy, tilt, squash = motion_at(state, index, count)
    body = base.transform(sprite, dx, dy, tilt, squash, pad=PAD, foot=FOOT)
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
    if abs(amp) > 0.15 * S:
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
    for part, series in (("head", head_amp), ("skirt", skirt_amp)):
        value = series[index]
        if abs(value) < 0.25:
            continue
        spec = rig[part]
        content = rigor.polar_twist(
            content, spec["pivot"], value,
            spec["r_in"], spec["r_out"], spec["sector"][0], spec["sector"][1],
            feather=22.0 * S,
        )

    phase = index / count
    # Calm states get breathing and blinking from rigor.LifeLayer while she runs, off
    # the frame clock, so the loop has no period to learn; the Qoder sheet has no such
    # layer, so its cells keep them baked in.
    if baked_life and state in CALM:
        breath = 1.0 + 0.011 * math.sin(2 * math.pi * phase * 2)
        centre = top + height * 0.52
        content = rigor.band_scale(content, centre - height * 0.16, centre + height * 0.16, breath)

    # One blink per cycle, two frames wide - only where the loop is sampled finely
    # enough that two frames read as a blink instead of a hitch.
    if (baked_life or state not in CALM) and count / cycle >= 6:
        offset = abs(math.sin(2 * math.pi * (phase + 0.37 * (index % 3))))
        if offset < BLINK_WINDOW:
            lines = face_lines(content)
            if lines["eye"] is not None:
                # 宽带 + 轻压：定位偏几行也只是柔和平移，不会拉出硬拖影
                content = rigor.band_scale(
                    content, lines["eye"] - BLINK_LIP, lines["eye"] + BLINK_CHIN, 0.55
                )
    return place(content, dx, dy, state, charm)


def part_rig(sprite: Image.Image) -> dict:
    """Pivots and radii derived from the silhouette, so every pose rigs itself."""
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


def sheet_cell(frame: Image.Image) -> Image.Image:
    """Downsample one render-resolution frame back into the Qoder cell."""
    return frame.resize((SHEET_W, SHEET_H), Image.Resampling.LANCZOS)


def main() -> None:
    cycles = cycle_seconds()
    OUT_SHEET.parent.mkdir(exist_ok=True)
    sheet = Image.new("RGBA", (SHEET_W * base.COLS, SHEET_H * base.ROWS), (0, 0, 0, 0))
    rig_map = {}
    for row, state in enumerate(base.ROW_STATES if hasattr(base, "ROW_STATES") else [s for s, _ in base.STATES]):
        count = FRAMES[state]
        cycle = cycles[state]
        sprite = base.trim(base.cutout(base.find_source(base.POSES[state])))
        if state in base.MIRROR:
            sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        sprite, _probe, box = fit_state(state, count, sprite, cycle)
        springs = spring_series(state, count, cycle)
        folder = OUT_FRAMES / state
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.png"):
            old.unlink()
        for index in range(count):
            frame = animate(state, index, count, sprite, springs, cycle,
                            charm=False, baked_life=False)
            base.clear_hidden_rgb(frame).save(folder / f"{index:02d}.png")
        first = Image.open(sorted(folder.glob("*.png"))[0]).convert("RGBA")
        lines = face_lines(first)
        rig_map[state] = {
            "eye": None if lines["eye"] is None else lines["eye"] / CELL_H,
            "chin": None if lines["chin"] is None else lines["chin"] / CELL_H,
        }
        keep = min(base.COLS, count)
        picks = [round(k * (count - 1) / (keep - 1)) for k in range(keep)] if keep > 1 else [0]
        for col, index in enumerate(picks):
            # The sheet keeps its ceiling ornament and its baked breathing and blinks:
            # a Qoder pet window has no life layer running under it.
            charming = animate(state, index, count, sprite, springs, cycle,
                               charm=True, baked_life=True)
            sheet.alpha_composite(sheet_cell(charming), (col * SHEET_W, row * SHEET_H))
        print(f"{state:14s} {count:2d} frames / {cycle:.1f}s = {count / cycle:4.1f}fps  "
              f"art box={box}  "
              f"{'OK' if box[0] >= SAFE_SIDE and box[1] >= SAFE_TOP and box[2] <= CELL_W - SAFE_SIDE else 'VIOLATION'}")
    (OUT_FRAMES / "rig.json").write_text(json.dumps(rig_map, ensure_ascii=False, indent=2), encoding="utf-8")
    for state, lines in rig_map.items():
        eye = "-" if lines["eye"] is None else f"{lines['eye']:.3f}"
        chin = "-" if lines["chin"] is None else f"{lines['chin']:.3f}"
        print(f"  {state:14s} eye={eye} chin={chin}")
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
        files = sorted((OUT_FRAMES / state).glob("*.png"))
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
        paths = sorted((OUT_FRAMES / state).glob("*.png"))
        if len(paths) != count:
            raise RuntimeError(f"{state}: {len(paths)} frames written, {count} expected")
        for path in paths:
            image = Image.open(path)
            if image.size != (CELL_W, CELL_H):
                raise RuntimeError(f"{path} is {image.size}, expected {(CELL_W, CELL_H)}")
            box = image.getchannel("A").getbbox()
            if box is None:
                raise RuntimeError(f"empty frame {path}")
            left, top, right, bottom = box
            clear["left"] = min(clear["left"], left)
            clear["top"] = min(clear["top"], top)
            clear["right"] = min(clear["right"], CELL_W - right)
            clear["bottom"] = min(clear["bottom"], CELL_H - bottom)
            total += 1
    sheet = Image.open(OUT_SHEET)
    if sheet.size != (SHEET_W * 8, SHEET_H * 9):
        raise RuntimeError(f"sheet is {sheet.size}, must stay {SHEET_W * 8}x{SHEET_H * 9}")
    print(f"{total} frames at {CELL_W}x{CELL_H}, sheet {sheet.size}, tightest clearance {clear}")


if __name__ == "__main__":
    main()
