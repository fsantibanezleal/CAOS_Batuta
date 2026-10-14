"""The requirement to test to task matrix (C08), built from the spec rows, tasks.md and the REQ markers of the tests.

The marker convention (decision 24) is shared with `tdd lock`: a comment line `# REQ: <id>[, <id>...]` in Python or
`// REQ: <id>[, <id>...]` in JavaScript and TypeScript. Nothing else counts: not a marker inside a string, not another
comment form, not another keyword spelling. A test file is "tagged" when it carries at least one marker line.
"""
import json
import re
from pathlib import Path

from batuta_lib import spec_model as sm

_HASH_MARK = re.compile(r"^[ \t]*#[ \t]*REQ:[ \t]*(.*?)[ \t]*$")
_SLASH_MARK = re.compile(r"^[ \t]*//[ \t]*REQ:[ \t]*(.*?)[ \t]*$")
MARKERS = {".py": _HASH_MARK, ".js": _SLASH_MARK, ".jsx": _SLASH_MARK, ".ts": _SLASH_MARK, ".tsx": _SLASH_MARK,
           ".mjs": _SLASH_MARK, ".cjs": _SLASH_MARK}


def scan_markers(path):
    """The requirement ids tagged in a test file, in order (an unreadable file or an unsupported type has none)."""
    pattern = MARKERS.get(Path(path).suffix)
    if pattern is None:
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    ids = []
    for line in lines:
        m = pattern.match(line)
        if m:
            ids.extend(tok for tok in (t.strip() for t in m.group(1).split(",")) if tok)
    return ids


def supported(path):
    return Path(path).suffix in MARKERS


def scope_files(root, spec, extra=()):
    """The test files of the feature: those a Gate cell names, plus the `extra` paths (files or folders)."""
    # retired rows keep their tests in scope: a test that still tags a retired id is a finding
    files, _ = sm.expand_tests(root, sm.spec_test_tokens(spec, include_retired=True) + [e.strip().rstrip("/") for e in extra])
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
