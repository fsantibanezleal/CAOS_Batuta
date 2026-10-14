"""Guard `locked-tests`: a locked test file is changed only through an approved change request.

Reads the C07 lock file (its location is `tdd.lock_file` in the configuration, default `.batuta/test-locks.json`; the
tdd area writes the same file) and denies Edit, Write and shell writes (redirects, tee, sed -i, cp into a folder, mv,
rm, globs, links, find -delete, xargs, git apply, PowerShell cmdlets and aliases, inline interpreters) to any locked
path, case-insensitively, with either slash, through NTFS stream spellings, links, hard links and 8.3 names. The lock
file (default and configured location) and the `.batuta/` folder are protected the same way, so the guard cannot be
switched off by deleting its data. A write to `.batuta/batuta.json`, which holds the security keys (`guards.*`,
`tdd.lock_file`), is an `ask`: only the human approves it. No lock file means nothing is locked yet and the guard
allows. A malformed lock file raises only for a call that writes something (reads still pass): the launcher exits 1
(a non-blocking error) unless the hook entry has `onFailure: "block"`.
"""
from __future__ import annotations

import fnmatch
import os
import posixpath
import re
from pathlib import Path

from . import (FILE_TOOLS, allow, ask, candidate_roots, command_of, deny, existing_paths, file_path_of, guard_config,
               has_glob, norm_path, section, spellings, tool_name)
from . import shell
from . import text as textlib

NAME = "locked-tests"
DEFAULT_LOCK = ".batuta/test-locks.json"
CONFIG_FILE = ".batuta/batuta.json"
SECURITY_KEYS = "guards.* (require_brief, destructive_disable, secret_globs, protected_branches, scan_ignore), tdd.lock_file"
RECURSIVE = {"rm", "rmdir", "del", "erase", "rd", "remove-item", "ri", "mv", "move", "move-item", "mi", "git", "find",
             "rsync", "robocopy", "xcopy", "xargs", "ln", "mklink"}
INTERPRETERS = {"python", "python3", "py", "node", "nodejs", "deno", "bun", "ruby", "perl", "php", "lua", "powershell",
                "pwsh", "pythonw"}
INLINE_WRITE = re.compile(
    r"open\(\s*[^,()]+,\s*(mode\s*=\s*)?[\"'][rbt]*[wax+]|\.(write|write_text|write_bytes|unlink|rename|replace|truncate|touch)\("
    r"|writefile|appendfile|rmsync|unlinksync|renamesync|copyfile|shutil\.(copy|move|rmtree)|os\.(remove|rename|replace|unlink)"
    r"|\[(system\.)?io\.file\]::(write|append|delete|move|copy|create|open)|\.delete\(\)")
EXPLAIN = [
    "Denies Edit, Write and shell writes to the test files listed in the C07 lock file, to the lock file itself and to",
    "  removal of the .batuta/ folder; asks before any write to .batuta/batuta.json (the security keys).",
    "Lock file location: tdd.lock_file in batuta.json (default .batuta/test-locks.json, relative, no ..).",
    "Shell spellings covered: > >> tee sed -i perl -i cp/mv into a folder, rm, globs, ln and mklink, find -delete/-exec,",
    "  xargs, git apply, truncate dd install git checkout/restore, Set-Content Add-Content Out-File Tee-Object Remove-Item",
    "  Copy-Item Move-Item (and sc, ac, clc), bash -c, cmd /c, pwsh -c, wsl, subshells, inline python/node/.NET writes,",
    "  cd followed by a relative path, $PWD prefixes, any case, either slash, links and NTFS stream suffixes.",
    "A locked test changes only through a row of specs/<feature>/test-change-requests.md (C33).",
]


def lock_location(cfg: dict) -> str:
    value = section(cfg, "tdd").get("lock_file", DEFAULT_LOCK)
    if (not isinstance(value, str) or not value or value.startswith("/") or "\\" in value or ":" in value
            or ".." in value.split("/")):
        raise ValueError(f"tdd.lock_file {value!r} must be a relative POSIX path without '..'")
    return value


def load_lock(root: Path):
    """(relative lock path, locked paths in the lock file's spelling, or None when there is no lock file)."""
    from batuta_lib import contract
    cfg = guard_config(root, strict=True)
    rel = lock_location(cfg)
    path = root / rel
    if not path.is_file():
        return rel, None
    try:
        doc = contract.loads_strict(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        raise ValueError(f"{rel}: the lock file cannot be read ({exc})") from exc
    schema = contract.load_schema(contract.find_schema(Path(contract.__file__).resolve().parents[2] / "contracts", "C07"))
    problems = contract.validate_instance("C07", doc, schema)
    if problems:
        raise ValueError(f"{rel}: the lock file does not satisfy C07 ({'; '.join(problems[:3])})")
    return rel, {e["path"]: e.get("task_id", "") for e in doc["entries"]}


def state(root: Path) -> str:
    try:
        rel, locked = load_lock(root)
    except (ValueError, OSError) as exc:
        return f"the lock file is unusable: {exc}"
    if locked is None:
        return f"no lock file at {rel}: nothing is locked yet, the guard allows everything"
    return f"{len(locked)} locked path(s) in {rel}"


def _reason(path: str, task: str, kind: str) -> str:
    if kind == "lock":
        return (f"BLOCKED by guard-locked-tests: {path} is the test lock file (C07), or a folder that holds it; it is "
                "written only by the tdd area, never edited, moved or deleted by hand or by an agent.")
    return (f"BLOCKED by guard-locked-tests: {path} is a locked test" + (f" (task {task})" if task else "")
            + ". A locked test changes only through an approved change request: add a row to "
              "specs/<feature>/test-change-requests.md (C33) with the columns Id, Date, Test path, Requirement, "
              "Reason, Proposed change, Status (open), Decided by; change the test only after the request is "
              "approved, then the tdd area re-locks it.")


def _config_ask(token: str) -> dict:
    return ask(f"guard-locked-tests: {token} holds the harness security settings ({SECURITY_KEYS}). Changing them can switch "
               "a guard off, so only the human approves a write to it; ask the human to make or approve this change.")


def _targets(payload, name: str, command: str, path: str):
    """[(command name, token)] of everything the call writes, and the inline-interpreter flag."""
    if path:
        return [("edit", path)], False
    normal = textlib.normalize(command)
    pairs = shell.write_pairs(normal)
    inline = any(shell.command_name(s) in INTERPRETERS for s in shell.all_segments(normal)) or \
        "io.file]" in normal.lower()
    return pairs, inline


def _samefile(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def decide(payload) -> dict:
    name = tool_name(payload)
    command = command_of(payload)
    path = file_path_of(payload) if name in FILE_TOOLS else ""
    if not command and not path:
        return allow()
    pairs, inline = _targets(payload, name, command, path)
    if not pairs and not inline:
        return allow()
    cwd = payload.get("cwd") if isinstance(payload, dict) and isinstance(payload.get("cwd"), str) else ""
    asked = None
    for root in candidate_roots(payload, [t for _, t in pairs]):
        result, ask_hit = _check_root(root, cwd, pairs, inline, command)
        if result is not None:
            return result
        asked = asked or ask_hit
    return asked if asked is not None else allow()


def _check_root(root: Path, cwd: str, pairs, inline: bool, command: str):
    """(deny result or None, ask result or None) for one project root."""
    config_norm = norm_path(CONFIG_FILE)
    asked = None
    for cmd_name, token in pairs:
        for sp in spellings(token, root, cwd or None):
            if sp == config_norm or (cmd_name in RECURSIVE and sp and not has_glob(sp) and config_norm.startswith(sp.rstrip("/") + "/")):
                if cmd_name == "mklink":      # a link to the harness data is a way round every later check: denied outright
                    return deny(_reason(token, "", "lock")), asked
                asked = asked or _config_ask(token)
    needs_lock = bool(pairs) or inline
    if not needs_lock:
        return None, asked
    rel_lock, locked = load_lock(root)
    if locked is None:
        return None, asked
    lock_norms = {norm_path(rel_lock), norm_path(DEFAULT_LOCK)}
    by_norm = {norm_path(p): (p, t) for p, t in locked.items()}
    abs_locked = [(root / p, p, t) for p, t in locked.items()]

    def hit(cmd_name: str, token: str):
        recursive = cmd_name in RECURSIVE
        for sp in spellings(token, root, cwd or None):
            if not sp:
                if recursive and textlib.normalize(token).strip().strip("\"'") in (".", "./", ".\\"):
                    return rel_lock, "", "lock"       # a recursive operation on the project folder itself
                continue
            if has_glob(sp):
                for n in lock_norms:
                    if fnmatch.fnmatchcase(n, sp):
                        return n, "", "lock"
                for key, (orig, task) in by_norm.items():
                    if fnmatch.fnmatchcase(key, sp):
                        return orig, task, "test"
                continue
            if sp in lock_norms:
                return sp, "", "lock"
            if sp in by_norm:
                return by_norm[sp][0], by_norm[sp][1], "test"
            if recursive:
                base = sp.rstrip("/")
                if any(n.startswith(base + "/") for n in lock_norms):
                    return sp, "", "lock"
                for key, (orig, task) in by_norm.items():
                    if key.startswith(base + "/"):
                        return orig, task, "test"
        raw = textlib.normalize(token).strip().strip("\"'")
        if raw and not has_glob(raw) and not raw.startswith(("$", "%")):
            for found in existing_paths(raw, root, cwd or None):
                for abs_path, orig, task in abs_locked:
                    if _samefile(found, abs_path):
                        return orig, task, "test"
                if any(_samefile(found, root / n) for n in lock_norms):
                    return rel_lock, "", "lock"
        return None

    for cmd_name, token in pairs:
        found = hit(cmd_name, token)
        if found:
            return deny(_reason(*found[:2], found[2])), asked
    if inline:
        normal = textlib.normalize(command).replace("\\", "/").lower()
        texts = [normal] + [t.replace("\\", "/").lower() for t in textlib.nested_texts(textlib.normalize(command))]
        for orig, task in locked.items():
            base = posixpath.basename(norm_path(orig))
            if any(base in t and INLINE_WRITE.search(t) for t in texts):
                return deny(_reason(orig, task, "test")), asked
        lock_base = posixpath.basename(norm_path(rel_lock))
        if any(lock_base in t and INLINE_WRITE.search(t) for t in texts):
            return deny(_reason(rel_lock, "", "lock")), asked
    return None, asked
