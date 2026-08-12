"""Topic deduplication against history (last 30 days)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .text import jaccard


class TopicHistory:
    """JSONL-backed history of generated topics; auto-prunes entries > 30 days old."""

    def __init__(self, path: str | Path, window_days: int = 30):
        self.path = Path(path)
        self.window_days = window_days
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        cutoff = datetime.now() - timedelta(days=self.window_days)
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                ts = datetime.fromisoformat(row.get("at", ""))
            except ValueError:
                continue
            if ts >= cutoff:
                out.append(row)
        return out

    def is_duplicate(self, title: str, threshold: float = 0.6) -> bool:
        """Return True if `title` is too similar to any recent topic."""
        history = self._load()
        titles = [h.get("title", "") for h in history]
        for old in titles:
            if jaccard(title, old) > threshold:
                return True
        return False

    def add(self, title: str, source: str, category: str = "") -> None:
        """Append a new topic to history (and rewrite to drop expired rows)."""
        history = self._load()
        history.append(
            {
                "title": title,
                "source": source,
                "category": category,
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        # Rewrite (drops expired)
        self.path.write_text(
            "\n".join(json.dumps(h, ensure_ascii=False) for h in history) + "\n",
            encoding="utf-8",
        )
