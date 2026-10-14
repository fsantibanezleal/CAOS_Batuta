"""Area `leaks`: the public-hygiene scanner (`leaks scan`).

Scans the tracked files (and untracked files that are not ignored; every file when the folder is not a git
repository), and their NAMES, for: user paths (a drive-letter users folder, a POSIX home folder, a macOS users
folder, any case, JSON-escaped or not), e-mail addresses outside an allow-list, common token patterns (GitHub,
Anthropic, OpenAI, AWS, Slack, Google, PyPI, npm, Hugging Face, GitLab, private keys) and the terms of an optional
private deny-list file kept OUTSIDE the repository (never shipped). Exit 1 on any hit, printing `file:line` and the
kind of hit; a secret, a file name that is one, or a deny-list term is never echoed.

No file is skipped silently: UTF-16 files are decoded (byte order mark or the alternating NUL pattern), large files and
very long lines are read in overlapping chunks, and binary files are searched for token patterns.

E-mail allow-list: the built-in non-personal addresses, `leaks.allow_emails` in batuta.json, `--allow-email`, and the
contact addresses declared in SECURITY.md and CODE_OF_CONDUCT.md (published on purpose). Mark a line with
`batuta-leaks: ignore` to skip its path, e-mail and deny-list hits; the marker never hides a token hit. The deny-list
file comes from `--deny-list` or `BATUTA_LEAKS_DENY_LIST`.
"""
from __future__ import annotations

import argparse
import codecs
import fnmatch
import os
import re
import subprocess
from pathlib import Path

from batuta_lib.guards import guard_config, section, string_list
from batuta_lib.guards import text as textlib
from batuta_lib.output import emit, item

AREA = "leaks"
HELP = "Public hygiene: scan tracked files for user paths, e-mail addresses, tokens and private deny-list terms."

MARKER = "batuta-leaks: ignore"
ENV_DENY_LIST = "BATUTA_LEAKS_DENY_LIST"
CHUNK = 1024 * 1024
WINDOW = 8192          # no pattern ever sees more than this many characters at once
OVERLAP = 512          # long enough for any token, and shared by neighbouring windows and chunks
CARRY_MAX = 1_000_000  # a line longer than this is scanned in pieces
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
DECLARING_FILES = ("SECURITY.md", "CODE_OF_CONDUCT.md")
USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?P<n1>[A-Za-z0-9_.-]+)|/home/(?P<n2>[A-Za-z0-9_.-]+)|/Users/(?P<n3>[A-Za-z0-9_.-]+)",
                       re.IGNORECASE)
PLACEHOLDER_NAME = re.compile(r"[A-Za-z](\.[A-Za-z])?")      # a, a.b: an example name, not a person
LOCAL_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._%+-")
DOMAIN = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.([A-Za-z]{2,})")
EMAIL_SCAN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.([A-Za-z]{2,})")  # declared contacts (small files)
NOT_TLD = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ts", "json", "md", "py", "html", "txt", "yml", "yaml"}
DEFAULT_ALLOW_EMAILS = ["*@example.com", "*@example.org", "*@example.net", "*@users.noreply.github.com",
                        "noreply@anthropic.com", "noreply@github.com", "*.example", "*.invalid"]
TOKENS = [
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI key", re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{50,}")),
    ("AWS access key", re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])")),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("Slack token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("PyPI token", re.compile(r"pypi-[A-Za-z0-9_-]{50,}")),
    ("npm token", re.compile(r"npm_[A-Za-z0-9]{36}")),
    ("Hugging Face token", re.compile(r"hf_[A-Za-z0-9]{34,}")),
    ("GitLab token", re.compile(r"glpat-[A-Za-z0-9_-]{20,}")),
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
    """A small file as text (UTF-8 or UTF-16), None when it is binary or unreadable (used for the declaring files)."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    encoding = detect_encoding(data[:8192])
    if encoding == "binary":
        return None
    return data.decode(encoding, errors="replace")


def detect_encoding(head: bytes) -> str:
    """`utf-8-sig`, `utf-16`, `utf-16-le`, `utf-16-be` or `binary`, from the first bytes of a file."""
    if head.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    if b"\x00" in head:
        even, odd = head[0::2].count(0), head[1::2].count(0)
        half = max(len(head) // 2, 1)
        if odd >= 0.3 * half and even <= 0.05 * half:
            return "utf-16-le"
        if even >= 0.3 * half and odd <= 0.05 * half:
            return "utf-16-be"
        return "binary"
    return "utf-8-sig"


def declared_emails(root: Path) -> list[str]:
    found: list[str] = []
    for name in DECLARING_FILES:
        text = read_text(root / name)
        if text:
            found += [m.group(0).lower() for m in EMAIL_SCAN.finditer(text) if m.group(1).lower() not in NOT_TLD]
    return found


def load_deny_terms(path: Path) -> list[str]:
    terms = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = textlib.normalize(line).strip()
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


def emails_in(line: str):
    """Yield (address, tld) for the e-mail addresses in a line, found around each `@` (linear in the line length)."""
    start = 0
    while True:
        at = line.find("@", start)
        if at < 0:
            return
        start = at + 1
        i = at
        while i > 0 and line[i - 1] in LOCAL_CHARS and at - i < 64:
            i -= 1
        if i == at:
            continue
        m = DOMAIN.match(line, at + 1, min(len(line), at + 1 + 255))
        if m:
            yield line[i:m.end()], m.group(1)


def token_hit(line: str) -> str | None:
    for family, pattern in TOKENS:
        if pattern.search(line):
            return f"token pattern ({family})"
    return None


def scan_line(line: str, allow_emails: list[str], tokens_only: bool = False) -> list[str]:
    """The kinds of leak on one line (no secret text in the answer). Tokens always count; the marker skips the rest."""
    line = textlib.normalize(line)
    hits = []
    token = token_hit(line)
    if token:
        hits.append(token)
    if tokens_only or MARKER in line:
        return hits
    if any(not PLACEHOLDER_NAME.fullmatch(m.group("n1") or m.group("n2") or m.group("n3")) for m in USER_PATH.finditer(line)):
        hits.append("user path")
    for address, tld in emails_in(line):
        if tld.lower() in NOT_TLD:
            continue
        if not any(fnmatch.fnmatchcase(address.lower(), pat.lower()) for pat in allow_emails):
            hits.append("e-mail address")
            break
    return hits


def _windows(line_no: int, text: str):
    if len(text) <= WINDOW:
        yield line_no, text
        return
    step = WINDOW - OVERLAP
    for start in range(0, len(text), step):
        yield line_no, text[start:start + WINDOW]
        if start + WINDOW >= len(text):
            break


def iter_text(path: Path, encoding: str):
    """(line number, window of at most WINDOW characters) for a text file read in chunks; nothing is skipped."""
    try:
        with open(path, "rb") as handle:
            if encoding.startswith("utf-16"):
                text = handle.read().decode(encoding, errors="replace")
                for number, line in enumerate(text.splitlines(), 1):
                    yield from _windows(number, line)
                return
            decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="replace")
            buf, number = "", 1
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                buf += decoder.decode(chunk)
                parts = buf.split("\n")
                buf = parts.pop()
                for part in parts:
                    yield from _windows(number, part.rstrip("\r"))
                    number += 1
                if len(buf) > CARRY_MAX:        # a very long line: scan it now, keep the tail so a token across the cut is found
                    yield from _windows(number, buf)
                    buf = buf[-OVERLAP:]
            buf += decoder.decode(b"", final=True)
            if buf:
                yield from _windows(number, buf.rstrip("\r"))
    except OSError:
        return


def iter_binary(path: Path):
    """(offset, window) of a binary file read in overlapping chunks, decoded as ASCII with replacement characters (token patterns are ASCII)."""
    try:
        with open(path, "rb") as handle:
            offset, carry = 0, ""
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                text = carry + chunk.decode("ascii", errors="replace")
                base = offset - len(carry)
                for line_no, window in _windows(0, text):
                    yield base, window
                carry = text[-OVERLAP:]
                offset += len(chunk)
    except OSError:
        return


def scan(root: Path, deny_terms: list[str], allow_emails: list[str]) -> tuple[list[tuple[str, str, str]], int]:
    """((file, location, kind) hits without duplicates, number of files scanned)."""
    hits: list[tuple[str, str, str]] = []
    seen: set = set()

    def add(rel: str, where: str, kind: str) -> None:
        key = (rel, where, kind)
        if key not in seen:
            seen.add(key)
            hits.append(key)

    def deny_hits(line: str):
        if deny_terms and MARKER not in line:
            lowered = textlib.normalize(line).lower()
            for index, term in enumerate(deny_terms, 1):
                if term in lowered:
                    yield f"private deny-list term #{index}"
                    break

    files = candidate_files(root)
    for rel in files:
        hidden = rel.rsplit("/", 1)[0] + "/***" if "/" in rel else "***"   # a file name that is a secret is never printed
        for kind in scan_line(rel, allow_emails):
            add(hidden, "name", f"{kind} in a file name")
        for kind in deny_hits(rel):
            add(hidden, "name", f"{kind} in a file name")
        path = root / rel
        try:
            with open(path, "rb") as handle:
                head = handle.read(8192)
        except OSError:
            continue
        encoding = detect_encoding(head)
        if encoding == "binary":
            for offset, window in iter_binary(path):
                kind = token_hit(window)
                if kind:
                    add(rel, f"binary@{offset}", kind)
            continue
        for number, window in iter_text(path, encoding):
            for kind in scan_line(window, allow_emails):
                add(rel, str(number), kind)
            for kind in deny_hits(window):
                add(rel, str(number), kind)
    return hits, len(files)


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
    hits, count = scan(root, terms, allow)
    noun = "file" if count == 1 else "files"
    if not hits:
        return emit(AREA, "scan", [item("OK", "no user path, e-mail address, token or deny-list term found")],
                    f"leaks scan: clean ({count} {noun} scanned)", as_json)
    items = [item("FAIL", kind, f"{rel}:{where}") for rel, where, kind in hits]
    return emit(AREA, "scan", items, f"leaks scan: {len(hits)} hit(s) ({count} {noun} scanned)", as_json)


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
