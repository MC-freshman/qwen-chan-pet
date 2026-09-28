"""Raising-along state: needs decay over wall-clock time, plus what she remembers.

Pure local arithmetic and one JSON file. No network, no model, no token.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import date, datetime, timedelta
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

SLEEP_ENERGY_RATE = 0.85  # per minute while she naps

NAP_ENERGY = 12.0  # 精力低于这条线又没人理，她自己睡下去
NAP_WAKE = 60.0    # 歇到这条线且人已回来，她自己醒

SCHEMA = 1  # save.json 的形状版本；改数值结构时在这里加分支，而不是靠 load 的宽容


def settle(absent_minutes: float, sleeping: bool) -> tuple[dict[str, float], float]:
    """一段缺席时长 -> (各数值增量, 实际结算的分钟数)。上限只有这一处。

    过去离线路径有 12 小时上限、心跳路径没有，于是"同一晚不在电脑前"要看出门时
    她是不是开着：合上盖走的是无上限那条，一次唤醒就把她扣到零。
    """
    used = min(max(0.0, absent_minutes), MAX_OFFLINE_MINUTES)
    deltas = {}
    for key, rate in DECAY.items():
        if key == "energy" and sleeping:
            deltas[key] = used * SLEEP_ENERGY_RATE
        else:
            # 小睡是休息不是受罪：除了精力照常回，其余三项也漏，只是慢三倍
            deltas[key] = used * (rate / 3.0 if sleeping else rate)
    return deltas, used


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
        self.subkey_cool = {}
        self.weekly_snapshot = {}    # Q5b: 上次周记时的累计值（差值法算周增量）
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        # 没有 schema 字段的旧档（v0，也就是现在线上这份）与 v1 同读。
        # 以后数值结构要变，分支加在这一行上面，而不是让 load 一路宽容下去。
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
        self.subkey_cool = {k: float(v) for k, v in (raw.get("subkey_cool") or {}).items()}
        self.weekly_snapshot = dict(raw.get("weekly_snapshot") or {})

    def offline_minutes(self) -> float:
        return max(0.0, min((time.time() - self.last_seen) / 60.0, MAX_OFFLINE_MINUTES))

    def apply_offline(self) -> float:
        """Catch the needs up with real time that passed while she was closed."""
        minutes = self.offline_minutes()
        if minutes > 1:
            self._drain(minutes)
        self.last_seen = time.time()
        return minutes

    def tick(self, minutes: float) -> None:
        if minutes <= 0:
            return
        _, used = settle(minutes, self.sleeping)
        self._drain(minutes)
        # "一起在线"只在心跳这条路上记：她睡着的那几个小时不该算成陪伴
        self.stats["minutes_online"] = self.stats.get("minutes_online", 0) + used
        self.last_seen = time.time()

    def _drain(self, minutes: float) -> None:
        deltas, _ = settle(minutes, self.sleeping)
        for key, delta in deltas.items():
            self.needs[key] = _clamp(self.needs[key] + delta)

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

    def remember_line(self, line_id: str, keep: int = 40) -> None:
        self.line_history.append(line_id)
        self.line_history = self.line_history[-keep:]

    def recent_lines(self) -> set[str]:
        # Q2: 规避集扩到整条历史（40）——池子小的时候 fallback 会自然放行，
        # 大池子的重复感被显著推迟
        return set(self.line_history)

    def subkey_recent(self, key: str, seconds: float = 4 * 3600) -> bool:
        """Q2 分类级冷却：环境类子键 N 小时内不再触发（touch 等互动类不在此列）。"""
        return time.time() - self.subkey_cool.get(key, 0.0) < seconds

    def note_subkey(self, key: str) -> None:
        self.subkey_cool[key] = time.time()

    def save(self) -> None:
        payload = {
            "schema": SCHEMA,
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
            "subkey_cool": self.subkey_cool,
            "weekly_snapshot": self.weekly_snapshot,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def write_weekly(diary_dir: Path, life: Life, today: date) -> Path | None:
    """Q5b 周记：本周增量 = 当前累计 - 上次快照，周一写上周的账。

    日记里的数值是累计值，直接把七天的加起来会算错——所以用快照差值。
    首次（没有快照）只落快照不产出，从下一周开始才有得写。"""
    diary_dir.mkdir(parents=True, exist_ok=True)
    now_vals = {
        "minutes": int(life.stats.get("minutes_online", 0)),
        "pets": int(life.stats.get("pets", 0)),
        "feeds": int(life.stats.get("feeds", 0)),
        "ts": time.time(),
    }
    snap = life.weekly_snapshot
    if not snap:
        life.weekly_snapshot = now_vals
        return None
    week_monday = today - timedelta(days=today.weekday())
    path = diary_dir / f"week-{week_monday.isoformat()}.md"
    lines = [
        f"# 周记 {week_monday.isoformat()} ~ {(today - timedelta(days=1)).isoformat()}",
        "",
        f"- 本周一起在线 {max(0, now_vals['minutes'] - int(snap.get('minutes', 0)))} 分钟",
        f"- 本周摸头 {max(0, now_vals['pets'] - int(snap.get('pets', 0)))} 次，"
        f"喂食 {max(0, now_vals['feeds'] - int(snap.get('feeds', 0)))} 次",
        f"- 心情 {life.needs['mood']:.0f} / 精力 {life.needs['energy']:.0f} / 亲密 {life.needs['affection']:.0f}",
    ]
    peak = life.busiest_hour()
    if peak is not None:
        lines.append(f"- 你最活跃的钟点是 {int(peak)} 点")
    if life.top_file():
        lines.append(f"- 你最近最常碰的文件是 {life.top_file()}")
    lines.append("")
    lines.append("（数值来自快照差值；每天一篇的日记在同一个文件夹里。）")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    life.weekly_snapshot = now_vals
    return path


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
