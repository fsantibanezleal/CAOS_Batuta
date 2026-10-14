"""The test lock (C07) and the test change requests (C33) as files: reading, validating and appending.

The lock is one JSON file, append-only: an entry is never edited or removed, a changed test is locked again by a
superseding entry that names the approved change request. A change request is a row of
`specs/<feature>/test-change-requests.md`; only a row with Status `approved` and a named decider authorises a change.
"""
import datetime
import json
import os
import re
import tempfile
import time
from pathlib import Path

from batuta_lib import config
from batuta_lib import contract as core

DEFAULT_LOCK = ".batuta/test-locks.json"   # the path the contract catalog names for C07
REQUEST_FILE = "test-change-requests.md"
HEADERS = ["Id", "Date", "Test path", "Requirement", "Reason", "Proposed change", "Status", "Decided by"]
REPLACE_ATTEMPTS = 6
REPLACE_PAUSE = 0.2
TASK_ID =re.compile(r"T-\d{3}\Z", re.ASCII)
REQ_ID = re.compile(r"REQ-[A-Z0-9]+-\d{3}\Z", re.ASCII)
FEATURE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z", re.ASCII)
_REL = core.compile_pattern(core.REL_PATH_PATTERN)


def schema(contract_id):
    return core.load_schema(core.find_schema(config.contracts_dir(), contract_id))


def bad_relpath(path):
    """The reason a path is not a POSIX path relative to the repository root, or None."""
    if not isinstance(path, str) or not _REL.search(path):
        return (f"{path!r} is not a POSIX path relative to the repository root "
                f"(no leading slash, drive letter, backslash, '.' or '..' segment)")
    return None


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


# ------------------------------------------------------------------ the lock file


def parse_lock(text):
    """(entries, None) for a sound lock, (None, None) when there is no file, (None, reason) when it is unusable."""
    if text is None:
        return None, None
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig", "replace")
    try:
        doc = core.loads_strict(text)
    except ValueError as exc:
        return None, f"invalid JSON ({exc})"
    errors = core.validate_instance("C07", doc, schema("C07"))
    if errors:
        return None, "does not satisfy C07: " + "; ".join(errors[:3])
    return doc["entries"], None


def live_entries(entries):
    """The newest entry of each path: {path: entry}."""
    return {e["path"]: e for e in entries}


def dump_lock(entries):
    return json.dumps({"contract_version": "1.0", "entries": entries}, indent=2) + "\n"


def atomic_write(path, text):
    """UTF-8, LF; a temp file in the same folder and then `os.replace`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Windows refuses a replace for a moment while a scanner or indexer holds the file
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_PAUSE * (attempt + 1))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ------------------------------------------------------------------ change requests


def parse_requests(text):
    """(rows as dicts, []) for a request file that satisfies C33, else ([], problems)."""
    sp = core.find_schema(config.contracts_dir(), "C33")
    spec = core.load_sections_spec(sp)
    problems = core.validate_markdown(text, core.load_schema(sp), spec)
    if problems:
        return [], problems
    rows, _ = core.read_table(text, spec["tables"][0])
    return rows, []


def is_decided(row):
    return str(row.get("Decided by", "")).strip() not in ("", "-")


def authorises(row, test_paths):
    """Why a request does not authorise a change of one of `test_paths`, or None when it does."""
    if row.get("Status") != "approved":
        return f"request {row.get('Id')} is {row.get('Status')}, not approved"
    if not is_decided(row):
        return f"request {row.get('Id')} names nobody in Decided by"
    if row.get("Test path") not in test_paths:
        return f"request {row.get('Id')} is for Test path {row.get('Test path')}, not {' or '.join(sorted(test_paths))}"
    return None


def request_paths(root):
    """Relative POSIX paths of the request files in a working tree."""
    base = Path(root) / "specs"
    if not base.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in base.rglob(REQUEST_FILE) if p.is_file())


def index_requests(texts):
    """From {file path: text}: ({id: [(row, file)]}, {file: problems}). A file that breaks C33 contributes no rows."""
    rows_by_id, problems = {}, {}
    for path, text in texts.items():
        rows, errors = parse_requests(text)
        if errors:
            problems[path] = errors
            continue
        for row in rows:
            rows_by_id.setdefault(row["Id"], []).append((row, path))
    return rows_by_id, problems


def load_requests(root):
    texts = {p: (Path(root) / p).read_text(encoding="utf-8-sig") for p in request_paths(root)}
    return index_requests(texts)


def lookup(rows_by_id, problems, request_id, test_paths):
    """(row, file, None) when the request authorises a change of one of `test_paths`, else (None, None, reason)."""
    found = rows_by_id.get(request_id, [])
    if len(found) > 1:
        return None, None, f"request {request_id} is defined more than once"
    if not found:
        broken = "; ".join(f"{p}: {e[0]}" for p, e in sorted(problems.items()))
        extra = f" (a request file breaks C33: {broken})" if broken else ""
        return None, None, f"no request {request_id} in specs/**/{REQUEST_FILE}{extra}"
    row, path = found[0]
    why = authorises(row, test_paths)
    return (None, None, why) if why else (row, path, None)


def next_request_id(texts):
    """CR-NNN, one above the highest in any request file (an id is unique across features: it is the commit trailer)."""
    numbers = [int(n) for text in texts for n in re.findall(r"^\|\s*CR-(\d+)\s*\|", text, re.MULTILINE | re.ASCII)]
    return f"CR-{max(numbers, default=0) + 1:03d}"


def _cell(text):
    return " ".join(str(text).split()).replace("|", "\\|")


def request_row(rid, test_path, requirement, reason, proposed, date):
    cells = [rid, date, test_path, requirement, reason, proposed, "open", ""]
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def decide_text(text, request_id, status, decided_by):
    """The request file text with the Status and Decided by cells of one row set. Raises ValueError when no row has the id."""
    lines, done = text.replace("\r\n", "\n").split("\n"), False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        body = stripped[1:-1] if stripped.endswith("|") and not stripped.endswith("\\|") else stripped[1:]
        cells = re.split(r"(?<!\\)\|", body)
        if len(cells) >= len(HEADERS) and cells[0].strip() == request_id:
            cells[HEADERS.index("Status")] = f" {status} "
            cells[HEADERS.index("Decided by")] = f" {_cell(decided_by)} "
            lines[i] = "|" + "|".join(cells) + "|"
            done = True
            break
    if not done:
        raise ValueError(f"no row {request_id} in the request file")
    return "\n".join(lines)


def append_request(existing, row, feature):
    """The request file text with `row` added. `existing` is None for a new file."""
    if existing is None:
        title = f"# Test change requests: {feature}"
        return (f"{title}\n\n| " + " | ".join(HEADERS) + " |\n|" + "---|" * len(HEADERS) + f"\n{row}\n")
    lines = existing.replace("\r\n", "\n").rstrip("\n").split("\n")
    if not lines or not lines[-1].lstrip().startswith("|"):
        raise ValueError("the last line of the request file is not a table row; add the row by hand")
    return "\n".join(lines + [row]) + "\n"
