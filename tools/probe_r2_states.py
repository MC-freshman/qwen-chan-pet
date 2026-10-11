# -*- coding: utf-8 -*-
"""A1 judgement (R2): the two new reaction states are installed and reachable.

Headless: frame folders, config cycle entries, line-pool subkeys reachable
through the react() channel, and the wiring call-sites present in pet.pyw.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import needs  # noqa: E402
import speech  # noqa: E402

NEW_STATES = ("surprised", "sleepy")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    out = {"checks": {}}

    for state in NEW_STATES:
        frames = sorted((ROOT / "app" / "frames" / state).glob("*.png"))
        out["checks"][f"frames_{state}_20"] = len(frames) == 20

    cfg = json.loads((ROOT / "app" / "config.json").read_text(encoding="utf-8"))
    for state in NEW_STATES:
        out["checks"][f"cycle_seconds_{state}"] = state in cfg["cycle_seconds"]

    life = needs.Life(ROOT / "out" / "r2_probe_save.json")
    sp = speech.Speech(ROOT / "app" / "lines" / "zh.json", life,
                       rng=random.Random(11), subkey_gap_seconds=0)
    vars_ok = {"file": "a.py", "seen": "2", "hour": "9", "days": "3", "minutes": "5",
               "app": "Qoder", "energy": "60", "mood": "70", "affection": "80",
               "gap_min": "5", "gap_hour": "1"}
    for state in NEW_STATES:
        line = sp.pick("state", state, **vars_ok)
        out["checks"][f"state_lines_{state}"] = bool(line)

    src = (ROOT / "app" / "pet.pyw").read_text(encoding="utf-8")
    out["checks"]["wired_throw_surprised"] = 'react("surprised", "dizzy"' in src
    out["checks"]["wired_sleepy_states"] = '"sleepy" in self.extra_states' in src
    selftest_src = (ROOT / "app" / "selftest.py").read_text(encoding="utf-8")
    out["checks"]["selftest_triggered_updated"] = all(s in selftest_src for s in NEW_STATES)

    out["pass"] = all(out["checks"].values())
    (ROOT / "out" / "r2_states.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
