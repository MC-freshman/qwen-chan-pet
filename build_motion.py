"""Dense, layered animation frames for the standalone pet.

Emits app/frames/<state>/*.png at S x the design cell, at full frame rate, and
free of anything that only made sense inside a fixed sprite sheet. Secondary
motion, breathing and blinking are applied on top of the authored choreography in
qwen_poses. Playback timing comes from config.json so the pet and this script never
disagree about how long a loop lasts.

    python build_motion.py                  # 全部 12 个态
    python build_motion.py shy idle         # 只重建这几个态
    python build_motion.py --check          # 只量成品帧的安全框，一个字节都不写
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

import qwen_poses as base  # noqa: E402  (the pose/safe-area pipeline)
import rigor  # noqa: E402

# Rendering runs at a multiple of the design cell because the source poses are
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
CALM = {"idle", "waiting", "review", "failed", "sleepy"}
HEAD_SECTOR = (-140.0, -40.0)   # image y grows down, so "up" is -90
SKIRT_SECTOR = (40.0, 140.0)
HIP_FRACTION = 0.66  # sway pivot, measured down the sprite
NECK_FRACTION = 0.30  # rows above this stay rigid, so the hat never smears
BLINK_WINDOW = 0.09

CELL_W, CELL_H = base.FRAME_W * S, base.FRAME_H * S
SAFE_SIDE = base.SAFE_SIDE * S
SAFE_TOP = base.SAFE_TOP * S
BASELINE = base.BASELINE * S
FOOT_MARGIN = base.FOOT_MARGIN * S
PAD = base.PAD * S
FOOT = 6 * S          # tilt pivot, measured up from the sprite's feet
SPREAD_MIN = 12 * S   # smallest credible eye separation for face_lines
GAP = 6 * S           # dark-pixel gap that counts as two separate clusters
BLINK_LIP = 6 * S     # how far the blink band reaches above the eye line
BLINK_CHIN = 8 * S

FIT = {state: (height * S, bias * S) for state, (height, bias) in base.FIT.items()}
MOTION = {
    state: [(dx * S, dy * S, tilt, squash) for dx, dy, tilt, squash in keys]
    for state, keys in base.MOTION.items()
}

# 三个反应专用态：只在被摸到/被甩出去的那一刻出场，各自一套编排与帧数。
# 宠物端按目录发现它们，所以这几个态没出帧也不会崩，只会退回最近的烘焙态。
EXTRA_MOTION = {
    "shy": [
        (0, 0, 0.0, 0.00), (-1, -1, -2.0, 0.01), (-2, -2, -3.0, 0.015), (-1, -1, -1.5, 0.005),
        (0, 0, 0.0, 0.00), (1, -1, 1.5, 0.005), (2, -2, 3.0, 0.015), (1, -1, 2.0, 0.01),
    ],
    "annoyed": [
        (0, 0, -1.5, 0.00), (0, 2, -2.5, -0.02), (1, 3, -3.5, -0.025), (1, 1, -2.5, -0.01),
        (0, 0, -1.5, 0.00), (0, 2, -2.0, -0.015), (-1, 3, -3.0, -0.02), (-1, 1, -2.0, -0.005),
    ],
    "dizzy": [
        (0, 0, 0.0, 0.00), (3, 1, 5.0, -0.01), (5, 2, 8.0, -0.02), (3, 1, 5.0, -0.01),
        (0, 0, 0.0, 0.00), (-3, 1, -5.0, -0.01), (-5, 2, -8.0, -0.02), (-3, 1, -5.0, -0.01),
    ],
    # 被甩出去那一瞬：先一缩，再向后上方弹开，左右各抖一下（起飞惊、落地晕，语义分开）
    "surprised": [
        (0, 0, 0.0, 0.02), (-1, -3, -2.0, -0.03), (-2, -5, -3.0, -0.04), (-1, -3, -2.0, -0.03),
        (0, 0, 0.0, 0.02), (1, -2, 2.0, -0.02), (2, -4, 3.0, -0.03), (1, -2, 2.0, -0.02),
    ],
    # 打盹：极慢的点头 sway，配合 CALM 生命层呼吸
    "sleepy": [
        (0, 0, 0.0, 0.00), (0, 1, 1.5, 0.01), (1, 2, 2.5, 0.02), (1, 3, 3.0, 0.025),
        (0, 2, 2.0, 0.015), (0, 0, 0.0, 0.00), (-1, 1, -1.5, 0.01), (-1, 2, -2.5, 0.015),
    ],
}
EXTRA_FIT = {"shy": (172, 0), "annoyed": (170, 0), "dizzy": (172, 0),
             "surprised": (170, 0), "sleepy": (170, 0)}
EXTRA_FRAMES = {"shy": 20, "annoyed": 20, "dizzy": 20, "surprised": 20, "sleepy": 20}

FIT.update({state: (height * S, bias * S) for state, (height, bias) in EXTRA_FIT.items()})
MOTION.update({
    state: [(dx * S, dy * S, tilt, squash) for dx, dy, tilt, squash in keys]
    for state, keys in EXTRA_MOTION.items()
})
FRAMES.update(EXTRA_FRAMES)
POSES = {**base.POSES, **{state: f"qwen-chibi-{state}" for state in EXTRA_MOTION}}

OUT_FRAMES = ROOT / "app" / "frames"
CONFIG = ROOT / "app" / "config.json"

# A run cycle needs more than one bounce: with a single pose the pet reads as a
# picture hopping along the desk. Two stride frames alternate every STRIDE frames.
POSE_SETS = {
    "running-right": ("qwen-chibi-run-a", "qwen-chibi-run-b"),
    "running-left": ("qwen-chibi-run-a", "qwen-chibi-run-b"),
    "running": ("qwen-chibi-run-a", "qwen-chibi-run-b"),
}
STRIDE = 4

# 镜像态不靠"把带方向的量取反"去凑：rigor.polar_twist 的扇形 feather 只在起始边斜坡，
# 实测振幅取反后仍有 1.6% 的像素不互为镜像。所以形参整套沿用正向态，最后把成品帧整幅翻。
MIRROR_SOURCE = {"running-left": "running-right"}
for _state, _source in MIRROR_SOURCE.items():
    FIT[_state] = FIT[_source]
    MOTION[_state] = MOTION[_source]

_palette_reference: Image.Image | None = None


def stride_frame(state: str, index: int) -> int:
    return (index // STRIDE) % 2 if state in POSE_SETS else 0


def palette_reference() -> Image.Image:
    """The idle pose: every other pose is pulled onto its white balance if it drifted."""
    global _palette_reference
    if _palette_reference is None:
        _palette_reference = base.trim(base.cutout(base.find_source(POSES["idle"])))
    return _palette_reference


def load_sprites(state: str) -> list[Image.Image]:
    names = POSE_SETS.get(state) or [POSES[state]]
    sprites = []
    for name in names:
        sprite = base.trim(base.cutout(base.find_source(name)))
        sprite = base.match_palette(sprite, palette_reference())
        # 镜像态在这里不翻：成品帧写盘前整幅翻，见 main()
        sprites.append(sprite)
    return sprites


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
    这里过去先把左上角 88x152 抹掉再找眼睛——那是给表里的挂饰留的位子，可成品帧根本不画
    挂饰，于是镜像态上这块盖住的是她自己的头发，检不出眼睛就悄悄不眨眼。
    实测 12 个态摘掉这块遮罩后检出值一字不变（含 running-left 的 205/231）。
    """
    arr = np.array(content.convert("RGB")).astype(int)
    alpha = np.array(content.getchannel("A"))
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


def place(content: Image.Image, dx: float, dy: float, state: str) -> Image.Image:
    frame = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    cw, ch = content.size
    x = round((CELL_W - cw) / 2 + dx + FIT[state][1])
    y = round(CELL_H - BASELINE - ch + dy)
    x = max(SAFE_SIDE, min(CELL_W - cw - SAFE_SIDE, x))
    y = max(SAFE_TOP, min(CELL_H - ch - FOOT_MARGIN, y))
    frame.alpha_composite(content, (x, y))
    return frame


def art_span(content: Image.Image) -> tuple[int, int]:
    box = content.getchannel("A").getbbox() or (0, 0, 1, 1)
    return box[1], box[3]


def render_state(state: str, count: int, sprites: list, height: int, cycle: float,
                 baked_life: bool = True):
    scaled = [base.fit(sprite, height, max_width=CELL_W - 6 * S) for sprite in sprites]
    springs = spring_series(state, count, cycle)
    return scaled, [
        animate(state, index, count, scaled[stride_frame(state, index)], springs, cycle,
                baked_life=baked_life)
        for index in range(count)
    ]


def art_box(frame: Image.Image) -> tuple[int, int, int, int]:
    """她的剪影占的那块框。过去这里要先抹掉左上角给挂饰留位子，现在成品帧不画挂饰。"""
    alpha = np.array(frame.getchannel("A"))
    ys, xs = np.nonzero(alpha)
    if len(ys) == 0:
        return (0, 0, 0, 0)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def fits(box) -> bool:
    """成品剪影有没有留在自己的安全框里：左右 SAFE_SIDE、上 SAFE_TOP、下留 FOOT_MARGIN。"""
    return (box[0] >= SAFE_SIDE and box[1] >= SAFE_TOP
            and box[2] <= CELL_W - SAFE_SIDE and box[3] <= CELL_H - FOOT_MARGIN)


def fit_state(state: str, count: int, sprites: list, cycle: float):
    """Shrink until the *finished* frames fit the safe box.

    The previous estimate looked only at the pre-deformation sprite, so the pendulum,
    joint twist and blink could still push the silhouette past the cell edge - that is
    why the raised fan kept getting cut while jumping. Measured with the baked life
    layer on, since that is the largest the silhouette ever gets.
    """
    height = FIT[state][0]
    scaled, frames = render_state(state, count, sprites, height, cycle, baked_life=True)
    box = (0, 0, 0, 0)
    for _ in range(5):
        boxes = [art_box(frame) for frame in frames]
        left = min(b[0] for b in boxes)
        top = min(b[1] for b in boxes)
        right = max(b[2] for b in boxes)
        bottom = max(b[3] for b in boxes)
        box = (left, top, right, bottom)
        need = max(SAFE_SIDE - left, right - (CELL_W - SAFE_SIDE), SAFE_TOP - top,
                   bottom - (CELL_H - FOOT_MARGIN))   # 底边也算：脚被切就是这里漏的
        if need <= 0:
            break
        span = max(1.0, bottom - top)
        height = max(110 * S, int(height * max(0.80, 1.0 - need / span) * 0.97))
        scaled, frames = render_state(state, count, sprites, height, cycle, baked_life=True)
    return scaled, frames, box


def animate(
    state: str, index: int, count: int, sprite: Image.Image, springs: tuple,
    cycle: float, baked_life: bool = True,
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
    # 安静态的呼吸与眨眼由运行时 rigor.LifeLayer 按墙钟算，不烘进帧里——预烘的循环再密
    # 也有周期可被认出来。baked_life=True 只用在 fit_state 量安全框那一次：那是她轮廓
    # 最大的时刻，按它来缩才不会真被切到。
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
    return place(content, dx, dy, state)


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


def _noise_components(path: Path) -> int:
    """R2 闸门：成品帧上孤立不透明小连通域的数量。

    两个来源都会长成这样：AI 背景彩噪（cutout 治不到的），和弹簧数值爆炸后
    polar_twist 把采样坐标搅乱产生的雪花（sleepy 初版 dt=0.225 炸过一次，
    981 个噪点连通域）。干净帧实测 ≤2 个、≤2 像素；爆炸帧是几百个。
    帧级阈值 20：dizzy 的"晕头星星"是故意画的 detached 粒子（实测最多 15 个/帧），
    20 对两边都留足余量。"""
    from scipy import ndimage

    solid = np.array(Image.open(path).getchannel("A")) >= 128
    lab, n = ndimage.label(solid)
    if n <= 1:
        return 0
    sizes = ndimage.sum(solid, lab, range(1, n + 1))
    return int((sizes < 3000).sum())


def measure_shipped() -> int:
    """只测量、一个字节都不写：把 app/frames 里现有成品帧对着安全框读一遍。

    过去"验一次安全框"等于"删写 141 张 PNG"，所以没人愿意随手验。
    """
    worst = {"left": 999, "top": 999, "right": 999, "bottom": 999}
    bad: list[str] = []
    total = 0
    for state, count in FRAMES.items():
        paths = sorted((OUT_FRAMES / state).glob("*.png"))
        if len(paths) != count:
            bad.append("%s: 盘上 %d 帧，合同应有 %d 帧" % (state, len(paths), count))
        for path in paths:
            box = Image.open(path).getchannel("A").getbbox()
            if box is None:
                bad.append("空帧 " + str(path))
                continue
            total += 1
            noise = _noise_components(path)
            if noise > 20:
                bad.append("%s/%s 噪点连通域 %d（>20）" % (state, path.name, noise))
            worst["left"] = min(worst["left"], box[0])
            worst["top"] = min(worst["top"], box[1])
            worst["right"] = min(worst["right"], CELL_W - box[2])
            worst["bottom"] = min(worst["bottom"], CELL_H - box[3])
            if not fits(box):
                bad.append("%s/%s 越出安全框 box=%s" % (state, path.name, box))
    print("%d 帧已量，最紧边距 %s（要求 左右≥%d、上≥%d、下≥%d）"
          % (total, worst, SAFE_SIDE, SAFE_TOP, FOOT_MARGIN))
    for line in bad[:20]:
        print("  问题：", line)
    print("  共 %d 处" % len(bad) if bad else "  全部合格")
    return 1 if bad else 0


def main() -> None:
    cycles = cycle_seconds()
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    unknown_flags = flags - {"--check"}
    if unknown_flags:
        raise SystemExit(f"不认识这些开关：{sorted(unknown_flags)}；可用：--check")
    only = set(sys.argv[1:]) - flags
    if "--check" in flags:
        raise SystemExit(measure_shipped())
    unknown = only - set(FRAMES)
    if unknown:
        raise SystemExit(f"没有这些状态：{sorted(unknown)}；可选：{sorted(FRAMES)}")
    rebuilt: list[str] = []
    bad: list[str] = []
    rig_file = OUT_FRAMES / "rig.json"
    rig_map = json.loads(rig_file.read_text(encoding="utf-8")) if (only and rig_file.exists()) else {}
    for state in FRAMES:
        if only and state not in only:
            continue
        count = FRAMES[state]
        cycle = cycles[state]
        sprites = load_sprites(state)
        scaled, _probe, box = fit_state(state, count, sprites, cycle)
        springs = spring_series(state, count, cycle)
        folder = OUT_FRAMES / state
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.png"):
            old.unlink()
        mirrored = MIRROR_SOURCE.get(state)
        for index in range(count):
            frame = animate(state, index, count, scaled[stride_frame(state, index)], springs,
                            cycle, baked_life=False)
            image = base.clear_hidden_rgb(frame)
            (image.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirrored else image).save(
                folder / f"{index:02d}.png")
        if mirrored and mirrored in rig_map:
            rig_map[state] = dict(rig_map[mirrored])   # 剪影是严格镜像的，地标行照抄，不必再检一遍
        else:
            first = Image.open(sorted(folder.glob("*.png"))[0]).convert("RGBA")
            lines = face_lines(first)
            rig_map[state] = {
                "eye": None if lines["eye"] is None else lines["eye"] / CELL_H,
                "chin": None if lines["chin"] is None else lines["chin"] / CELL_H,
            }
        print(f"{state:14s} {count:2d} frames / {cycle:.2f}s = {count / cycle:4.1f}fps  "
              f"art box={box}  {'OK' if fits(box) else 'VIOLATION'}")
        rebuilt.append(state)
        if not fits(box):
            bad.append(state)
    (OUT_FRAMES / "rig.json").write_text(json.dumps(rig_map, ensure_ascii=False, indent=2), encoding="utf-8")
    for state, lines in rig_map.items():
        eye = "-" if lines["eye"] is None else f"{lines['eye']:.3f}"
        chin = "-" if lines["chin"] is None else f"{lines['chin']:.3f}"
        print(f"  {state:14s} eye={eye} chin={chin}")
    verify(rebuilt)   # 写了哪些态就查哪些：部分重建过去直接跳过这一步
    if bad:
        raise SystemExit(f"这些状态的剪影越出安全框，帧已写盘但得复缩：{bad}")
    if only:
        print("部分重建：预览图未改动")
        return
    contact(ROOT / "docs" / "preview.png")
    print(f"preview -> {ROOT / 'docs' / 'preview.png'}")


def contact(target: Path, columns: int = 8) -> None:
    """README 用的那张：12 个态各一行，每行按列数均匀取样后缩回三分之二格。

    全帧率的原图一张 384x416，232 张拼起来既没人看也没法进仓库；缩到 128x139 一格
    刚好还能看清礼帽和扇面，整张 1.2MB 量级。
    """
    cell = (base.FRAME_W * 2 // 3, base.FRAME_H * 2 // 3)
    rows = []
    for state, count in FRAMES.items():
        paths = sorted((OUT_FRAMES / state).glob("*.png"))
        picks = [round(k * (len(paths) - 1) / (columns - 1)) for k in range(columns)] \
            if len(paths) > 1 else [0]
        strip = Image.new("RGBA", (cell[0] * columns, cell[1]), (250, 250, 252, 255))
        for col, index in enumerate(picks):
            frame = Image.open(paths[index]).convert("RGBA").resize(cell, Image.Resampling.LANCZOS)
            strip.alpha_composite(frame, (col * cell[0], 0))
        rows.append((state, strip))
    canvas = Image.new("RGB", (cell[0] * columns, cell[1] * len(rows)), (250, 250, 252))
    y = 0
    for _state, strip in rows:
        canvas.paste(strip.convert("RGB"), (0, y))
        y += strip.height
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, optimize=True)


def verify(states: list[str]) -> None:
    """质检要跟着每一次重建跑，而且四边都查：单态重建过去直接跳过这一步。"""
    checked = states
    clear = {"left": 999, "right": 999, "top": 999, "bottom": 999}
    violations: list[str] = []
    total = 0
    for state in checked:
        count = FRAMES[state]
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
            noise = _noise_components(path)
            if noise > 20:
                violations.append(f"{path.name} of {state}: 噪点连通域 {noise}（>20）")
            if not fits(box):
                violations.append(f"{path.name} of {state}: box={box}")
            clear["left"] = min(clear["left"], left)
            clear["top"] = min(clear["top"], top)
            clear["right"] = min(clear["right"], CELL_W - right)
            clear["bottom"] = min(clear["bottom"], CELL_H - bottom)
            total += 1
    if violations:
        raise RuntimeError(f"{len(violations)} 帧越出安全框，最早几例：{violations[:5]}")
    print(f"{total} frames at {CELL_W}x{CELL_H}, tightest clearance {clear}")


if __name__ == "__main__":
    main()
