"""Copy a single draft's content to the system clipboard.

Heavy deps `pyperclip` and `plyer` are imported lazily so this module loads
even when they are missing (will fall back to stdout print + silent notify).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger("autopost.publish.copy")

PLATFORM_FILES = {
    "wechat": "wechat.html",
    "bjh": "bjh.txt",
}


def copy_draft(folder: str | Path, platform: str) -> str:
    """Read the platform-specific file from a draft folder and copy to clipboard.

    Returns the file content (also placed on the clipboard if pyperclip works).
    """
    folder = Path(folder)
    if platform not in PLATFORM_FILES:
        raise ValueError(f"unknown platform {platform!r}; choose from {list(PLATFORM_FILES)}")
    file = folder / PLATFORM_FILES[platform]
    if not file.exists():
        raise FileNotFoundError(
            f"{file} not found; this draft was generated for a different platform?"
        )
    content = file.read_text(encoding="utf-8")
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(content)
    except Exception as e:
        log.warning("pyperclip failed (%s); printing to stdout instead", e)
        print(content)
        return content
    log.info("copied %d chars to clipboard from %s (%s)", len(content), file, platform)
    _notify(f"已复制 {platform} 草稿到剪贴板({len(content)} 字符)")
    return content


def _notify(msg: str) -> None:
    """Best-effort desktop notification (silent if plyer/backend missing)."""
    try:
        from plyer import notification  # type: ignore
        notification.notify(title="autopost", message=msg, timeout=3)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy a draft to clipboard")
    parser.add_argument("folder", help="path to a draft folder, e.g. drafts/2026-08-12/01-xxx")
    parser.add_argument("--platform", choices=list(PLATFORM_FILES), required=True)
    args = parser.parse_args(argv)

    try:
        copy_draft(args.folder, args.platform)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
