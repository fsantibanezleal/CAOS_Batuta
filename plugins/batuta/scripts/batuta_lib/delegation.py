"""Delegation core shared by the `route`, `brief` and `report` areas: roles and kinds, the brief template, the brief
lint, Markdown section helpers and the delegation ledger (C04).

A brief is written from `templates/brief.md` and listed in the ledger `<coordination_root>/delegation/ledger.md`, one
Markdown table per coordination root (no JSONL). The ledger functions work on text and keep every byte they do not
change: the optional columns, the free-text Notes, the `y` and `n` aliases of Accepted and the line endings of the file.
`update_ledger` is the only writer: it takes a lock file, writes the whole new file to a temp file in the same folder,
re-reads the ledger just before the replace so a row a concurrent writer added in between is kept, and refuses a result
that does not satisfy C04. The lint applies the C02 contract and the rules a schema cannot hold (escalation, the model
that must not be used unless asked for, overlapping write scopes, a long deliverable list, unfilled template slots).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from batuta_lib import config
from batuta_lib import contract
from batuta_lib import projectroot

MODELS = ("haiku", "sonnet", "opus", "fable")
# The default kind of the roles that ship; an agent file with no entry here needs --kind.
DEFAULT_KINDS = {"searcher": "lookup", "runner": "run", "implementer": "implement", "test-author": "implement",
                 "doc-writer": "docs", "adversary": "review", "reviewer": "review"}
AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"


def _shipped_agents(agents_dir=None):
    """agent -> (pinned model, default kind or None), read from the agent files of the plugin (the `model` line of each);
    general-purpose (primary-source research) has no pinned model."""
    found = {}
    folder = Path(agents_dir) if agents_dir else AGENTS_DIR
    for path in sorted(folder.glob("*.md")):
        m = re.search(r"^model:\s*(\S+)\s*$", path.read_text(encoding="utf-8-sig").split("\n---", 1)[0], re.M)
        found[path.stem] = (m.group(1) if m else None, DEFAULT_KINDS.get(path.stem))
    found["general-purpose"] = (None, "research")
    return found


AGENTS = _shipped_agents()
KINDS = ("implement", "job", "skeleton", "docs", "review", "research", "lookup", "run")
CPD_KINDS = ("implement", "job", "skeleton")   # the kinds whose briefs carry the contract-first sections
SPEC_KINDS = ("implement", "job", "skeleton", "docs")   # the kinds whose briefs need Definitions and Spec
CPD_SECTIONS = ("adr constraints", "sizing reference", "contracts", "invariants and edge cases", "missing-data behavior",
                "environment and limits", "owner prerequisites", "shared files", "must refute", "production-path check")
MAX_DELIVERABLES = 8
LEDGER_COLUMNS = ("ID", "Agent", "Model", "Brief", "Report", "Status", "Accepted")
OPTIONAL_COLUMNS = ("Provider", "Tokens in", "Tokens out", "Cost USD", "Superseded by", "Notes")
OPEN_STATUSES = ("drafted", "pending", "launched")   # a brief still being worked on: its write scope is taken
SLOT = re.compile(r"<fill\b[^>]*>", re.IGNORECASE)
PLUGIN_ROOT = Path(__file__).resolve().parents[2]    # plugins/batuta
LOCK_TIMEOUT_SECONDS = 30.0
LOCK_STALE_SECONDS = 120.0

_BLOCK = re.compile(r"\{\{([#^])(\w+)\}\}\n?(.*?)\{\{/\2\}\}\n?", re.DOTALL)
_VAR = re.compile(r"\{\{(\w+)\}\}")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_DELIVERABLE = re.compile(r"^\s*(?:[-*+]|\d+[.)])?\s*\**\s*(D\d+)\b")
_HEADER_FIELD = re.compile(r"^\s*[-*]\s*([A-Za-z][A-Za-z ]*?)\s*:\s*(.+?)\s*$")
_EOL = re.compile(r"(\r\n|\n)")
_TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# every character str.splitlines treats as a line boundary: none may reach a header line or a one-line state entry
LINE_BOUNDARY = re.compile("[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]")
_FENCE_LINE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_BACKTICKED = re.compile(r"`[^`\n]+`")


class DelegationError(ValueError):
    """A delegation operation cannot be done; the message says why."""


class LedgerError(DelegationError):
    """The ledger would not satisfy C04 after the change, or cannot be written."""


class LedgerLockError(LedgerError):
    """The ledger lock stayed taken by another writer (not a C04 problem)."""


# ------------------------------------------------------------------ configuration and paths


def project_config(args):
    """(project root, resolved configuration, warning lines) for a verb with a `--root` option and the global `--config`.

    A missing configuration file is not an error: the C01 defaults apply and the caller prints the warning."""
    root = Path(getattr(args, "root", None) or ".").resolve()
    resolved = config.load(getattr(args, "config", None), project_root=root)
    warnings = []
    if resolved.source == "defaults":
        warnings.append("WARN no batuta.json found; using the built-in defaults of C01")
    return root, resolved, warnings


def find_project_root(cwd):
    """The nearest folder at or above `cwd` that holds `.batuta/` (the user's own Batuta home does not count) or `.git`,
    else `cwd` itself."""
    start = Path(cwd).resolve()
    try:
        home = config.home_dir().resolve()
    except OSError:
        home = None

    def holds_root(folder):
        marker = folder / config.PROJECT_DIR
        if (marker / config.FILE_NAME).is_file():
            return True
        if marker.is_dir() and (home is None or marker.resolve() != home):
            return True
        return (folder / ".git").exists()

    found = projectroot.find(start, holds_root)
    return found if found is not None else start


def unlisted_briefs(folder):
    """Names of the `*.brief.md` files in a delegation folder that have no row in its ledger (empty without a ledger)."""
    folder = Path(folder)
    ledger = folder / "ledger.md"
    if not ledger.is_file():
        return []
    try:
        listed = {Path(r["Brief"].replace("\\", "/")).name for r in ledger_rows(read_text(ledger))[1]}
    except OSError:
        return []
    return sorted(p.name for p in folder.glob("*.brief.md") if p.name not in listed)


def delegation_dir(root, cfg):
    return Path(root) / cfg.get("coordination_root", config.PROJECT_DIR) / "delegation"


def template_path():
    return PLUGIN_ROOT / "templates" / "brief.md"


def batuta_script():
    return Path(__file__).resolve().parents[1] / "batuta.py"


# ------------------------------------------------------------------ the brief template


def render(template, values):
    """Fill `{{key}}` in one pass; `{{#key}}..{{/key}}` is kept when the value is non-empty, `{{^key}}..{{/key}}` when empty."""
    def block(match):
        wanted = match.group(1) == "#"
        return match.group(3) if bool(values.get(match.group(2))) == wanted else ""

    text = _BLOCK.sub(block, template)
    return _VAR.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)


def render_template(kind, values):
    """The brief text for a kind. Missing runtime values (python, batuta, temp_root) get their defaults."""
    vals = dict(values)
    vals["kind"] = kind
    vals["cpd"] = "yes" if kind in CPD_KINDS else ""
    vals.setdefault("python", Path(sys.executable).as_posix())
    vals.setdefault("batuta", batuta_script().as_posix())
    vals.setdefault("temp_root", "<temp root>")
    return render(template_path().read_text(encoding="utf-8"), vals)


# ------------------------------------------------------------------ Markdown helpers


def sections(text, keep_fences=False):
    """Map each lower-cased heading title to the lines under it (until the next heading of any level).

    Lines inside fenced code blocks are dropped: an example table quoted in a fence is not the document's own structure.
    `keep_fences` keeps them, for sections whose evidence is a quoted command and its output."""
    found = {}
    current = None
    fence = None   # (character, length) of the open fence: ``` or ~~~, three or more, closed by the same character
    for line in text.lstrip("\ufeff").splitlines():
        marker = _FENCE_LINE.match(line)
        if fence is None and marker:
            fence = (marker.group(1)[0], len(marker.group(1)))
            if keep_fences and current is not None:
                current.append(line)
            continue
        if fence is not None:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= fence[1] and not marker.group(2).strip():
                fence = None
            if keep_fences and current is not None:
                current.append(line)
            continue
        match = _HEADING.match(line)
        if match:
            current = found.setdefault(match.group(2).strip().lower(), [])
            continue
        if current is not None:
            current.append(line)
    return found


def find_section(found, name):
    """The lines of the first section whose title starts with `name` (lower case), or None."""
    for title, lines in found.items():
        if title.startswith(name):
            return lines
    return None


def header_fields(text):
    """The `- key: value` bullets before the first `##` heading, keys lower-cased."""
    out = {}
    for line in text.lstrip("﻿").splitlines():
        if line.startswith("## "):
            break
        match = _HEADER_FIELD.match(line)
        if match:
            out.setdefault(" ".join(match.group(1).lower().split()), match.group(2).strip().strip("` "))
    return out


def deliverable_ids(text):
    """The ordered deliverable ids D1..Dn of a brief's Deliverables section."""
    lines = find_section(sections(text), "deliverables")
    if lines is None:
        raise DelegationError("brief has no '## Deliverables' section")
    ids = []
    for line in lines:
        match = _DELIVERABLE.match(line)
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
    if not ids:
        raise DelegationError("brief lists no deliverables (expected lines starting with D1, D2, ...)")
    return ids


# ------------------------------------------------------------------ the lint


def scope_paths(value):
    """The paths of a `write scope` field: comma or semicolon separated, notes in parentheses dropped, `read-only` none."""
    paths = []
    for part in re.split(r"[,;]", re.sub(r"\([^)]*\)", "", value)):
        part = part.strip().strip("`").strip().replace("\\", "/")
        if part.startswith("./"):
            part = part[2:]
        if part and part.lower() != "read-only" and ("/" in part or "." in part):
            paths.append(part)
    return paths


def _overlap(a, b):
    """The same path, one directory above the other, or two globs that meet."""
    a, b = a.rstrip("/"), b.rstrip("/")
    if a == b or b.startswith(a + "/") or a.startswith(b + "/"):
        return True
    if any(ch in a + b for ch in "*?["):
        return contract.scopes_overlap(a, b) or contract.scopes_overlap(a + "/", b + "/")
    return False


def shared_scopes(text, siblings):
    """Warnings for write-scope paths this brief shares with the open sibling briefs (id -> text) of its ledger."""
    header = header_fields(text)
    mine = scope_paths(header.get("write scope", ""))
    out = []
    for ident, other in siblings.items():
        if ident == header.get("id", ""):
            continue
        for path in mine:
            for theirs in scope_paths(header_fields(other).get("write scope", "")):
                if _overlap(path, theirs):
                    out.append(f"write scope path {path} overlaps {theirs} of brief {ident} in the same ledger")
    return out


def _check_items(lines):
    """The items of a Checks list as (id or start of text, text), continuation lines joined to their item."""
    items = []
    for line in lines:
        match = _ITEM.match(line)
        if match:
            items.append([match.group(1)])
        elif items and line.strip():
            items[-1].append(line.strip())
    out = []
    for parts in items:
        body = " ".join(parts)
        ident = re.match(r"\**(C\d+)\b", body)
        out.append((ident.group(1) if ident else body[:30], body))
    return out


def structure_errors(text, kind, existing):
    """Required sections, deliverables and check commands counted outside code fences only (a fenced example is not the
    document's own structure). A problem the C02 messages in `existing` already name is not repeated."""
    found = sections(text)
    required = ["goal", "context and background", "out of scope", "checks", "deliverables"]
    if kind in SPEC_KINDS:
        required += ["definitions", "spec"]
    if kind in CPD_KINDS:
        required += list(CPD_SECTIONS)
    known = " ".join(existing).lower()
    out = []
    for name in required:
        body = find_section(found, name)
        if (body is None or not "".join(body).strip()) and name not in known:
            out.append(f"section '{name}' is missing or empty outside code fences")
    if find_section(found, "deliverables") is not None or "deliverable" not in known:
        try:
            deliverable_ids(text)
        except DelegationError as exc:
            if "deliverable" not in known:
                out.append(str(exc))
    if kind in CPD_KINDS:
        for ident, body in _check_items(find_section(found, "checks") or []):
            if not _BACKTICKED.search(body) and body[:25] not in " ".join(existing):
                out.append(f"check {ident} has no backticked command (each check is a command with its expected result)")
    return out


def lint_brief(text, siblings=None):
    """(errors, warnings) of a brief: the C02 contract, unfilled template slots and the rules a schema cannot hold."""
    errors, warnings = [], []
    slots = SLOT.findall(text)
    if slots:
        errors.append(f"{len(slots)} template slot(s) not filled, first: {slots[0][:70]}")
    schema_path = contract.find_schema(config.contracts_dir(), "C02")
    errors.extend(contract.validate_markdown(text, contract.load_schema(schema_path), contract.load_sections_spec(schema_path)))
    header = header_fields(text)
    errors.extend(structure_errors(text, header.get("kind", ""), errors))
    agent = header.get("agent", "")
    model = header.get("model", "").split()[0].lower() if header.get("model") else ""
    if model == "fable":
        warnings.append("fable is not used unless the owner asks for it")
    pinned = AGENTS.get(agent, (None, None))[0]
    if pinned and model in MODELS and model != pinned:
        warnings.append(f"{agent} is pinned to {pinned}; the model line must say why {model} (escalation)")
    try:
        ids = deliverable_ids(text)
    except DelegationError:
        ids = []   # C02 already reports the missing deliverables
    if len(ids) > MAX_DELIVERABLES:
        warnings.append(f"{len(ids)} deliverables: more than {MAX_DELIVERABLES} usually means the brief should be split")
    if siblings:
        warnings.extend(shared_scopes(text, siblings))
    return errors, warnings


def open_siblings(folder, own_id=None):
    """The open briefs (status drafted, pending or launched) of the ledger in `folder`, as id -> text."""
    folder = Path(folder)
    ledger = folder / "ledger.md"
    if not ledger.is_file():
        return {}
    try:
        _cols, rows = ledger_rows(read_text(ledger))
    except OSError:
        return {}
    out = {}
    for row in rows:
        if row["ID"] == own_id or row["Status"] not in OPEN_STATUSES:
            continue
        path = folder / Path(row["Brief"].replace("\\", "/")).name
        try:
            out[row["ID"]] = read_text(path)
        except OSError:
            continue
    return out


# ------------------------------------------------------------------ the ledger (C04)


def read_text(path):
    """A file as text with its line endings and any BOM untouched."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _lines(text):
    """[(content, eol)] where eol is '\\r\\n', '\\n' or '' (the last line without a final newline)."""
    parts = _EOL.split(text)
    out = []
    for i in range(0, len(parts), 2):
        out.append((parts[i], parts[i + 1] if i + 1 < len(parts) else ""))
    if out and out[-1] == ("", ""):
        out.pop()
    return out


def _spans(content):
    """(start, end) of the cell text between the unescaped pipes of a table line."""
    pipes = [m.start() for m in re.finditer(r"(?<!\\)\|", content)]
    if not pipes:
        return []
    spans = []
    for a, b in zip(pipes, pipes[1:]):
        spans.append((a + 1, b))
    tail = content[pipes[-1] + 1:]
    if tail.strip():
        spans.append((pipes[-1] + 1, len(content)))
    return spans


def _canonical(name):
    norm = " ".join(name.lower().split())
    for known in LEDGER_COLUMNS + OPTIONAL_COLUMNS:
        if known.lower() == norm:
            return known
    return name.strip()


def _find_table(lines):
    """(header index, separator index, last row index) of the first table, or None."""
    for i in range(len(lines) - 1):
        a, b = lines[i][0].lstrip(), lines[i + 1][0].strip()
        if a.startswith("|") and b.startswith("|") and re.fullmatch(r"\|?[\s:|-]+\|?", b) and "-" in b:
            last = i + 1
            while last + 1 < len(lines) and lines[last + 1][0].lstrip().startswith("|"):
                last += 1
            return i, i + 1, last
    return None


def ledger_rows(text):
    """(column names, rows) of the ledger table. Each row is a dict column -> text, plus `_line`, its line index.

    A text without a table gives ([], [])."""
    lines = _lines(text.lstrip("﻿") if text.startswith("﻿") else text)
    found = _find_table(lines)
    if found is None:
        return [], []
    head, sep, last = found
    columns = [_canonical(lines[head][0][s:e]) for s, e in _spans(lines[head][0])]
    rows = []
    for n in range(sep + 1, last + 1):
        cells = [lines[n][0][s:e].strip() for s, e in _spans(lines[n][0])]
        if not any(cells):
            continue
        row = dict(zip(columns, cells))
        row["_line"] = n
        rows.append(row)
    return columns, rows


def ledger_render(text):
    """The ledger as text again: every byte kept (the parse is lossless)."""
    return "".join(content + eol for content, eol in _lines(text))


def accepted_value(cell):
    """yes or no for the cell of the Accepted column (`y` and `n` in any case are aliases, never written), else None."""
    return {"y": "yes", "yes": "yes", "n": "no", "no": "no"}.get(cell.strip().strip("`").lower())


def ledger_problems(text):
    """The C04 problems of a ledger text (empty when it satisfies the contract)."""
    schema_path = contract.find_schema(config.contracts_dir(), "C04")
    return contract.validate_markdown(text.lstrip("﻿"), contract.load_schema(schema_path), contract.load_sections_spec(schema_path))


def _eol_of(lines, default="\n"):
    for _content, eol in lines:
        if eol:
            return eol
    return default


def _row_line(columns, values):
    return "| " + " | ".join(str(values.get(c, "")) for c in columns) + " |"


def ledger_add_row(text, values, title=None):
    """The ledger text with one row added after the last row of the table (every column of the existing header filled,
    the optional ones empty). A text without a table gets the C04 header first."""
    lines = _lines(text)
    found = _find_table(lines)
    if found is None:
        eol = _eol_of(lines)
        head = "| " + " | ".join(LEDGER_COLUMNS) + " |"
        sep = "|" + "|".join("---" for _ in LEDGER_COLUMNS) + "|"
        block = [(head, eol), (sep, eol), (_row_line(LEDGER_COLUMNS, values), eol)]
        if not lines:
            prefix = [(f"# Delegation ledger: {title}" if title else "# Delegation ledger", eol), ("", eol)]
            return "".join(c + e for c, e in prefix + block)
        if lines[-1][1] == "":
            lines[-1] = (lines[-1][0], eol)
        return "".join(c + e for c, e in lines + [("", eol)] + block)
    _head, _sep, last = found
    columns = [_canonical(lines[_head][0][s:e]) for s, e in _spans(lines[_head][0])]
    eol = _eol_of(lines)
    content, line_eol = lines[last]
    lines[last] = (content, line_eol or eol)
    lines.insert(last + 1, (_row_line(columns, values), line_eol or eol))
    return "".join(c + e for c, e in lines)


def ledger_set_status(text, row_id, status):
    """The ledger text with the Status cell of one row replaced; everything else byte for byte. KeyError for an unknown id."""
    lines = _lines(text)
    found = _find_table(lines)
    if found is None:
        raise KeyError(row_id)
    head, sep, last = found
    columns = [_canonical(lines[head][0][s:e]) for s, e in _spans(lines[head][0])]
    if "ID" not in columns or "Status" not in columns:
        raise KeyError(row_id)
    id_at, status_at = columns.index("ID"), columns.index("Status")
    for n in range(sep + 1, last + 1):
        content, eol = lines[n]
        spans = _spans(content)
        if len(spans) <= max(id_at, status_at) or content[spans[id_at][0]:spans[id_at][1]].strip() != row_id:
            continue
        a, b = spans[status_at]
        raw = content[a:b]
        if raw.strip() == status:
            return text
        lead = raw[:len(raw) - len(raw.lstrip())] or " "
        trail = raw[len(raw.rstrip()):] or " "
        lines[n] = (content[:a] + lead + status + trail + content[b:], eol)
        return "".join(c + e for c, e in lines)
    raise KeyError(row_id)


def _cell_text(value):
    return " ".join(str(value).replace("|", "\\|").split())


def _ensure_pipe(content):
    return content if content.rstrip().endswith("|") else content.rstrip() + " |"


def ledger_set_cells(text, row_id, values):
    """The ledger text with the cells `values` (column name -> value) of the row `row_id` set; every other byte as it was.

    A column the header lacks (the optional ones: Provider, Tokens in, Tokens out, Cost USD, Notes) is appended to the header,
    the separator and every row. A pipe or a line break inside a value cannot break the row. KeyError for an unknown id or a
    text without a table. Applied through `update_ledger`, the only writer."""
    lines = _lines(text)
    found = _find_table(lines)
    if found is None:
        raise KeyError(row_id)
    head, sep, last = found
    columns = [_canonical(lines[head][0][s:e]) for s, e in _spans(lines[head][0])]
    if "ID" not in columns:
        raise KeyError(row_id)
    id_at = columns.index("ID")
    target = None
    for n in range(sep + 1, last + 1):
        spans = _spans(lines[n][0])
        if len(spans) > id_at and lines[n][0][spans[id_at][0]:spans[id_at][1]].strip() == row_id:
            target = n
            break
    if target is None:
        raise KeyError(row_id)
    missing = [c for c in values if c not in columns]
    if missing:
        for n in range(head, last + 1):
            content, eol = lines[n]
            if n == head:
                content = _ensure_pipe(content) + "".join(f" {c} |" for c in missing)
            elif n == sep:
                content = _ensure_pipe(content) + "---|" * len(missing)
            else:
                content = _ensure_pipe(content) + " |" * len(missing)
            lines[n] = (content, eol)
        columns += missing
    content, eol = lines[target]
    content = _ensure_pipe(content)
    while len(_spans(content)) < len(columns):
        content += " |"
    for name, value in values.items():
        a, b = _spans(content)[columns.index(name)]
        if content[a:b].strip() == _cell_text(value):
            continue
        content = content[:a] + " " + _cell_text(value) + " " + content[b:]
    lines[target] = (content, eol)
    return "".join(c + e for c, e in lines)


class _Lock:
    """A lock file next to the ledger (created exclusively); a lock older than LOCK_STALE_SECONDS is a crashed writer's."""

    def __init__(self, path):
        self.path = Path(str(path) + ".lock")
        self.held = False

    def __enter__(self):
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.held = True
                return self
            except (FileExistsError, PermissionError):   # PermissionError: the other writer's delete is still pending (Windows)
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_SECONDS:
                        self.path.unlink()
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise LedgerLockError(f"the ledger lock {self.path.name} stayed taken for {int(LOCK_TIMEOUT_SECONDS)} s")
                time.sleep(0.01)

    def __exit__(self, *_exc):
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass


def _read_retry(path):
    """The ledger text, or "" when there is none; a read that collides with a replace (Windows) is tried again."""
    for attempt in range(40):
        try:
            return read_text(path) if Path(path).is_file() else ""
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.05)


def _replace(src, dst):
    for attempt in range(40):
        try:
            os.replace(src, dst)
            return
        except PermissionError:   # a reader holds the file open for a moment (Windows)
            if attempt == 39:
                raise
            time.sleep(0.05)


def update_ledger(path, mutate, before_replace=None, _locked=False):
    """Apply `mutate(text) -> text` to the ledger file atomically and return the new text.

    The whole new file is written to a temp file in the same folder, the ledger is re-read just before the replace and,
    when another writer changed it meanwhile, `mutate` is applied again to what is there now (a row added in between is
    kept). The result must satisfy C04 or `LedgerError` is raised and the file is untouched. `before_replace` is a test hook."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with (contextlib.nullcontext() if _locked else _Lock(path)):
        for _attempt in range(10):
            base = _read_retry(path)
            new = mutate(base)
            if new == base:
                return new
            problems = ledger_problems(new)
            if problems:
                raise LedgerError("; ".join(problems))
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".ledger-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
                if before_replace is not None:
                    before_replace()
                current = _read_retry(path)
                if current != base:
                    continue   # someone wrote in between: apply the change to the new content
                _replace(tmp, path)
                tmp = None
                return new
            finally:
                if tmp is not None:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
        raise LedgerError("the ledger kept changing under the writer; try again")


# ------------------------------------------------------------------ brief new


def new_brief(root, cfg, slug, topic, agent, title, model=None, kind=None, sizing=None, report=None, date=None):
    """Write a brief from the template and add its ledger row. Returns a dict with the paths and the notes.

    Raises DelegationError (bad input) or LedgerError (the ledger would not satisfy C04; nothing is left behind)."""
    root = Path(root).resolve()
    pinned, default_kind = AGENTS[agent]
    model = model or pinned
    notes = []
    if model is None:
        raise DelegationError(f"--model is required with --agent {agent} (it has no pinned model)")
    if pinned and model != pinned:
        notes.append(f"{agent} is pinned to {pinned}; {model} is an escalation, say why in the brief's model line")
    kind = kind or default_kind
    if kind is None:
        raise DelegationError(f"--kind is required with --agent {agent} (it has no default kind)")
    if not _TOPIC.match(topic):
        raise DelegationError("--topic is lower-case kebab-case (letters, digits and hyphens): the id is <topic>-<date>")
    date = date or dt.date.today().isoformat()
    try:
        dt.date.fromisoformat(date)
    except ValueError as exc:
        raise DelegationError(f"--date {date!r} is not an ISO date") from exc
    for label, value in (("--title", title), ("--slug", slug), ("--sizing", sizing or ""), ("--report", str(report or ""))):
        if LINE_BOUNDARY.search(value):
            raise DelegationError(f"{label} must be on one line")
    folder = delegation_dir(root, cfg)
    ledger = folder / "ledger.md"
    folder.mkdir(parents=True, exist_ok=True)
    temp_root = str((cfg.get("roots") or {}).get("temp", "")).replace("\\", "/") or "<temp root>"
    with _Lock(ledger):   # the id is chosen and its file created inside the ledger lock: two writers never pick one id
        taken = set()
        if ledger.is_file():
            taken = {r["ID"] for r in ledger_rows(_read_retry(ledger))[1]}
        ident, n = f"{topic}-{date}", 2
        while True:
            brief = folder / f"{ident}.brief.md"
            if ident not in taken:
                try:
                    handle = open(brief, "x", encoding="utf-8", newline="\n")   # exclusive: never an existing file
                    break
                except FileExistsError:
                    pass
            ident = f"{topic}-{date}-{n}"
            n += 1
        try:
            with handle:
                report_path = Path(report).resolve() if report else folder / f"{ident}.report.md"
                try:
                    rel_brief, rel_report = brief.relative_to(root).as_posix(), report_path.relative_to(root).as_posix()
                except ValueError as exc:
                    raise DelegationError("the brief and the report must lie inside the project root: the ledger holds relative paths") from exc
                handle.write(render_template(kind, {"title": title, "id": ident, "agent": agent, "model": model,
                                                    "report": report_path.as_posix(), "brief": brief.as_posix(),
                                                    "sizing": sizing or "", "temp_root": temp_root}))
            row = {"ID": ident, "Agent": agent, "Model": model, "Brief": rel_brief, "Report": rel_report, "Status": "drafted", "Accepted": "no"}
            update_ledger(ledger, lambda current: ledger_add_row(current, row, title=slug), _locked=True)
        except BaseException:
            brief.unlink()   # only the file this call created (the exclusive create above)
            raise
    return {"id": ident, "brief": brief, "report": report_path, "ledger": ledger, "notes": notes}
