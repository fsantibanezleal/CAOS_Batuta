"""The requirement to test to task matrix (C08), built from the spec rows, tasks.md and the REQ markers of the tests.

The marker convention (decision 24) is shared with `tdd lock`: a comment line `# REQ: <id>[, <id>...]` in Python or
`// REQ: <id>[, <id>...]` in JavaScript and TypeScript. Nothing else counts: not a marker inside a string, a template
literal or a block comment, not a trailing comment, not another comment form, not another keyword spelling. A test file is
"tagged" when it carries at least one marker line. `scan_markers` is the one reader of the convention (`tdd lock` adopts it).
"""
import io
import json
import re
import tokenize
from pathlib import Path

from batuta_lib import spec_model as sm

_MARK = re.compile(r"(?:#|//)[ \t]*REQ:[ \t]*(.*?)[ \t]*\Z")
PY_SUFFIXES = (".py",)
JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
MARKERS = {**{s: "py" for s in PY_SUFFIXES}, **{s: "js" for s in JS_SUFFIXES}}
_NL = "\n"


def _ids(text):
    return [tok for tok in (t.strip() for t in text.split(",")) if tok]


def _python_markers(text):
    """Marker ids from `tokenize` COMMENT tokens that stand alone on their line (a marker inside a string never counts).
    A file that stops tokenizing keeps the markers read before the error."""
    ids = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and not tok.line[:tok.start[1]].strip():
                m = _MARK.match(tok.string)
                if m and tok.string.startswith("#"):
                    ids.extend(_ids(m.group(1)))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return ids


def _js_markers(text):
    """Marker ids from `//` comments that start a line, outside strings, template literals and block comments."""
    ids = []
    state, quote, i, n = "code", "", 0, len(text)
    line_start = True
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == _NL:
                line_start = True
            elif c in " \t\r":
                pass
            elif c == "/" and nxt == "/":
                end = text.find(_NL, i)
                end = n if end < 0 else end
                if line_start:
                    m = _MARK.match(text[i:end].rstrip("\r"))
                    if m:
                        ids.extend(_ids(m.group(1)))
                i = end
                continue
            elif c == "/" and nxt == "*":
                state, i, line_start = "block", i + 2, False
                continue
            elif c in "'\"`":
                state, quote, line_start = "string", c, False
            else:
                line_start = False
        elif state == "block":
            if c == "*" and nxt == "/":
                state, i = "code", i + 2
                continue
        else:  # a string or a template literal
            if c == "\\":
                i += 2
                continue
            if c == quote:
                state = "code"
            elif c == _NL and quote != "`":
                state = "code"   # an unterminated quote ends at its line
        i += 1
    return ids


def scan_markers(path):
    """The requirement ids tagged in a test file, in order. An unreadable file or an unsupported type has none."""
    kind = MARKERS.get(Path(path).suffix)
    if kind is None:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    return _python_markers(text) if kind == "py" else _js_markers(text)


def supported(path):
    return Path(path).suffix in MARKERS


def scope_files(root, spec, extra=()):
    """The test files of the feature: those a Gate cell names, plus the `extra` paths (files or folders)."""
    # retired rows keep their tests in scope: a test that still tags a retired id is a finding
    files, _, _ = sm.expand_tests(root, sm.spec_test_tokens(spec, include_retired=True) + [e.strip().rstrip("/") for e in extra])
    return [f for f in files if supported(f)]


def build(root, spec, task_rows, extra_tests=()):
    """(matrix dict for C08, findings): findings are {"kind": orphan|unknown|retired|untagged|no-task, "id"/"path", ...}."""
    root = Path(root)
    status = {r["Id"]: r.get("Status", "active") for r in spec.rows}
    tags = {}
    files = scope_files(root, spec, extra_tests)
    untagged = []
    for f in files:
        ids = scan_markers(root / f)
        if not ids:
            untagged.append(f)
        for i in ids:
            tags.setdefault(i, [])
            if f not in tags[i]:
                tags[i].append(f)
    tasks = {}
    unknown, findings = set(), []
    for t in task_rows or []:
        for r in t["Requirements"]:
            if r in status:
                tasks.setdefault(r, []).append(t["Task"])
            else:
                unknown.add(r)
                findings.append({"kind": "unknown", "id": r, "where": f"task {t['Task']}"})
    for i, where in tags.items():
        if i not in status:
            unknown.add(i)
            findings.append({"kind": "unknown", "id": i, "where": ", ".join(where)})
        elif status[i] == "retired":
            unknown.add(i)
            findings.append({"kind": "retired", "id": i, "where": ", ".join(where)})
    reqs, orphans = [], []
    for row in spec.rows:
        i = row["Id"]
        reqs.append({"id": i, "gate": row.get("Gate", ""), "tests": sorted(tags.get(i, [])),
                     "tasks": sorted(tasks.get(i, [])), "status": row.get("Status", "active")})
        if row.get("Status") == "active":
            if not tags.get(i):
                orphans.append(i)
            if not tasks.get(i):
                findings.append({"kind": "no-task", "id": i})
    orphans.sort()
    for i in orphans:
        findings.append({"kind": "orphan", "id": i})
    for f in untagged:
        findings.append({"kind": "untagged", "path": f})
    matrix = {"contract_version": "1.0", "spec_id": spec.id, "requirements": reqs, "orphans": orphans,
              "unknown_ids": sorted(unknown), "untagged_tests": sorted(untagged),
              "ok": not (orphans or unknown or untagged)}
    return matrix, findings


def dumps(matrix):
    return json.dumps(matrix, indent=2) + "\n"
