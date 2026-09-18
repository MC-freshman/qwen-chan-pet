"""Line picker: choose from a hand-written pool. Nothing here is generated."""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

_FORMAT = string.Formatter()


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in _FORMAT.parse(text) if name}


class Speech:
    def __init__(self, path: Path, life, rng: random.Random | None = None):
        self.tree = json.loads(Path(path).read_text(encoding="utf-8"))
        self.life = life
        self.rng = rng or random.Random()

    def candidates(self, category: str, sub: str | None = None) -> list[tuple[str, str]]:
        group = self.tree.get(category, {})
        keys = [sub] if sub else list(group)
        out = []
        for key in keys:
            for index, text in enumerate(group.get(key) or []):
                out.append((f"{category}/{key}/{index}", text))
        return out

    def pick(self, category: str, sub: str | None = None, **variables) -> str | None:
        """Return one line whose placeholders we can actually fill, avoiding repeats."""
        recent = self.life.recent_lines()
        pool = []
        for line_id, text in self.candidates(category, sub):
            missing = _placeholders(text) - set(variables)
            if missing:
                continue
            pool.append((line_id, text, line_id in recent))
        if not pool:
            return None
        fresh = [item for item in pool if not item[2]]
        line_id, text, _ = self.rng.choice(fresh or pool)
        self.life.remember_line(line_id)
        return text.format(**variables)
