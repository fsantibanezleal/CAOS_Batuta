"""Area `leaks`: the public-hygiene scanner (`leaks scan`).

Scans the tracked files (and untracked files that are not ignored; every file when the folder is not a git
repository) for: user paths (a drive-letter users folder, a POSIX home folder, a macOS users folder), e-mail
addresses outside an allow-list, common token patterns (GitHub, Anthropic, OpenAI, AWS, Slack, Google, private keys)
and the terms of an optional private deny-list file kept OUTSIDE the repository (never shipped). Exit 1 on any hit,
printing `file:line` and the kind of hit; a secret or a deny-list term is never echoed.

E-mail allow-list: the built-in non-personal addresses, `leaks.allow_emails` in batuta.json, `--allow-email`, and the
contact addresses declared in SECURITY.md and CODE_OF_CONDUCT.md (published on purpose). Mark a line with
`batuta-leaks: ignore` to skip it. The deny-list file comes from `--deny-list` or `BATUTA_LEAKS_DENY_LIST`.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
from pathlib import Path

from batuta_lib.guards import guard_config, section, string_list
from batuta_lib.output import emit, item

AREA = "leaks"
HELP = "Public hygiene: scan tracked files for user paths, e-mail addresses, tokens and private deny-list terms."

MARKER = "batuta-leaks: ignore"
ENV_DENY_LIST = "BATUTA_LEAKS_DENY_LIST"
MAX_BYTES = 2_000_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
DECLARING_FILES = ("SECURITY.md", "CODE_OF_CONDUCT.md")
USER_PATH = re.compile(r"[A-Za-z]:[\\/]Users[\\/]|/home/[A-Za-z0-9_.-]+/|/Users/[A-Za-z0-9_.-]+/")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.([A-Za-z]{2,})")
NOT_TLD = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ts", "json", "md", "py", "html", "txt", "yml", "yaml"}
DEFAULT_ALLOW_EMAILS = ["*@example.com", "*@example.org", "*@example.net", "*@users.noreply.github.com",
                        "noreply@anthropic.com", "noreply@github.com", "*.example", "*.invalid"]
TOKENS = [
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
]


def _git(root: Path, *args: str):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _toplevel(root: Path) -> Path | None:
    proc = _git(root, "rev-parse", "--show-toplevel")
    return Path(proc.stdout.strip()).resolve() if proc.returncode == 0 and proc.stdout.strip() else None


def candidate_files(root: Path) -> list[str]:
    """Repository-relative POSIX paths: tracked plus untracked-not-ignored in a git repository, else every file."""
    if _toplevel(root) is not None:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                              capture_output=True)
        if proc.returncode == 0:
            names = [n.decode("utf-8", errors="replace") for n in proc.stdout.split(b"\0") if n]
            return sorted(set(names))
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            found.append((Path(folder) / name).relative_to(root).as_posix())
    return sorted(found)


def read_text(path: Path) -> str | None:
    """The file as text, None for a binary or oversize file."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8000]:
        return None
    return data.decode("utf-8", errors="replace")


def declared_emails(root: Path) -> list[str]:
    found: list[str] = []
    for name in DECLARING_FILES:
        text = read_text(root / name)
        if text:
            found += [m.group(0).lower() for m in EMAIL.finditer(text) if m.group(1).lower() not in NOT_TLD]
    return found


def load_deny_terms(path: Path) -> list[str]:
    terms = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line.lower())
    return terms


def deny_list_problem(path: Path, root: Path) -> tuple[str, str] | None:
    """Why this deny-list file cannot be used: it must exist and sit outside the repository."""
    resolved = path.resolve()
    folders = {root.resolve()}
    top = _toplevel(root)
    if top is not None:
        folders.add(top)
    for folder in folders:
        if resolved == folder or folder in resolved.parents:
            return "REFUSED", "the private deny-list must live outside the repository (it is never shipped)"
    if not path.is_file():
        return "FAIL", f"deny-list file not found: {path.as_posix()}"
    return None


def scan_line(line: str, allow_emails: list[str]) -> list[str]:
    """The kinds of leak on one line (no secret text in the answer)."""
    if MARKER in line:
        return []
    hits = []
    for family, pattern in TOKENS:
        if pattern.search(line):
            hits.append(f"token pattern ({family})")
            break
    if USER_PATH.search(line):
        hits.append("user path")
    for match in EMAIL.finditer(line):
        address = match.group(0).lower()
        if match.group(1).lower() in NOT_TLD:
            continue
        if not any(fnmatch.fnmatchcase(address, pat.lower()) for pat in allow_emails):
            hits.append("e-mail address")
            break
    return hits


def scan(root: Path, deny_terms: list[str], allow_emails: list[str]) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for rel in candidate_files(root):
        text = read_text(root / rel)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for kind in scan_line(line, allow_emails):
                hits.append((rel, number, kind))
            if deny_terms and MARKER not in line:
                lowered = line.lower()
                for index, term in enumerate(deny_terms, 1):
                    if term in lowered:
                        hits.append((rel, number, f"private deny-list term #{index}"))
                        break
    return hits


def _scan(args) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
    as_json = bool(getattr(args, "json", False))
    deny_path = args.deny_list or os.environ.get(ENV_DENY_LIST)
    terms: list[str] = []
    if deny_path:
        problem = deny_list_problem(Path(deny_path), root)
        if problem:
            return emit(AREA, "scan", [item(problem[0], problem[1])], "leaks scan: deny-list unusable", as_json)
        terms = load_deny_terms(Path(deny_path))
    cfg_allow = string_list(section(guard_config(root), "leaks").get("allow_emails"))
    allow = DEFAULT_ALLOW_EMAILS + declared_emails(root) + cfg_allow + list(args.allow_email or [])
    hits = scan(root, terms, allow)
    if not hits:
        return emit(AREA, "scan", [item("OK", "no user path, e-mail address, token or deny-list term found")],
                    "leaks scan: clean", as_json)
    items = [item("FAIL", kind, f"{rel}:{number}") for rel, number, kind in hits]
    return emit(AREA, "scan", items, f"leaks scan: {len(hits)} hit(s)", as_json)


def register(subparsers) -> None:
    parser = subparsers.add_parser("scan", help="scan the tracked files for leaks")
    parser.add_argument("--root", metavar="DIR", help="repository folder (default: the current folder)")
    parser.add_argument("--deny-list", metavar="FILE", help="private deny-list file kept outside the repository")
    parser.add_argument("--allow-email", metavar="PATTERN", action="append", help="allowed address or glob (repeatable)")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    parser.set_defaults(func=_scan)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="leaks")
    parser.add_argument("--json", action="store_true")
    register(parser.add_subparsers(dest="verb", required=True))
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)
