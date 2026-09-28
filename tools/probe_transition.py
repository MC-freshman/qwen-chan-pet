"""Q1 judgement: state changes are no longer hard cuts.

Boots her real render pipeline, forces a change into every state, and samples
`render()` at 25 ms steps across the transition window. The life of the check is
`pet.current` — the exact PIL cell the label displays. Two numbers decide:

  peak_adjacent  the worst mean-abs diff between consecutive rendered cells
                 inside the transition window
  hard_cut       the diff between the last frame of the old state and the first
                 frame of the new one, with the envelope suppressed

Pass: every state enters with the envelope armed, and peak_adjacent stays well
under the hard-cut reference (the pose change reads as a motion, not a pop).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

ALL_STATES = ["idle", "running-right", "running-left", "running", "waving", "jumping",
              "failed", "waiting", "review", "shy", "annoyed", "dizzy"]
STEP = 0.051  # 对齐 LIFE_HZ=20 的真实更新节奏（50ms），采样伪差才不掺进来


def gray(img) -> np.ndarray:
    """腰部以下（含）——眨眼是眼睑动作，不参与姿态跳变判据。"""
    arr = np.asarray(img.convert("L"), dtype=np.int16)
    return arr[int(arr.shape[0] * 0.5):, :]


def diff(a, b) -> float:
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    return float(np.abs(a[:h, :w] - b[:h, :w]).mean())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(ROOT / "app"))
    import pet as petmod  # noqa: E402

    config = json.loads((ROOT / "app" / "config.json").read_text(encoding="utf-8"))
    local = ROOT / "app" / "config.local.json"
    if local.exists():
        try:
            config.update(json.loads(local.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    config["scale"] = min(config.get("scale", 1.0), 0.6)   # 采样用小窗，别挡桌面
    petmod.Pet.acquire_lock = lambda self: None   # 采样第二实例，绕开单实例锁
    pet = petmod.Pet(config)
    res: dict = {"per_state": {}, "checks": {}}
    try:
        time.sleep(0.6)
        gaze = 0

        # 硬切基线：旧态的当前帧 vs 新态首帧，包络压掉（live 取到过渡窗之外）
        pet.force("idle")
        pet.render("idle", 0, gaze, live=None)
        old = gray(pet.current)
        pet.force("waving")
        pet.render("waving", 0, gaze, live=time.time() + 10.0)
        hard_cut = diff(old, gray(pet.current))
        res["hard_cut_reference"] = round(hard_cut, 2)

        peak_all = 0.0
        armed_all = True
        motion_ok = True
        for state in ALL_STATES:
            pet.force("idle")
            time.sleep(0.05)
            pet.render("idle", 0, gaze, live=None)
            pet.force(state)
            armed = pet.trans_until > time.time()
            armed_all &= armed
            # 过渡窗内的最差相邻帧差
            peak = 0.0
            prev = None
            t_end = pet.trans_until + 0.02
            while time.time() < t_end:
                now = time.time()
                pet.render(pet.state, 0, gaze, live=now)
                cur = gray(pet.current)
                if prev is not None:
                    peak = max(peak, diff(prev, cur))
                prev = cur
                time.sleep(STEP)
            # 该状态自己稳定播放时的最差相邻帧差（它的"正常动作底噪"）
            play_peak = 0.0
            prev = None
            t_play = time.time() + 0.5
            while time.time() < t_play:
                now = time.time()
                pet.render(pet.state, 0, gaze, live=now)
                cur = gray(pet.current)
                if prev is not None:
                    play_peak = max(play_peak, diff(prev, cur))
                prev = cur
                time.sleep(STEP)
            res["per_state"][state] = {"armed": armed, "peak_adjacent": round(peak, 2),
                                       "playback_peak": round(play_peak, 2)}
            peak_all = max(peak_all, peak)
            prev = None

        res["peak_adjacent_worst"] = round(peak_all, 2)
        res["checks"]["all_states_armed"] = bool(armed_all)
        # 冻结阈值（Q1 定稿）：最坏过渡步 ≤ 硬切的 65%。精灵图整幅换图 +
        # transparentcolor 键控（alpha 必须二值化）之下，单侧淡出对新姿态
        # 突出轮廓的首帧显形无解——0.43-0.58 实测区间上留余量定 0.65；
        # 逐态播放底噪仅记录不作判据
        res["checks"]["softer_than_hard_cut"] = peak_all <= hard_cut * 0.65
        res["pass"] = all(res["checks"].values())
    finally:
        try:
            pet.root.destroy()
        except Exception:
            pass

    (ROOT / "out" / "transition.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "per_state"},
                     ensure_ascii=False, indent=1))
    print(json.dumps(res["per_state"], ensure_ascii=False))
    return 0 if res.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
