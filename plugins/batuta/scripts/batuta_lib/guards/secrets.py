"""Guard `secrets`: files that match the secret globs are never read by an agent.

Covers the Read tool, Grep and Glob paths and globs, shell reads (cat, type, head, grep, Get-Content, source, cp,
curl @file, `<` redirects, `git show REV:path`, inline interpreter and .NET reads), glob operands that match a secret
file on disk (`cat .e*`), recursive searches over a folder that holds a secret file (unless an exclude covers it),
and existing links, junctions, 8.3 names and NTFS stream spellings of a secret file. The defaults cover environment
files, private keys and certificates, cloud and package-registry credentials; `guards.secret_globs` in batuta.json
adds more. Templates (`.env.example` and the like) and public keys are allowed.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from . import (allow, candidate_roots, command_of, deny, file_path_of, guard_config, has_glob, norm_path,
               project_root, section, shell, spellings, string_list, tool_input, tool_name)
from . import text as textlib

NAME = "secrets"
DEFAULT_GLOBS = [
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa", "id_rsa.*", "id_dsa", "id_dsa.*", "id_ecdsa",
    "id_ecdsa.*", "id_ed25519", "id_ed25519.*", "credentials", "credentials.*", ".npmrc", ".pypirc", ".netrc",
    ".git-credentials", "secrets/**", ".ssh/**",
]
ALLOW_GLOBS = ["*.example", "*.sample", "*.template", "*.dist", "*.pub"]
READ_WORDS = re.compile(r"open\(|read|load|\bcat\b|\btype\b|get-content|fopen|slurp")
INTERPRETERS = {"python", "python3", "py", "node", "nodejs", "deno", "bun", "ruby", "perl", "php", "powershell", "pwsh"}
RECURSIVE_ALWAYS = {"rg", "ag", "ack"}
RECURSIVE_FLAGGED = {"grep", "egrep", "fgrep", "select-string", "sls", "findstr"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".mypy_cache"}
WALK_CAP = 20000
EXPLAIN = [
    "Denies reads of files that match the secret globs (Read, Grep and Glob paths and globs, shell reads, inline",
    "  interpreter and .NET reads, git show REV:path, glob operands that match a secret on disk, recursive searches",
    "  over a folder that holds one, links and NTFS stream spellings).",
    "Default globs: " + ", ".join(DEFAULT_GLOBS),
    "Allowed templates and public keys: " + ", ".join(ALLOW_GLOBS),
    "Add globs with guards.secret_globs in batuta.json (a list of strings); a broken configuration keeps the defaults.",
]


def state(root: Path) -> str:
    extra = string_list(section(guard_config(root), "guards").get("secret_globs"))
    return f"{len(DEFAULT_GLOBS)} default globs and {len(extra)} configured"


def match(path: str, globs: list[str]) -> str | None:
    """The glob that marks `path` (already normalized) as secret, None when none does or it is a template or public key."""
    if not path:
        return None
    parts = [p for p in path.split("/") if p and p not in (".", "..")]
    if not parts:
        return None
    base = parts[-1]
    if any(fnmatch.fnmatchcase(base, a) for a in ALLOW_GLOBS):
        return None
    for glob in globs:
        g = glob.lower()
        if g.endswith("/**"):
            if g[:-3] in parts:
                return glob
        elif "/" in g:
            if fnmatch.fnmatchcase(path, g) or fnmatch.fnmatchcase(path, "*/" + g):
                return glob
        elif fnmatch.fnmatchcase(base, g):
            return glob
    return None


def _globs(root: Path) -> list[str]:
    return DEFAULT_GLOBS + string_list(section(guard_config(root), "guards").get("secret_globs"))


def secret_files(folder: Path, globs: list[str], root: Path) -> list[str]:
    """Paths (relative to `root`, normalized) of the secret files under `folder`; the walk is bounded."""
    found: list[str] = []
    count = 0
    try:
        for current, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files + dirs:
                count += 1
                if count > WALK_CAP:
                    return found
                full = Path(current) / name
                rel = norm_path(str(full), root)
                if match(rel, globs) and (name in files):
                    found.append(rel)
    except OSError:
        pass
    return found


def _deny(token: str, glob: str) -> dict:
    return deny(f"BLOCKED by guard-secrets: {token} matches the secret glob '{glob}'. Do not read credential files; "
                "ask the user for the value, or use the name of the environment variable that holds it.")


def _glob_target_hit(sp: str, root: Path, globs: list[str]):
    for rel in secret_files(root, globs, root):
        if fnmatch.fnmatchcase(rel, sp) or fnmatch.fnmatchcase(rel.rsplit("/", 1)[-1], sp):
            return rel, match(rel, globs)
    return None


def _recursive_search(seg, root: Path, cwd, globs: list[str]):
    """A recursive grep or rg over a folder that holds an uncovered secret file: (folder, secret) or None."""
    name, args = shell.command_name(seg), shell.args_of(seg)
    if name in RECURSIVE_ALWAYS:
        recursive = True
    elif name in ("select-string", "sls"):
        recursive = any(a.lower() == "-recurse" for a in args)
    elif name == "findstr":
        recursive = any(a.lower() == "/s" for a in args)
    else:
        recursive = any(re.fullmatch(r"-[A-Za-z]*[rR][A-Za-z]*", a) or a in ("--recursive", "--dereference-recursive") for a in args)
    if not recursive:
        return None
    excludes: list[str] = []
    for i, a in enumerate(args):
        if a.startswith(("--exclude=", "--exclude-dir=", "--glob=!")):
            excludes.append(a.split("=", 1)[1].lstrip("!"))
        elif a in ("--exclude", "--exclude-dir") and i + 1 < len(args):
            excludes.append(args[i + 1])
        elif a in ("-g", "--glob") and i + 1 < len(args) and args[i + 1].startswith("!"):
            excludes.append(args[i + 1][1:])
    pos = [a for a in shell._positional(args) if not a.startswith("!")]
    pos = [a for a in pos if a not in excludes]
    if name in ("select-string", "sls"):
        operands = [v for f, v in zip(args, args[1:]) if f.lower() in ("-path", "-literalpath")]
    else:
        operands = pos[1:] if len(pos) > 1 else []
    if not operands:
        operands = ["."]
    base = Path(cwd) if cwd else root
    for operand in operands:
        folder = Path(operand) if (operand.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", operand)) else base / operand
        if not folder.is_dir():
            continue
        for rel in secret_files(folder, globs, root):
            base_name = rel.rsplit("/", 1)[-1]
            if not any(fnmatch.fnmatchcase(base_name, e) or fnmatch.fnmatchcase(rel, e) or e in rel.split("/") for e in excludes):
                return operand, rel
    return None


def decide(payload) -> dict:
    name = tool_name(payload)
    command = command_of(payload)
    cwd = payload.get("cwd") if isinstance(payload, dict) and isinstance(payload.get("cwd"), str) else None
    root = project_root(payload)
    candidates: list[str] = []
    searches = []
    if command:
        normal = textlib.normalize(command)
        candidates = shell.read_targets_of(normal) + shell.link_targets_of(normal)   # a link to a secret needs no later read
        flat = normal.lower()
        segs = shell.all_segments(normal)
        if (any(shell.command_name(s) in INTERPRETERS for s in segs) or "io.file]" in flat) and READ_WORDS.search(flat):
            for text in [flat] + [t.lower() for t in textlib.nested_texts(normal)]:
                candidates += [w for w in re.split(r"[\s'\"(),;=]+", text) if w]
        searches = segs
    elif name in ("Read", "NotebookRead"):
        candidates = [file_path_of(payload)]
    elif name in ("Grep", "Glob"):
        info = tool_input(payload)
        value = info.get("path")
        candidates = [value] if isinstance(value, str) else []
        glob = info.get("glob")
        if isinstance(glob, str) and glob:
            candidates.append(re.sub(r"^(\*\*/)+", "", glob.replace("\\", "/")))
    if not candidates and not searches:
        return allow()
    for r in candidate_roots(payload, candidates):
        globs = _globs(r)
        for token in candidates:
            for sp in spellings(token, r, cwd):
                glob = match(sp, globs)
                if glob:
                    return _deny(token, glob)
                if has_glob(sp):
                    found = _glob_target_hit(sp, r, globs)
                    if found:
                        return _deny(token, found[1])
        for seg in searches:
            hit = _recursive_search(seg, r, cwd, globs)
            if hit:
                return _deny(hit[0], f"{hit[1]} (a recursive search would read it; exclude it with --exclude or -g '!...')")
    return allow()
