"""SQLite storage for hot topics (raw cache + dedup support)."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from threading import local

log = logging.getLogger("autopost.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS hot_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT,
    score INTEGER DEFAULT 0,
    source TEXT,
    category TEXT,
    raw_json TEXT,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hot_topics_fetched ON hot_topics(fetched_at);
CREATE INDEX IF NOT EXISTS idx_hot_topics_source ON hot_topics(source);

CREATE TABLE IF NOT EXISTS published (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_published_topic ON published(topic_id);
"""


class HotTopicsDB:
    """Thread-local SQLite handle for hot topics."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        with sqlite3.connect(self.path) as c:
            c.executescript(SCHEMA)

    def insert_many(self, topics: list[dict]) -> int:
        if not topics:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        rows = [
            (
                t.get("title", ""),
                t.get("url", ""),
                int(t.get("score", 0) or 0),
                t.get("source", ""),
                t.get("category", ""),
                json.dumps(t, ensure_ascii=False),
                now,
            )
            for t in topics
        ]
        c = self._conn()
        c.executemany(
            "INSERT INTO hot_topics (title, url, score, source, category, raw_json, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        c.commit()
        log.info("inserted %d hot topics", len(rows))
        return len(rows)

    def recent(self, hours: int = 24) -> list[dict]:
        """Return topics fetched in the last N hours, deduplicated by title."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
        c = self._conn()
        rows = c.execute(
            "SELECT title, url, score, source, category, fetched_at "
            "FROM hot_topics WHERE fetched_at >= ? "
            "ORDER BY score DESC",
            (cutoff,),
        ).fetchall()
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            if r["title"] in seen:
                continue
            seen.add(r["title"])
            out.append(dict(r))
        return out

    def cleanup(self, days: int = 7) -> int:
        """Delete topics older than N days. Returns rowcount."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        c = self._conn()
        cur = c.execute("DELETE FROM hot_topics WHERE fetched_at < ?", (cutoff,))
        c.commit()
        return cur.rowcount
