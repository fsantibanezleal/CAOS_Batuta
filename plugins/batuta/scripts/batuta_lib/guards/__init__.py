"""Shared pieces of the guards: handler results (C31 carrying C16 decisions), payload readers, the project root and
the guard configuration, path normalization.

A guard module defines `NAME`, `EXPLAIN` (what it checks, shown by `guard <name> --explain`) and
`decide(payload) -> handler_result`. The `guard` area wires them as hook handlers.
"""
from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path

from . import text as textlib

CONTRACT_VERSION = "1.0"
REASON_CAP = 2000          # a deny reason stays well under the official 10,000-character hook output cap
FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")
ROOT_MARKERS = (".batuta", ".git")


def allow() -> dict:
    return {"contract_version": CONTRACT_VERSION, "exit_code": 0, "output": None}


def _decision(kind: str, reason: str) -> dict:
    reason = " ".join(str(reason).split()) if "\n" not in str(reason) else str(reason).strip()
    if len(reason) > REASON_CAP:
        reason = reason[:REASON_CAP - 3] + "..."
    return {"contract_version": CONTRACT_VERSION, "exit_code": 0,
            "output": {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": kind,
                                              "permissionDecisionReason": reason}}}


def deny(reason: str) -> dict:
    return _decision("deny", reason)


def ask(reason: str) -> dict:
    return _decision("ask", reason)


def tool_name(payload) -> str:
    name = payload.get("tool_name") if isinstance(payload, dict) else None
    return name if isinstance(name, str) else ""


def tool_input(payload) -> dict:
    value = payload.get("tool_input") if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def command_of(payload) -> str:
    """The command text of a shell tool call, '' for any other call or a malformed input."""
    if tool_name(payload) not in SHELL_TOOLS:
        return ""
    value = tool_input(payload).get("command")
    return value if isinstance(value, str) else ""


def file_path_of(payload) -> str:
    value = tool_input(payload).get("file_path") or tool_input(payload).get("notebook_path")
    return value if isinstance(value, str) else ""


def project_root(payload) -> Path:
    """The project folder: CLAUDE_PROJECT_DIR, else the payload cwd, else the process cwd; then the nearest folder
    above it that holds `.batuta` or `.git` (the start folder when none does)."""
    start = None
    if isinstance(payload, dict) and isinstance(payload.get("cwd"), str) and payload["cwd"]:
        start = payload["cwd"]
    start = start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    base = Path(start)
    try:
        base = base.resolve()
    except OSError:
        pass
    for folder in (base, *base.parents):
        if any((folder / marker).exists() for marker in ROOT_MARKERS):
            return folder
    return base


def guard_config(root: Path, strict: bool = False) -> dict:
    """The resolved configuration (C01 plus the `guards`, `tdd` and `leaks` extras). Non-strict: a configuration that
    cannot be read falls back to the built-in defaults, so an extra list is only ever an addition."""
    from batuta_lib import config
    try:
        return config.load(project_root=root).config
    except (config.ConfigError, OSError):
        if strict:
            raise
        return config.default_config()


def section(cfg: dict, name: str) -> dict:
    value = cfg.get(name)
    return value if isinstance(value, dict) else {}


def string_list(value, default=()) -> list[str]:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    return list(default)


_PWD = re.compile(r"^(?:\$\{?pwd\}?|\$\(pwd\)|%cd%|\$env:pwd|\$pwd)/", re.IGNORECASE)


def norm_path(token: str, root: Path | None = None) -> str:
    """A path as the guards compare it: normalized text, POSIX slashes, lower case, no `./` or `$PWD/` prefix, and
    relative to `root` when it is absolute and lies under it."""
    t = textlib.normalize(token).strip().strip("\"'").replace("\\", "/")
    t = re.sub(r"^/([A-Za-z])/", r"\1:/", t)          # /c/work (Git Bash) -> c:/work
    t = _PWD.sub("", t)
    while t.startswith("./"):
        t = t[2:]
    t = re.sub(r"/{2,}", "/", t)
    if t and not t.startswith(("~", "$", "%")):
        t = posixpath.normpath(t)
    t = t.lower()
    if root is not None:
        r = norm_path(str(root))
        stripped = _under(t, r)
        if stripped is None and is_absolute(t) and not t.startswith("~"):
            try:  # a short (8.3) or symlinked spelling of the same folder
                real = norm_path(os.path.realpath(textlib.normalize(token).strip().strip("\"'")))
                stripped = _under(real, r)
            except (OSError, ValueError):
                stripped = None
        if stripped is not None:
            t = stripped
    return "" if t == "." else t


def _under(path: str, root: str) -> str | None:
    base = root.rstrip("/")
    if path.startswith(base + "/"):
        return path[len(base) + 1:]
    return "" if path == base else None


def is_absolute(norm: str) -> bool:
    return norm.startswith(("/", "~")) or bool(re.match(r"^[a-z]:/", norm))
