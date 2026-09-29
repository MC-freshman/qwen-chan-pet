"""Q5 judgement: micro-actions fire on cadence and read visually; weekly digest math.

Three parts, all offline except part 2 (needs her render pipeline):
  A. 30 min of virtual time through LifeLayer: 东张西望 and 伸懒腰 each fire
     at least once per 10 minutes on average.
  B. A stretch at its peak renders measurably different from the resting pose.
  C. write_weekly's increments equal current-cumulative minus snapshot (差值法),
     first run without a snapshot only plants the snapshot.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


def gray_lower(img) -> np.ndarray:
    arr = np.asarray(img.convert("L"), dtype=np.int16)
    return arr[int(arr.shape[0] * 0.5):, :]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import rigor
    import needs
    from needs import write_weekly

    res: dict = {"checks": {}, "evidence": {}}

    # ---- A: 虚拟 30 分钟，微动作节奏 ----
    layer = rigor.LifeLayer()
    layer.set_landmarks(60, 120)      # head_follow_profile 需要 chin 锚点
    t0 = time.time()
    glitches, stretches = 0, 0
    last_glance_until, last_stretch_from = 0.0, 0.0
    now = t0
    while now - t0 < 1800.0:
        now += 0.05
        layer.offsets(208, now)       # 驱动 glance/turn 的调度
        layer.stretch(now)
        if layer.glance_until != last_glance_until:
            last_glance_until = layer.glance_until
            glitches += 1             # 一次三连扫视 = 一次
        if layer.stretch_from != last_stretch_from:
            last_stretch_from = layer.stretch_from
            stretches += 1
    res["evidence"]["glances_in_30min"] = glitches
    res["evidence"]["stretches_in_30min"] = stretches
    res["checks"]["glance_ge_1_per_10min"] = glitches >= 3
    res["checks"]["stretch_ge_1_per_10min"] = stretches >= 3

    # ---- C: 周记差值法（先做，不依赖 Tk）----
    tmp = ROOT / "out" / "q5_diary"
    shutil.rmtree(tmp, ignore_errors=True)
    life = needs.Life(ROOT / "out" / "q5_save.json")
    if (ROOT / "out" / "q5_save.json").exists():
        (ROOT / "out" / "q5_save.json").unlink()
        life = needs.Life(ROOT / "out" / "q5_save.json")
    life.stats["minutes_online"] = 600
    life.stats["pets"] = 40
    life.stats["feeds"] = 12
    first = write_weekly(tmp, life, date.today())
    res["checks"]["weekly_first_plants_snapshot"] = first is None and bool(life.weekly_snapshot)
    life.stats["minutes_online"] = 600 + 320
    life.stats["pets"] = 40 + 9
    life.stats["feeds"] = 12 + 3
    life.hours["21"] = 50
    path = write_weekly(tmp, life, date.today())
    text = path.read_text(encoding="utf-8") if path else ""
    res["evidence"]["weekly_text"] = text
    res["checks"]["weekly_file_written"] = path is not None and path.exists()
    res["checks"]["weekly_delta_correct"] = (
        "本周一起在线 320 分钟" in text and "本周摸头 9 次" in text and "喂食 3 次" in text)

    # ---- B: 拉伸帧可区分（需要她的渲染管线）----
    try:
        import pet as petmod
        petmod.Pet.acquire_lock = lambda self: None   # 采样用第二实例，绕开单实例锁
        config = json.loads((ROOT / "app" / "config.json").read_text(encoding="utf-8"))
        config["scale"] = min(config.get("scale", 1.0), 0.6)
        pet = petmod.Pet(config)
        time.sleep(0.6)
        gaze = 0
        pet.force("idle")
        live = time.time()
        # 关掉拉伸，画一帧
        layer = pet.layer
        layer.stretch_until = live - 1.0
        pet.render("idle", 0, gaze, live=live)
        rest = gray_lower(pet.current)
        # 手动把拉伸放进峰值窗口，再画一帧
        layer.stretch_from = live - 0.9
        layer.stretch_until = live + 1.2
        pet.render("idle", 0, gaze, live=live + 0.06)   # 跨过 LIFE_HZ 去重桶
        stretched = gray_lower(pet.current)
        d = float(np.abs(stretched - rest).mean())
        res["evidence"]["stretch_frame_diff"] = round(d, 3)
        res["checks"]["stretch_visually_distinct"] = d > 1.0
        try:
            pet.root.destroy()
        except Exception:
            pass
    except Exception as e:
        res["evidence"]["render_error"] = str(e)
        res["checks"]["stretch_visually_distinct"] = False

    res["pass"] = all(res["checks"].values())
    (ROOT / "out" / "q5.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
