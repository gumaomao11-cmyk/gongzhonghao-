"""Mark a draft as published/rejected."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ..storage.exporter import update_status

log = logging.getLogger("autopost.publish.update_status")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update draft status")
    parser.add_argument(
        "folder",
        nargs="?",
        help="path to a draft folder; if omitted, uses current directory",
    )
    parser.add_argument(
        "--status",
        required=True,
        choices=["pending", "published", "rejected"],
    )
    parser.add_argument(
        "--platform",
        required=True,
        choices=["wechat", "bjh"],
    )
    args = parser.parse_args(argv)

    folder = Path(args.folder) if args.folder else Path.cwd()
    if not (folder / "meta.json").exists():
        print(f"ERROR: meta.json not found in {folder}", file=sys.stderr)
        return 1

    if not update_status(folder, args.status, args.platform):
        print("ERROR: status update failed; see logs", file=sys.stderr)
        return 1

    print(f"OK: {folder.name} -> {args.status} on {args.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
