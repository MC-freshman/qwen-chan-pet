"""Raising-along state: needs decay over wall-clock time, plus what she remembers.

Pure local arithmetic and one JSON file. No network, no model, no token.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

MAX_OFFLINE_MINUTES = 12 * 60  # a night away should not wipe her out completely


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


DEFAULTS = {
    "mood": 72.0,
    "energy": 80.0,
    "affection": 40.0,
    "curiosity": 60.0,
}

# Per-minute drift while she is awake.
DECAY = {"mood": -0.09, "energy": -0.17, "affection": -0.02, "curiosity": -0.25}


class Life:
    """Needs + long-term memory of the主人, persisted in one JSON file."""

    def __init__(self, save_path: Path):
        self.path = Path(save_path)
        self.needs = dict(DEFAULTS)
        self.sleeping = False
        self.last_seen = time.time()
        self.first_met = int(time.time())
        self.stats = {"pets": 0, "feeds": 0, "drags": 0, "minutes_online": 0}
        self.hours = Counter()
        self.apps = Counter()
        self.files = Counter()
        self.line_history = []
        self.diary_day = ""
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for key in DEFAULTS:
            if isinstance(raw.get("needs", {}).get(key), (int, float)):
                self.needs[key] = _clamp(float(raw["needs"][key]))
        self.sleeping = bool(raw.get("sleeping", False))
        self.last_seen = float(raw.get("last_seen", time.time()))
        self.first_met = int(raw.get("first_met", self.first_met))
        self.stats.update(raw.get("stats", {}))
        # note_context keys by str(hour); a second dtype here means dict(self.hours)
        # serializes two entries for the same hour and the next load keeps only one.
        self.hours.update({str(k): v for k, v in (raw.get("hours") or {}).items()})
        self.apps.update(raw.get("apps") or {})
        self.files.update(raw.get("files") or {})
        self.line_history = list(raw.get("line_history") or [])
        self.diary_day = raw.get("diary_day", "")

    def offline_minutes(self) -> float:
        return max(0.0, min((time.time() - self.last_seen) / 60.0, MAX_OFFLINE_MINUTES))

    def apply_offline(self) -> float:
        """Catch the needs up with real time that passed while she was closed."""
        minutes = self.offline_minutes()
        if minutes > 1:
            self._drain(minutes, sleeping=self.sleeping)
        self.last_seen = time.time()
        return minutes

    def tick(self, minutes: float) -> None:
        if minutes <= 0:
            return
        self._drain(minutes, sleeping=self.sleeping)
        self.stats["minutes_online"] = self.stats.get("minutes_online", 0) + minutes
        self.last_seen = time.time()

    def _drain(self, minutes: float, sleeping: bool) -> None:
        for key, rate in DECAY.items():
            gain = minutes * (SLEEP_ENERGY_RATE if (sleeping and key == "energy") else rate)
            self.needs[key] = _clamp(self.needs[key] + gain)

    def bump(self, key: str, amount: float) -> float:
        before = self.needs[key]
        self.needs[key] = _clamp(before + amount)
        return self.needs[key] - before

    def note_context(self, title: str, file: str) -> None:
        now = datetime.now()
        self.hours[str(now.hour)] += 1
        app = title.split(" - ")[-1].strip() if title else ""
        if app:
            self.apps[app] += 1
        if file:
            self.files[file] += 1

    def busiest_hour(self) -> int | None:
        if not self.hours:
            return None
        return max(self.hours.items(), key=lambda kv: kv[1])[0]

    def top_file(self) -> str:
        return self.files.most_common(1)[0][0] if self.files else ""

    def top_app(self) -> str:
        return self.apps.most_common(1)[0][0] if self.apps else ""

    def days_known(self) -> int:
        return max(1, int((time.time() - self.first_met) // 86400) + 1)

    def remember_line(self, line_id: str, keep: int = 12) -> None:
        self.line_history.append(line_id)
        self.line_history = self.line_history[-keep:]

    def recent_lines(self) -> set[str]:
        return set(self.line_history[-8:])

    def save(self) -> None:
        payload = {
            "needs": {k: round(v, 2) for k, v in self.needs.items()},
            "sleeping": self.sleeping,
            "last_seen": self.last_seen,
            "first_met": self.first_met,
            "stats": self.stats,
            "hours": dict(self.hours),
            "apps": dict(self.apps.most_common(20)),
            "files": dict(self.files.most_common(20)),
            "line_history": self.line_history,
            "diary_day": self.diary_day,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


SLEEP_ENERGY_RATE = 0.85  # per minute while she naps


def write_diary(diary_dir: Path, life: Life, today: date) -> None:
    """One deterministic line per day, assembled from stats rather than generated."""
    diary_dir.mkdir(parents=True, exist_ok=True)
    peak = life.busiest_hour()
    lines = [
        f"# {today.isoformat()}",
        "",
        f"- 累计一起在线 {round(life.stats.get('minutes_online', 0))} 分钟",
        f"- 累计摸头 {life.stats.get('pets', 0)} 次，喂食 {life.stats.get('feeds', 0)} 次",
        f"- 心情 {life.needs['mood']:.0f} / 精力 {life.needs['energy']:.0f} / 亲密 {life.needs['affection']:.0f}",
    ]
    if peak is not None:
        lines.append(f"- 你最活跃的钟点是 {int(peak)} 点")
    if life.top_file():
        lines.append(f"- 你最近最常碰的文件是 {life.top_file()}")
    path = diary_dir / f"{today.isoformat()}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
