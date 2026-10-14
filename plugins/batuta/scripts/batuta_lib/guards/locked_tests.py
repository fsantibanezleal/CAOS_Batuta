"""Guard `locked-tests`: a locked test file is changed only through an approved change request.

Reads the C07 lock file (its location is `tdd.lock_file` in the configuration, default `.batuta/test-locks.json`; the
tdd area writes the same file) and denies Edit, Write and shell writes (redirects, tee, sed -i, cp, mv, rm, git
checkout, Set-Content, inline interpreters) to any locked path, case-insensitively and with either slash. The lock file
itself is protected the same way. No lock file means nothing is locked yet and the guard allows. A malformed lock file
raises: the launcher exits 1 (a non-blocking error) unless the hook entry has `onFailure: "block"`.
"""
from __future__ import annotations

import posixpath
import re
from pathlib import Path

from . import FILE_TOOLS, allow, command_of, deny, file_path_of, guard_config, norm_path, project_root, section, tool_name
from . import shell
from . import text as textlib

NAME = "locked-tests"
DEFAULT_LOCK = ".batuta/test-locks.json"
RECURSIVE = {"rm", "rmdir", "del", "erase", "rd", "remove-item", "ri", "mv", "move", "move-item", "mi", "git"}
INTERPRETERS = {"python", "python3", "py", "node", "nodejs", "deno", "bun", "ruby", "perl", "php", "lua", "powershell",
                "pwsh", "pythonw"}
INLINE_WRITE = re.compile(
    r"open\(\s*[^,()]+,\s*(mode\s*=\s*)?[\"'][rbt]*[wax+]|\.(write|write_text|write_bytes|unlink|rename|replace|truncate|touch)\("
    r"|writefile|appendfile|rmsync|unlinksync|renamesync|copyfile|shutil\.(copy|move|rmtree)|os\.(remove|rename|replace|unlink)"
    r"|\[(system\.)?io\.file\]::(write|append|delete|move|copy|create|open)|\.delete\(\)")
EXPLAIN = [
    "Denies Edit, Write and shell writes to the test files listed in the C07 lock file, and to the lock file itself.",
    "Lock file location: tdd.lock_file in batuta.json (default .batuta/test-locks.json, relative, no ..).",
    "Shell spellings covered: > >> tee sed -i perl -i cp mv rm truncate dd install git checkout/restore Set-Content",
    "  Add-Content Out-File Remove-Item Copy-Item Move-Item, bash -c and pwsh -Command bodies, subshells, inline",
    "  python/node/.NET writes, cd followed by a relative path, $PWD prefixes, any case, either slash.",
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


def _reason(path: str, task: str, is_lock_file: bool) -> str:
    if is_lock_file:
        return (f"BLOCKED by guard-locked-tests: {path} is the test lock file (C07); it is written only by the "
                "tdd area, never edited by hand or by an agent.")
    return (f"BLOCKED by guard-locked-tests: {path} is a locked test" + (f" (task {task})" if task else "")
            + ". A locked test changes only through an approved change request: add a row to "
              "specs/<feature>/test-change-requests.md (C33) with the columns Id, Date, Test path, Requirement, "
              "Reason, Proposed change, Status (open), Decided by; change the test only after the request is "
              "approved, then the tdd area re-locks it.")


def decide(payload) -> dict:
    name = tool_name(payload)
    command = command_of(payload)
    path = file_path_of(payload) if name in FILE_TOOLS else ""
    if not command and not path:
        return allow()
    root = project_root(payload)
    rel_lock, locked = load_lock(root)
    if locked is None:
        return allow()
    by_norm = {norm_path(p): (p, t) for p, t in locked.items()}
    lock_norm = norm_path(rel_lock)
    cwd = payload.get("cwd") if isinstance(payload, dict) and isinstance(payload.get("cwd"), str) else ""
    cwd_rel = norm_path(cwd, root) if cwd else ""

    def spellings(token: str) -> list[str]:
        n = norm_path(token, root)
        out = [n]
        if cwd_rel and n and n != cwd_rel and not n.startswith(("/", "~", "$", "%")) and not re.match(r"^[a-z]:/", n):
            out.append(posixpath.normpath(cwd_rel + "/" + n))
        return out

    def hit(token: str, recursive: bool):
        for n in spellings(token):
            if not n:
                continue
            if n == lock_norm:
                return rel_lock, "", True
            if n in by_norm:
                return by_norm[n][0], by_norm[n][1], False
            if recursive:
                for key, (orig, task) in by_norm.items():
                    if key.startswith(n.rstrip("/") + "/"):
                        return orig, task, False
        return None

    if path:
        found = hit(path, False)
        return deny(_reason(*found)) if found else allow()
    for cmd_name, token in shell.write_pairs(textlib.normalize(command)):
        found = hit(token, cmd_name in RECURSIVE)
        if found:
            return deny(_reason(*found))
    # inline interpreter writes: the path is inside a code string, so look at the text of the whole command
    normal = textlib.normalize(command).replace("\\", "/").lower()
    if any(shell.command_name(s) in INTERPRETERS for s in shell.all_segments(textlib.normalize(command))) or "io.file]" in normal:
        texts = [normal] + [t.replace("\\", "/").lower() for t in textlib.nested_texts(textlib.normalize(command))]
        for orig, task in locked.items():
            base = posixpath.basename(norm_path(orig))
            if any(base in t and INLINE_WRITE.search(t) for t in texts):
                return deny(_reason(orig, task, False))
        if lock_norm and any(posixpath.basename(lock_norm) in t and INLINE_WRITE.search(t) for t in texts):
            return deny(_reason(rel_lock, "", True))
    return allow()
