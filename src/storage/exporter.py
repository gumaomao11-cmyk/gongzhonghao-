"""Status update side effects: meta.json + manifest.csv."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("autopost.exporter")

# CSV manifest header
FIELDS = ["id", "title", "category", "source", "platform", "char_count", "status", "ai_smell"]


def update_status(folder: str | Path, status: str, platform: str) -> bool:
    """Update a draft's meta.json + the parent manifest.csv.

    status in {pending, published, rejected}
    """
    folder = Path(folder)
    meta_path = folder / "meta.json"
    if not meta_path.exists():
        log.error("meta.json not found: %s", meta_path)
        return False

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if status not in ("pending", "published", "rejected"):
        log.error("invalid status: %s", status)
        return False

    meta["status"] = status
    meta["status_platform"] = platform
    meta["status_updated_at"] = datetime.now().isoformat(timespec="seconds")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # update manifest.csv
    manifest = folder.parent / "manifest.csv"
    if not manifest.exists():
        log.warning("manifest.csv not found, skipping CSV update: %s", manifest)
        return True

    rows: list[dict] = []
    updated = False
    with manifest.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r["id"] == meta["id"] and r["platform"] == platform:
                r["status"] = status
                updated = True
            rows.append(r)

    if updated:
        with manifest.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        log.info("status updated: %s -> %s on %s", meta["id"], status, platform)
    else:
        log.warning("no manifest row matched id=%s platform=%s", meta["id"], platform)

    return True
