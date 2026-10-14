"""Guard `approvals`: an agent never writes under the `approvals/` folder of a spec.

The approval record (C06) proves a human approved a frozen spec: the human types `approve <spec id> <first 12 hex of
the spec sha256>`, and the record is written from that prompt (or by the manual `spec approve` command run by the
human). This guard denies Edit, Write and shell writes to `specs/<id>/approvals/` and asks before an agent runs
`spec approve --apply`.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import FILE_TOOLS, ask, allow, command_of, deny, file_path_of, norm_path, project_root, tool_name
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


def state(root: Path) -> str:
    found = [p for p in root.glob("**/specs/*/approvals") if p.is_dir()][:3] if root.is_dir() else []
    if not found:
        return "no approvals folder under specs/<id>/: nothing to protect yet, the guard still denies writes to one"
    return f"approvals folders: {', '.join(p.relative_to(root).as_posix() for p in found)}"


def _deny(path: str) -> dict:
    return deny(f"BLOCKED by guard-approvals: {path} is in an approvals folder of a spec (C06). The approval is typed "
                f"by the human as `{PHRASE}` and recorded from that prompt; an agent never writes an approval record. "
                "Ask the human to type the approval phrase.")


def decide(payload) -> dict:
    name = tool_name(payload)
    command = command_of(payload)
    path = file_path_of(payload) if name in FILE_TOOLS else ""
    if path:
        return _deny(path) if APPROVALS.search(norm_path(path, project_root(payload))) else allow()
    if not command:
        return allow()
    root = project_root(payload)
    normal = textlib.normalize(command)
    for _name, token in shell.write_pairs(normal):
        if APPROVALS.search(norm_path(token, root)):
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
