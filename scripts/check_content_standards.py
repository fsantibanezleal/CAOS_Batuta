#!/usr/bin/env python3
"""Fail the build if tracked text content carries an em-dash, an emoji or an absolute user path.

Adapted from CAOS_PRODUCT_TEMPLATE `scripts/check_content_standards.py` (ADR-0067: no em-dash, no emoji),
with one more rule for this batuta: no shipped file may contain a machine path (design principle 6, DEV-1).

What it flags:
  - em-dash U+2014 and horizontal bar U+2015;
  - emoji: U+1F000..U+1FAFF and the emoji-presentation selector U+FE0F;
  - an absolute user path: a drive-letter users folder, a POSIX home folder, a macOS users folder.

Not flagged: the ASCII double hyphen, the en-dash, the middot, arrows, check marks, and path placeholders such
as `/home/<name>/`. English-only (ADR-0066) cannot be checked mechanically and is left to review.

The scanned set is every tracked text file plus untracked files that are not ignored. Exit 1 on any hit,
printing `file:line:col`.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

BANNED_DASHES = {0x2014, 0x2015}
EMOJI_SELECTOR = 0xFE0F
USER_PATH = re.compile(r"[A-Za-z]:[\\/]Users[\\/]|/home/[A-Za-z0-9_.-]+/|/Users/[A-Za-z0-9_.-]+/")

TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yml", ".yaml", ".toml", ".txt", ".cfg", ".ini", ".mjs", ".js", ".cjs",
    ".ts", ".sh", ".ps1", ".html", ".css", ".svg", ".editorconfig", ".gitignore", ".gitattributes",
}
TEXT_NAMES = {"LICENSE", "VERSION"}


class Hit(NamedTuple):
    path: str
    line: int
    col: int
    kind: str
    detail: str


def is_emoji(cp: int) -> bool:
    return 0x1F000 <= cp <= 0x1FAFF or cp == EMOJI_SELECTOR


def scan_text(path: str, text: str) -> list[Hit]:
    hits: list[Hit] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for col, ch in enumerate(line, 1):
            cp = ord(ch)
            if cp in BANNED_DASHES:
                hits.append(Hit(path, lineno, col, "em-dash", f"U+{cp:04X}"))
            elif is_emoji(cp):
                hits.append(Hit(path, lineno, col, "emoji", f"U+{cp:04X}"))
        for match in USER_PATH.finditer(line):
            hits.append(Hit(path, lineno, match.start() + 1, "user-path", "absolute user path"))
    return hits


def is_text_file(rel: str) -> bool:
    path = Path(rel)
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES or path.name.startswith(".")


def candidate_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root, capture_output=True, text=True, check=True,
    )
    return sorted({ln.strip() for ln in out.stdout.splitlines() if ln.strip()})


def scan_repo(root: Path) -> list[Hit]:
    hits: list[Hit] = []
    for rel in candidate_files(root):
        if not is_text_file(rel) or not (root / rel).is_file():
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits.extend(scan_text(rel, text))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="repository root (default: the repository this script lives in)")
    args = parser.parse_args(argv)
    hits = scan_repo(args.root.resolve())
    if not hits:
        print("check_content_standards: OK, no em-dash, emoji or absolute user path in repository text.")
        return 0
    print("check_content_standards: FAIL")
    for h in hits:
        print(f"  {h.path}:{h.line}:{h.col}  {h.kind} ({h.detail})")
    print("\nReplace an em-dash with a comma, colon, semicolon, period or parentheses; remove emoji; "
          "replace a user path with an environment variable or a placeholder.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
