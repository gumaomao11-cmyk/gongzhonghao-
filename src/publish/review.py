"""Interactive TUI for browsing and updating draft statuses.

Heavy dep `rich` is imported lazily so the module loads without it (the table
function just degrades to plain text printing).
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from ..storage.exporter import update_status

log = logging.getLogger("autopost.publish.review")


def list_drafts(day_dir: str | Path) -> list[Path]:
    day = Path(day_dir)
    if not day.exists():
        return []
    return sorted([p for p in day.iterdir() if p.is_dir()])


def show_table(day_dir: Path, *, use_rich: bool = True) -> None:
    """Print a table of drafts; falls back to plain text if rich is missing."""
    drafts = list_drafts(day_dir)
    rows: list[dict] = []
    for d in drafts:
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "id": d.name[:30],
                "title": meta.get("title", d.name)[:50],
                "category": meta.get("category", ""),
                "char_count": str(meta.get("char_count", "")),
                "status": meta.get("status", "pending"),
            }
        )

    if use_rich:
        try:
            from rich.console import Console
            from rich.table import Table
            console = Console()
            table = Table(title=f"drafts in {day_dir.name} ({len(drafts)} 篇)")
            table.add_column("#", style="cyan", no_wrap=True)
            table.add_column("标题", style="bold")
            table.add_column("分类")
            table.add_column("字数", justify="right")
            table.add_column("状态")
            for i, r in enumerate(rows, 1):
                color = {"pending": "yellow", "published": "green", "rejected": "red"}.get(r["status"], "white")
                table.add_row(str(i), r["title"], r["category"], r["char_count"], f"[{color}]{r['status']}[/]")
            console.print(table)
            return
        except ImportError:
            pass  # fall through to plain

    # plain text fallback
    print(f"\n=== drafts in {day_dir.name} ({len(rows)} 篇) ===")
    print(f"{'#':<3} {'title':<52} {'cat':<6} {'chars':>6}  status")
    for i, r in enumerate(rows, 1):
        print(f"{i:<3} {r['title']:<52} {r['category']:<6} {r['char_count']:>6}  {r['status']}")


def interactive_loop(day_dir: Path) -> int:
    drafts = list_drafts(day_dir)
    if not drafts:
        print(f"no drafts in {day_dir}")
        return 1

    show_table(day_dir)
    print("\nFor each draft: p=published, r=rejected, k=keep pending, q=quit\n")

    for d in drafts:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        platform = meta.get("platform", "?")
        print(f"{d.name}  ({platform})")
        print(f"  {meta.get('title', '')}")
        print(f"  chars {meta.get('char_count', '?')}  status {meta.get('status', 'pending')}")
        try:
            choice = input("  [p]ublish / [r]eject / [k]eep / [q]uit: ").strip().lower()
        except EOFError:
            return 0
        if choice == "q":
            return 0
        if choice == "p":
            update_status(d, "published", platform)
            print("  OK published")
        elif choice == "r":
            update_status(d, "rejected", platform)
            print("  OK rejected")
        else:
            print("  kept as pending")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review drafts interactively")
    parser.add_argument("day_dir", help="path to a day's draft folder, e.g. drafts/2026-08-12")
    args = parser.parse_args(argv)
    return interactive_loop(Path(args.day_dir))


if __name__ == "__main__":
    raise SystemExit(main())
