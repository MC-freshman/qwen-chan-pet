"""Q0 judgement: the brain, tested without a window.

Headless gate for everything that does not need the Tk canvas: the line pool,
the picker's no-repeat contract, needs decay, the offline cap, save round-trip
and the diary writer. Rate limiting and input handling live inside the Tk Pet
and are covered by interaction checks, not here.
"""

from __future__ import annotations

import json
import random
import string
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import needs  # noqa: E402
import speech  # noqa: E402
from needs import settle, write_diary  # noqa: E402

# line_vars() 供给的全部变量（pet.pyw:808-822），台词占位符不得超出这个集合
VARS = {"file", "seen", "hour", "days", "minutes", "app", "energy", "mood",
        "affection", "gap_min", "gap_hour"}

# pet.pyw 今天真能触发的分类/子键。state/running-left|right 不单列——
# context_line 用 state.split("-")[0] 查表，左右跑折叠进 state/running。
# state 的 shy/annoyed/dizzy 反应态只持续 0.9-1.6s、短于发言间隔，
# 实际够不着——如实登记为准死角，不算绿。
TRIGGERED = {
    "greet": {"morning", "afternoon", "evening", "late_night", "back_short", "back_long", "first_meet"},
    "state": {"idle", "running", "waving", "jumping", "failed", "waiting", "review",
              "shy", "annoyed", "dizzy", "surprised", "sleepy"},
    "touch": {"pet", "hat", "face", "hair", "skirt", "body", "feed", "drag", "thrown",
              "landed", "tickle", "annoyed", "reject", "watched"},
    "needs": {"low_energy", "low_mood", "low_affection", "high_affection"},
    "sense": {"user_idle", "long_work", "night_owl", "coding", "qoder"},
    "self": {"memory", "aware", "identity"},
    "qoder_busy": {"default"},
    "qoder_done": {"default"},
    "boss": {"default"},
}
# 反应态（shy/annoyed/dizzy）已由独立通道触发（Q2），不再算准死角

MEMORY_WINDOW = 8  # needs.recent_lines 的记忆窗


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out = {"checks": {}}
    tree = json.loads((ROOT / "app" / "lines" / "zh.json").read_text(encoding="utf-8"))

    # ---- A: 每句台词的占位符都是 line_vars() 真供得上的 ----
    fmt = string.Formatter()
    bad = {}
    for cat, subs in tree.items():
        for sub, lines in subs.items():
            for i, text in enumerate(lines):
                missing = {name for _, name, _, _ in fmt.parse(text) if name} - VARS
                if missing:
                    bad[f"{cat}/{sub}/{i}"] = sorted(missing)
    out["unknown_placeholders"] = bad
    out["checks"]["no_unsatisfiable_lines"] = not bad

    # ---- B: 触发面要求的每个子键都存在且非空 ----
    missing = {}
    for cat, subs in TRIGGERED.items():
        for sub in sorted(subs):
            if not tree.get(cat, {}).get(sub):
                missing[f"{cat}/{sub}"] = len(tree.get(cat, {}).get(sub) or [])
    out["missing_subkeys"] = missing
    out["lines_per_category"] = {k: sum(len(v) for v in subs.values()) for k, subs in tree.items()}
    out["total_lines"] = out["lines_per_category"] and sum(out["lines_per_category"].values())
    out["checks"]["categories_present"] = not missing
    out["checks"]["at_least_150_lines"] = out["total_lines"] >= 150

    # 自检档不跨运行：历史/冷却残留会把 C 项的池子全挡住
    for stale in ("selftest_save.json", "selftest_save2.json", "selftest_save3.json"):
        stale_path = ROOT / "out" / stale
        if stale_path.exists():
            stale_path.unlink()
    life = needs.Life(ROOT / "out" / "selftest_save.json")
    sp = speech.Speech(ROOT / "app" / "lines" / "zh.json", life, rng=random.Random(4))

    # ---- C: 记忆窗内不重复 —— 池子里还有没说过的话时，选词必须给新的 ----
    # 本项专测去重机制本身，用关掉子键冷却的实例（冷却另有语义，见 H 项）
    sp_dedup = speech.Speech(ROOT / "app" / "lines" / "zh.json", life, rng=random.Random(4),
                             subkey_gap_seconds=0)
    dupes = {}
    for cat, subs in tree.items():
        for sub, lines in subs.items():
            got = [sp_dedup.pick(cat, sub, **{k: "1" for k in VARS}) for _ in range(len(lines) + 3)]
            got = [g for g in got if g]
            n = min(len(lines), MEMORY_WINDOW)
            dupes[f"{cat}/{sub}"] = n - len(set(got[:n]))
    out["repeat_within_pool"] = {k: v for k, v in dupes.items() if v}
    out["checks"]["no_repeat_within_pool"] = not any(dupes.values())

    # ---- D: 衰减是"每分钟"的真实速率，不是快了 60 倍 ----
    life2 = needs.Life(ROOT / "out" / "selftest_save2.json")
    life2.sleeping = False
    before = life2.needs["energy"]
    life2.tick(1.0)  # 恰好一分钟
    drift = before - life2.needs["energy"]
    out["energy_drift_per_minute"] = round(drift, 4)
    out["checks"]["decay_is_per_minute"] = 0.05 < drift < 0.6

    # ---- E: 离线结算上限只有 settle() 这一处（12 小时） ----
    _, used = settle(24 * 60, False)
    out["offline_capped_minutes"] = used
    out["checks"]["offline_capped_at_12h"] = used == needs.MAX_OFFLINE_MINUTES

    # ---- F: 存档往返（原子写路径） ----
    life2.needs["mood"] = 55.5
    life2.save()
    again = needs.Life(ROOT / "out" / "selftest_save2.json")
    out["checks"]["save_roundtrip"] = abs(again.needs["mood"] - 55.5) < 0.01

    # ---- G: 日记是确定性的统计拼装，非空且字段齐全 ----
    with tempfile.TemporaryDirectory() as td:
        # 种上一天的真实密度，可选字段（活跃钟点/常碰文件）才有得写
        life2.hours["14"] = 40
        life2.files["main.py"] = 12
        life2.stats["minutes_online"] = 180
        life2.stats["pets"] = 7
        write_diary(Path(td), life2, date.today())
        files = list(Path(td).glob("*.md"))
        text = files[0].read_text(encoding="utf-8") if files else ""
        body = [ln for ln in text.splitlines() if ln.strip()]
        out["checks"]["diary_written_nonempty"] = len(files) == 1 and len(body) >= 6

    # ---- H: 48h 窗口重复率（Q2）——模拟 7 天环境类发言，同线 48h 内不再出现 ----
    import random as _rd
    sim_rng = _rd.Random(20260926)
    life3 = needs.Life(ROOT / "out" / "selftest_save3.json")
    sp3 = speech.Speech(ROOT / "app" / "lines" / "zh.json", life3, rng=_rd.Random(7),
                        subkey_gap_seconds=4 * 3600)
    buckets = [("state", s) for s in ("idle", "running", "review", "waiting", "failed",
                                      "waving", "jumping")]         + [("self", s) for s in ("memory", "aware", "identity")]         + [("sense", s) for s in ("coding", "user_idle", "long_work", "night_owl", "qoder")]         + [("greet", s) for s in ("morning", "afternoon", "evening", "late_night",
                                  "back_short", "back_long", "first_meet")]         + [("needs", s) for s in ("low_energy", "low_mood", "low_affection", "high_affection")]
    spoken: list[tuple[float, str]] = []
    t = 0.0
    slots = 7 * 24 * 6          # 7 天，每 10 分钟一个发言机会（≈频控上限的一半）
    for _ in range(slots):
        # context_line 的回退链：首选被冷却挡住就再试两条，都堵上才闭嘴
        for _attempt in range(3):
            cat, sub = buckets[sim_rng.randrange(len(buckets))]
            text = sp3.pick(cat, sub, **{k: "1" for k in VARS})
            if text:
                spoken.append((t, f"{cat}/{sub}"))
                break
        t += 600.0
    repeats = 0
    for i, (ti, lid) in enumerate(spoken):
        for tj, ljd in spoken[:i]:
            if ljd == lid and ti - tj < 48 * 3600:
                repeats += 1
                break
    rate = repeats / max(1, len(spoken))
    out["sim_slots"] = len(spoken)
    out["sim_repeat_rate_48h"] = round(rate, 4)
    out["checks"]["repeat_within_48h_le_15pct"] = rate <= 0.15

    out["pass"] = all(out["checks"].values())
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "selftest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["checks"], ensure_ascii=False, indent=1))
    print("total_lines", out["total_lines"], "| pass", out["pass"])
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
