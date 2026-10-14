"""Reading a feature spec and the files around it: shared by the spec, size, adr and tech areas, the approval and the trace.

What lives here: comment stripping (a template example is an HTML comment and never counts), the C05 spec as an object,
the Gate cell rules (a backticked command or a test id), the named test files a Gate cell points at, the catalog and ADR
lookups, and the LF-normalized SHA-256 every hash of the freeze uses (decision 4: CRLF and LF variants hash equal).
"""
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from batuta_lib import config
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm

CATALOG_PATH = "docs/contracts/catalog.md"
ADR_DIR = "docs/decisions"
TECH_DIR = "docs/design/tech"
SPECS_DIR = "specs"
FOUNDATION = "000-foundation"
SPEC_ID = re.compile(r"\d{3}-[a-z0-9-]+\Z")
REQ_ID = re.compile(r"REQ-[A-Z0-9]+-\d{3}\Z")
ADR_ID = re.compile(r"\bADR-\d{4}\b")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE = re.compile(r"^[ \t]*(```|~~~)")
PLACEHOLDER_GATES = {"", "-", "tbd", "todo", "n/a", "na", "none", "manual", "later", "?"}
_TEST_ID = re.compile(r"[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+)*\.[A-Za-z0-9]+(?:::[A-Za-z0-9_\[\]-]+)?\Z")
_PATH_TOKEN = re.compile(r"[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+)*/?\Z")
_TEST_SEGMENTS = {"test", "tests", "__tests__"}
_SKIP_PARTS = {"__pycache__", "node_modules", ".git"}


# ------------------------------------------------------------------ text and hashes


def strip_comments(text):
    """The text without HTML comments (fenced code blocks are kept as they are). Template examples sit in comments."""
    out, run, fence = [], [], None
    for line in text.split("\n"):
        m = _FENCE.match(line)
        if fence is None and m:
            out.append(_COMMENT.sub("", "\n".join(run)) if run else None)
            run = []
            fence = m.group(1)
            out.append(line)
        elif fence is not None:
            out.append(line)
            if m and m.group(1) == fence:
                fence = None
        else:
            run.append(line)
    if run:
        out.append(_COMMENT.sub("", "\n".join(run)))
    return "\n".join(x for x in out if x is not None)


def sha256_bytes_lf(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def sha256_lf(path):
    return sha256_bytes_lf(Path(path).read_bytes())


def rel(path, root):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def slugify(title, limit=40):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:limit].strip("-")
    return slug or "spec"


# ------------------------------------------------------------------ contracts of the unit


def schema_and_sections(cid):
    sp = core.find_schema(config.contracts_dir(), cid)
    if sp is None:
        raise ValueError(f"{cid} schema not found in {config.contracts_dir()}")
    return core.load_schema(sp), core.load_sections_spec(sp), sp


def table_spec(cid, name):
    _, spec, _ = schema_and_sections(cid)
    return next(t for t in spec["tables"] if t["name"] == name)


def validate_text(cid, text):
    """Errors of a Markdown artifact (comments already stripped by the caller) against its built-in contract."""
    schema, spec, _ = schema_and_sections(cid)
    return core.validate_markdown(text, schema, spec)


def read_rows(cid, table_name, text, ci=False):
    """Rows of the named table of a Markdown artifact, or None when the table is absent."""
    found = core.read_table(text, table_spec(cid, table_name), ci)
    return found[0] if found else None


# ------------------------------------------------------------------ the spec


@dataclass
class Spec:
    path: Path
    text: str
    stripped: str
    meta: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def id(self):
        return self.meta.get("id", "")

    @property
    def status(self):
        return self.meta.get("status", "")

    @property
    def tier(self):
        return self.meta.get("tier", "")

    def active_rows(self):
        return [r for r in self.rows if r.get("Status") == "active"]


def read_spec(path):
    """The spec at `path` read after comment stripping: front matter, requirement rows and the C05 errors."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    stripped = strip_comments(text.replace("\r\n", "\n"))
    spec = Spec(path, text, stripped)
    spec.errors = validate_text("C05", stripped)
    try:
        spec.meta = fm.parse(stripped)[0]
    except ValueError:
        spec.meta = {}
    try:
        spec.rows = read_rows("C05", "Requirements", stripped, True) or []
        raw = _raw_gates(stripped)
        for row in spec.rows:
            # the table reader drops the backticks of a whole-cell span; the gate rules read the cell as written
            row["Gate"] = raw.get(row.get("Id"), row.get("Gate", ""))
    except ValueError:
        spec.rows = []
    return spec


def _raw_gates(stripped):
    body = fm.parse(stripped)[1] if stripped.lstrip().startswith("---") else stripped
    for title, headers, rows in fm.section_tables(body):
        if (title or "").lower() == "requirements" and "Id" in headers and "Gate" in headers:
            i, g = headers.index("Id"), headers.index("Gate")
            return {r[i].strip(): r[g].strip() for r in rows}
    return {}


def spec_dirs(root):
    base = Path(root) / SPECS_DIR
    if not base.is_dir():
        return []
    return sorted(d for d in base.iterdir() if d.is_dir() and d.name != FOUNDATION
                  and (SPEC_ID.match(d.name) or (d / "spec.md").is_file()))


def spec_path(root, spec_id):
    return Path(root) / SPECS_DIR / spec_id / "spec.md"


def requirement_ids_by_spec(root):
    """Map of requirement id to the folders of the specs that define it (every status, every spec)."""
    found = {}
    for d in spec_dirs(root):
        p = d / "spec.md"
        if not p.is_file():
            continue
        try:
            rows = read_spec(p).rows
        except (OSError, ValueError):
            continue
        for row in rows:
            found.setdefault(row.get("Id", ""), [])
            if d.name not in found[row.get("Id", "")]:
                found[row.get("Id", "")].append(d.name)
    return found


def adr_references(spec):
    return sorted(set(ADR_ID.findall(spec.stripped)))


# ------------------------------------------------------------------ gates and named tests


def _spans(cell):
    return [s.strip() for s in re.findall(r"`([^`]+)`", cell) if s.strip()]


def check_gate(cell):
    """None when the Gate cell is runnable text (a backticked command or a test id `path[::name]`), else the reason."""
    raw = cell.strip()
    if raw.strip("`").strip().lower() in PLACEHOLDER_GATES:
        return "the gate is empty or a placeholder"
    spans = _spans(raw)
    if spans:
        if all(s.lower() in PLACEHOLDER_GATES for s in spans):
            return "the gate is a placeholder"
        return None
    if _TEST_ID.match(raw):
        return None
    return "the gate is neither a backticked command nor a test id (path or path::name)"


def is_test_path(path):
    parts = path.rstrip("/").split("/")
    name = parts[-1]
    return (any(p in _TEST_SEGMENTS for p in parts) or name.startswith("test_") or name.endswith("_test.py")
            or ".test." in name or ".spec." in name)


def named_test_tokens(cell):
    """Repository-relative paths (files, or folders ending in `/`) that a Gate cell names as tests."""
    spans = _spans(cell) or [cell.strip()]
    found = []
    for span in spans:
        for word in span.split():
            word = word.strip("\"',;()").split("::")[0]
            if word.startswith("./"):
                word = word[2:]
            if not word or word.startswith(("-", "/")) or ".." in word.split("/") or not _PATH_TOKEN.match(word):
                continue
            if "/" not in word and "." not in word:
                continue
            if is_test_path(word) and word not in found:
                found.append(word)
    return found


def expand_tests(root, tokens):
    """(files, missing): the existing test files named by `tokens` (a folder token adds every file under it)."""
    root = Path(root)
    files, missing = [], []
    for tok in tokens:
        p = root / tok.rstrip("/")
        if p.is_dir():
            for f in sorted(x for x in p.rglob("*") if x.is_file() and not (_SKIP_PARTS & set(x.parts)) and x.suffix != ".pyc"):
                r = rel(f, root)
                if r not in files:
                    files.append(r)
        elif p.is_file():
            r = rel(p, root)
            if r not in files:
                files.append(r)
        else:
            missing.append(tok)
    return files, missing


def spec_test_tokens(spec, include_retired=False):
    tokens = []
    for row in (spec.rows if include_retired else spec.active_rows()):
        for tok in named_test_tokens(row.get("Gate", "")):
            if tok not in tokens:
                tokens.append(tok)
    return tokens


# ------------------------------------------------------------------ catalog, ADRs, sizing


def catalog_file(root, override=None):
    return Path(override) if override else Path(root) / CATALOG_PATH


def read_catalog_rows(root, override=None):
    """(rows or None, items): the catalog rows, or None with FAIL items when absent or invalid."""
    from batuta_lib.areas import contract as carea
    p = catalog_file(root, override)
    items = []
    if not p.is_file():
        return None, items
    rows = carea.read_catalog(p, items)
    return rows, items


def interface_ids(spec):
    from batuta_lib.areas import contract as carea
    seen = []
    for i in carea._interface_ids(spec.stripped):
        if i not in seen:
            seen.append(i)
    return seen


def find_adr(root, adr_id):
    base = Path(root) / ADR_DIR
    if not base.is_dir():
        return None
    hits = sorted(base.glob(f"{adr_id}-*.md")) + sorted(base.glob(f"{adr_id}.md"))
    return hits[0] if hits else None


def adr_status(path):
    try:
        return fm.parse(Path(path).read_text(encoding="utf-8-sig"))[0].get("status", "")
    except (OSError, ValueError):
        return ""


def find_sizing(root, explicit=None, config_arg=None):
    """The sizing file: the explicit path, else the one under the coordination root of the project. Returns (path or None,
    the places looked at)."""
    from batuta_lib.areas import contract as carea
    if explicit:
        return Path(explicit), [Path(explicit).as_posix()]
    coord = config.load(config_arg, project_root=root).config.get("coordination_root", ".batuta")
    places = [f"{coord}/sizing.md", f"{coord}/*/sizing.md", "sizing.md"]
    found = carea._sizing_candidates(root, coord)
    return (found[0] if found else None), places
