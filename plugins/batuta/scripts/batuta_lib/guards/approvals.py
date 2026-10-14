"""Guard `approvals`: an agent never writes under the `approvals/` folder of a spec.

The approval record (C06) proves a human approved a frozen spec: the human types `approve <spec id> <first 12 hex of
the spec sha256>`, and the record is written from that prompt (or by the manual `spec approve` command run by the
human). This guard denies Edit, Write and shell writes (redirects, cp or Copy-Item into the folder, sc/ac, links,
pipe-fed deletes, globs, cmd /c bodies) to `specs/<id>/approvals/`, resolves existing links and junctions, and asks
before an agent runs `spec approve --apply`.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from . import (FILE_TOOLS, allow, ask, candidate_roots, command_of, deny, file_path_of, has_glob, norm_path,
               project_root, spellings, tool_name)
from . import shell
from . import text as textlib
from .locked_tests import INLINE_WRITE, INTERPRETERS

NAME = "approvals"
APPROVALS = re.compile(r"(^|/)specs/[^/]+/approvals(/|$)")
APPROVALS_TEXT = re.compile(r"specs/[^/\s'\"]+/approvals(?:/|\b)")
APPROVE_CMD = re.compile(r"\bspec\s+approve\b", re.IGNORECASE)
APPLY = re.compile(r"--apply\b")
EXPLAIN = [
    "Denies Edit, Write and shell writes under specs/<spec id>/approvals/ (the C06 approval records).",
    "The approval is typed by the human: `approve <spec id> <first 12 hex of the spec sha256>`; an agent never writes it.",
    "Asks before an agent runs `spec approve ... --apply` (the manual fallback is the human's command).",
]
PHRASE = "approve <spec id> <first 12 hex of the spec sha256>"


def _approval_dirs(root: Path) -> list[Path]:
    try:
        return [p for p in root.glob("**/specs/*/approvals") if p.is_dir()] if root.is_dir() else []
    except OSError:
        return []


def state(root: Path) -> str:
    found = _approval_dirs(root)[:3]
    if not found:
        return "no approvals folder under specs/<id>/: nothing to protect yet, the guard still denies writes to one"
    return f"approvals folders: {', '.join(p.relative_to(root).as_posix() for p in found)}"


def _deny(path: str) -> dict:
    return deny(f"BLOCKED by guard-approvals: {path} is in an approvals folder of a spec (C06). The approval is typed "
                f"by the human as `{PHRASE}` and recorded from that prompt; an agent never writes an approval record. "
                "Ask the human to type the approval phrase.")


def _glob_hits(spelling: str, root: Path) -> bool:
    """Does a glob target match an existing file or folder of an approvals folder?"""
    for folder in _approval_dirs(root):
        rel = folder.relative_to(root).as_posix().lower()
        names = [rel] + [f"{rel}/{p.relative_to(folder).as_posix().lower()}" for p in folder.rglob("*")]
        if any(fnmatch.fnmatchcase(n, spelling) for n in names):
            return True
    return False


def decide(payload) -> dict:
    name = tool_name(payload)
    command = command_of(payload)
    path = file_path_of(payload) if name in FILE_TOOLS else ""
    cwd = payload.get("cwd") if isinstance(payload, dict) and isinstance(payload.get("cwd"), str) else None
    if path:
        for root in candidate_roots(payload, [path]):
            if any(APPROVALS.search(sp) for sp in spellings(path, root, cwd)):
                return _deny(path)
        return allow()
    if not command:
        return allow()
    normal = textlib.normalize(command)
    pairs = shell.write_pairs(normal)
    for root in candidate_roots(payload, [t for _, t in pairs]):
        for _name, token in pairs:
            for sp in spellings(token, root, cwd):
                if APPROVALS.search(sp) or (has_glob(sp) and _glob_hits(sp, root)):
                    return _deny(token)
    segs = shell.all_segments(normal)
    flat = normal.replace("\\", "/").lower()
    if any(shell.command_name(s) in INTERPRETERS for s in segs) or "io.file]" in flat:
        texts = [flat] + [t.replace("\\", "/").lower() for t in textlib.nested_texts(normal)]
        if any(APPROVALS_TEXT.search(t) and INLINE_WRITE.search(t) for t in texts):
            return _deny("a path under specs/<id>/approvals/")
    for seg in segs:
        if APPROVE_CMD.search(" ".join(seg.words)) and APPLY.search(" ".join(seg.words)):
            return ask("guard-approvals: `spec approve --apply` records a human approval. Run it only when the human "
                       f"typed `{PHRASE}` for this exact spec; otherwise leave it to the human.")
    return allow()
