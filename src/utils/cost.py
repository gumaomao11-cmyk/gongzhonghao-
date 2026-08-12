"""Token cost tracking and estimation (heuristic, no tokenizer required)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def estimate_tokens(text: str) -> int:
    """Rough token estimate without external tokenizer.

    Heuristic:
      - Chinese chars: ~1 token / 1.6 chars
      - English words: ~1 token / word
      - Whitespace/punct: ~0.3 token / char
    """
    import re

    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    ascii_words = len(re.findall(r"[A-Za-z]+", text))
    other = max(0, len(text) - chinese - sum(len(w) for w in re.findall(r"[A-Za-z]+", text)))
    return int(chinese / 1.6 + ascii_words + other * 0.3)


class CostTracker:
    """Daily token counter persisted as JSON. Used to enforce daily budget."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def today(self) -> int:
        return self._load().get(date.today().isoformat(), 0)

    def add(self, tokens: int) -> int:
        data = self._load()
        key = date.today().isoformat()
        data[key] = data.get(key, 0) + tokens
        self._save(data)
        return data[key]

    def budget_remaining(self, budget: int) -> int:
        return max(0, budget - self.today())
