"""Guard `approvals`: an agent never writes under the `approvals/` folder of a spec.

The approval record (C06) proves a human approved a frozen spec: the human types `approve <spec id> <first 12 hex of
the spec sha256>`, and the record is written from that prompt (or by the manual `spec approve` command run by the
human). This guard denies Edit, Write and shell writes (redirects, cp or Copy-Item into the folder, sc/ac, links,
pipe-fed deletes, globs, cmd /c bodies) to `specs/<id>/approvals/`, resolves existing links and junctions, and denies
every invocation of the approval commands (`batuta.py spec approve`, `batuta.py spec hook-approval`, `hook.py
spec-approval`): an agent never creates an approval, in any spelling the guards parse.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from . import (FILE_TOOLS, allow, candidate_roots, command_of, deny, file_path_of, has_glob, norm_path,
               project_root, spellings, tool_name)
from . import shell
from . import text as textlib
from .locked_tests import INLINE_WRITE, INTERPRETERS

NAME = "approvals"
APPROVALS = re.compile(r"(^|/)specs/[^/]+/approvals(/|$)")
APPROVALS_TEXT = re.compile(r"specs/[^/\s'\"]+/approvals(?:/|\b)")
TABLE_PATH = re.compile(r"(^|/)test-change-requests\.md$")
TABLE_TEXT = re.compile(r"test-change-requests\.md")
DECIDE_CMD = re.compile(r"\btdd\s+change-request\s+decide\b", re.IGNORECASE)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
APPROVE_CMD = re.compile(r"\bspec\s+(approve|hook-approval)\b", re.IGNORECASE)
HOOK_CMD = re.compile(r"\bspec-approval\b", re.IGNORECASE)
BATUTA_WORD = re.compile(r"^batuta(\.py|\.exe|\.cmd)?$", re.IGNORECASE)
HOOK_WORD = re.compile(r"^hook(\.py)?$", re.IGNORECASE)
CONTINUATION = re.compile(r"\\\r?\n|`\r?\n")
EXPLAIN = [
    "Denies Edit, Write and shell writes under specs/<spec id>/approvals/ (the C06 approval records) and to any",
    "  test-change-requests.md; denies `tdd change-request decide` (`tdd change-request new` stays allowed).",
    "The approval is typed by the human: `approve <spec id> <first 12 hex of the spec sha256>`; an agent never writes it.",
    "Denies every invocation of `batuta.py spec approve`, `batuta.py spec hook-approval` and `hook.py spec-approval`.",
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


def _deny_table(path: str) -> dict:
    return deny(f"BLOCKED by guard-approvals: {path} is a test change request table (C33). A request is filed with "
                "`tdd change-request new` (it appends only `open` rows); it is decided by the human, who runs "
                "`tdd change-request decide` in their own terminal. An agent never edits the table by hand.")


def _table_files(root: Path) -> list[str]:
    """Normalized paths (relative to `root`) of the existing change request tables; the walk is bounded."""
    found, count = [], 0
    try:
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            count += len(files) + len(dirs)
            if count > 20000:
                break
            if "test-change-requests.md" in (f.lower() for f in files):
                found.append(norm_path(str(Path(current) / "test-change-requests.md"), root))
    except OSError:
        pass
    return found


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
            for sp in spellings(path, root, cwd):
                if APPROVALS.search(sp):
                    return _deny(path)
                if TABLE_PATH.search(sp):
                    return _deny_table(path)
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
                if TABLE_PATH.search(sp) or (has_glob(sp) and any(fnmatch.fnmatchcase(t, sp) for t in _table_files(root))):
                    return _deny_table(token)
    segs = shell.all_segments(normal)
    flat = normal.replace("\\", "/").lower()
    if any(shell.command_name(s) in INTERPRETERS for s in segs) or "io.file]" in flat:
        texts = [flat] + [t.replace("\\", "/").lower() for t in textlib.nested_texts(normal)]
        if any(APPROVALS_TEXT.search(t) and INLINE_WRITE.search(t) for t in texts):
            return _deny("a path under specs/<id>/approvals/")
        if any(TABLE_TEXT.search(t) and INLINE_WRITE.search(t) for t in texts):
            return _deny_table("test-change-requests.md")
    if _runs_command(normal, ((DECIDE_CMD, BATUTA_WORD),)):
        return deny("BLOCKED by guard-approvals: a test change request is decided by the human, never by the agent. Ask the "
                    "human to run `tdd change-request decide` in their own terminal. You may file a request with "
                    "`tdd change-request new` (it appends only `open` rows).")
    if _runs_approval_command(normal):
        return deny("BLOCKED by guard-approvals: an approval is the human's act, never the agent's. Ask the human to type "
                    f"`{PHRASE}` in the prompt (the hook records it), or to run `spec approve` in their own terminal. "
                    "`spec show` and `spec freeze --check` are fine to run.")
    return allow()


def _runs_command(normal: str, rules) -> bool:
    """Does any segment (after line continuations and obfuscation are removed, nested commands included) hold the words of
    a rule (a phrase pattern) together with a word named like the tool (`batuta`, `batuta.py`)?"""
    text = CONTINUATION.sub(" ", normal)
    for variant in (text, textlib.deobfuscate(text)):
        for seg in shell.all_segments(variant):
            words = [w.replace("\\", "/").rsplit("/", 1)[-1] for w in seg.words]
            joined = " ".join(w.lower() for w in seg.words)
            for phrase, tool in rules:
                if phrase.search(joined) and any(tool.match(w) for w in words):
                    return True
    return False


def _runs_approval_command(normal: str) -> bool:
    """Does the command line invoke `batuta.py spec approve`, `batuta.py spec hook-approval` or `hook.py spec-approval`
    (any launcher, path, case, quoting, nesting, assignment prefix or chaining)?"""
    text = CONTINUATION.sub(" ", normal)
    for variant in (text, textlib.deobfuscate(text)):
        for seg in shell.all_segments(variant):
            words = [w.replace("\\", "/").rsplit("/", 1)[-1] for w in seg.words]
            joined = " ".join(w.lower() for w in seg.words)
            if APPROVE_CMD.search(joined) and any(BATUTA_WORD.match(w) for w in words):
                return True
            if HOOK_CMD.search(joined) and any(HOOK_WORD.match(w) for w in words):
                return True
    return False
