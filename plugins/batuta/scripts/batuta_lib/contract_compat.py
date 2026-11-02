"""The contract version rule (CONTRACT-5): compare every contract schema with the same file at a git ref.

A schema whose content changed since the ref must change its `contract_version`. A breaking change needs a higher major
version; an additive change needs at least a higher minor version. Schemas are compared as JSON values, never as text, so
reformatting is no change. Standard library only (ADR-0001).
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from batuta_lib.output import item

SCHEMA_GLOB = "C*-*.schema.json"
TIMEOUT = 60

# Keywords that only describe the schema: a change is additive and never breaking.
ANNOTATIONS = {"description", "title", "$comment", "examples", "example", "default", "$id", "$schema", "_why", "deprecated",
               "readOnly", "writeOnly"}
# A larger value is stricter (lower bounds), a smaller value is stricter (upper bounds).
LOWER_BOUNDS = {"minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties", "minContains"}
UPPER_BOUNDS = {"maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties", "maxContains"}
# A change of these cannot be ranked as looser or stricter, so it is breaking; removing the keyword is additive.
OPAQUE = {"pattern", "format", "multipleOf", "contentEncoding", "contentMediaType"}
# Maps of name to schema: a removed name is breaking, a new name is additive.
NAMED_MAPS = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
BRANCHES = {"oneOf", "anyOf", "allOf"}


@dataclass
class Changes:
    breaking: list = field(default_factory=list)
    additive: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.breaking or self.additive)


def _esc(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def _types(value):
    return {value} if isinstance(value, str) else set(value) if isinstance(value, list) else set()


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _contains(values, wanted):
    return any(v == wanted and type(v) is type(wanted) for v in values)


def classify(old, new):
    """The breaking and additive changes between two schema documents, each a list of `<json path>: <what changed>`."""
    changes = Changes()
    _node(old, new, "", changes)
    return changes


def changed(old, new):
    """True when the two schemas differ in content, ignoring `contract_version`."""
    return _strip(old) != _strip(new)


def _strip(doc):
    return {k: v for k, v in doc.items() if k != "contract_version"} if isinstance(doc, dict) else doc


def _node(old, new, path, out):
    if old == new:
        return
    where = path or "/"
    if not isinstance(old, dict) or not isinstance(new, dict):
        # a boolean schema: `false` accepts nothing and `true` everything, so only a move toward `true` is a relaxation
        relaxed = old is False or new is True
        (out.additive if relaxed else out.breaking).append(f"{where}: schema changed from {_show(old)} to {_show(new)}")
        return
    for key in sorted(set(old) | set(new)):
        o, n = old.get(key), new.get(key)
        has_o, has_n = key in old, key in new
        if has_o and has_n and o == n:
            continue
        here = f"{path}/{_esc(key)}"
        if key == "contract_version":
            continue
        if key in ANNOTATIONS:
            out.additive.append(f"{here}: {key} changed")
        elif key in NAMED_MAPS:
            _named(o or {}, n or {}, here, out)
        elif key == "required":
            added = [x for x in (n or []) if x not in (o or [])]
            dropped = [x for x in (o or []) if x not in (n or [])]
            out.breaking.extend(f"{here}: {x!r} added to required" for x in added)
            out.additive.extend(f"{here}: {x!r} dropped from required" for x in dropped)
        elif key == "enum":
            _enum(has_o, o, has_n, n, here, out)
        elif key == "const":
            if has_o and not has_n:
                out.additive.append(f"{here}: const removed")
            elif has_n and not has_o:
                out.breaking.append(f"{here}: const {_show(n)} added")
            else:
                out.breaking.append(f"{here}: const changed from {_show(o)} to {_show(n)}")
        elif key == "type":
            _type(has_o, o, has_n, n, here, out)
        elif key in LOWER_BOUNDS or key in UPPER_BOUNDS:
            _bound(key, has_o, o, has_n, n, here, out)
        elif key in OPAQUE:
            if has_o and not has_n:
                out.additive.append(f"{here}: {key} removed")
            elif has_n and not has_o:
                out.breaking.append(f"{here}: {key} {_show(n)} added")
            else:
                out.breaking.append(f"{here}: {key} changed from {_show(o)} to {_show(n)}")
        elif key == "additionalProperties" or key == "unevaluatedProperties":
            _additional(key, has_o, o, has_n, n, here, out)
        elif key == "uniqueItems":
            if n is True and o is not True:
                out.breaking.append(f"{here}: uniqueItems added")
            else:
                out.additive.append(f"{here}: uniqueItems removed")
        elif key == "$ref":
            out.breaking.append(f"{here}: $ref changed from {_show(o)} to {_show(n)}")
        elif key in ("items", "contains", "propertyNames", "not", "if", "then", "else", "additionalItems"):
            _single(key, has_o, o, has_n, n, here, out)
        elif key in BRANCHES or key == "prefixItems":
            _branches(key, o or [], n or [], here, out)
        else:
            out.breaking.append(f"{here}: {key} changed")


def _show(value):
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 60 else text[:57] + "..."


def _named(old, new, path, out):
    for name in sorted(set(old) | set(new)):
        here = f"{path}/{_esc(name)}"
        if name not in new:
            out.breaking.append(f"{here}: removed")
        elif name not in old:
            out.additive.append(f"{here}: added")
        else:
            _node(old[name], new[name], here, out)


def _enum(has_o, o, has_n, n, path, out):
    if not has_n:
        out.additive.append(f"{path}: enum removed")
    elif not has_o:
        out.breaking.append(f"{path}: enum added")
    else:
        for value in o:
            if not _contains(n, value):
                out.breaking.append(f"{path}: value {_show(value)} removed")
        for value in n:
            if not _contains(o, value):
                out.additive.append(f"{path}: value {_show(value)} added")


def _type(has_o, o, has_n, n, path, out):
    if not has_n:
        out.additive.append(f"{path}: type removed")
    elif not has_o:
        out.breaking.append(f"{path}: type {_show(n)} added")
    else:
        removed, added = _types(o) - _types(n), _types(n) - _types(o)
        if removed:
            out.breaking.append(f"{path}: type {', '.join(sorted(removed))} removed (now {_show(n)})")
        if added:
            out.additive.append(f"{path}: type {', '.join(sorted(added))} added")


def _bound(key, has_o, o, has_n, n, path, out):
    if not has_n:
        out.additive.append(f"{path}: {key} removed")
    elif not has_o:
        out.breaking.append(f"{path}: {key} {_show(n)} added")
    elif not (_num(o) and _num(n)):
        out.breaking.append(f"{path}: {key} changed from {_show(o)} to {_show(n)}")
    elif (n > o) == (key in LOWER_BOUNDS):
        out.breaking.append(f"{path}: {key} tightened from {_show(o)} to {_show(n)}")
    else:
        out.additive.append(f"{path}: {key} relaxed from {_show(o)} to {_show(n)}")


def _additional(key, has_o, o, has_n, n, path, out):
    old_open = (not has_o) or o is True
    new_open = (not has_n) or n is True
    if old_open and not new_open:
        out.breaking.append(f"{path}: {key} closed to {_show(n)}")
    elif new_open:
        out.additive.append(f"{path}: {key} opened")
    else:
        _node(o, n, path, out)


def _single(key, has_o, o, has_n, n, path, out):
    if not has_n:
        out.additive.append(f"{path}: {key} removed")
    elif not has_o:
        out.breaking.append(f"{path}: {key} added")
    elif key in ("not", "if", "then", "else"):
        out.breaking.append(f"{path}: {key} changed")
    else:
        _node(o, n, path, out)


def _branches(key, old, new, path, out):
    if not (isinstance(old, list) and isinstance(new, list)):
        out.breaking.append(f"{path}: {key} changed")
        return
    for i in range(min(len(old), len(new))):
        _node(old[i], new[i], f"{path}/{i}", out)
    narrowing = key in ("allOf", "prefixItems")
    for i in range(len(old), len(new)):
        (out.breaking if narrowing else out.additive).append(f"{path}/{i}: branch added")
    for i in range(len(new), len(old)):
        (out.additive if narrowing else out.breaking).append(f"{path}/{i}: branch removed")


# ------------------------------------------------------------------ the version rule


def parse_version(text):
    """(major, minor) of a version string like '1.1', or None."""
    match = re.fullmatch(r"(\d+)\.(\d+)", str(text))
    return (int(match.group(1)), int(match.group(2))) if match else None


def _git(cwd, *args, binary=False):
    """(return code, stdout bytes or text, stderr text); 127 when git cannot run."""
    try:
        p = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(cwd), *args], capture_output=True,
                           timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, b"" if binary else "", f"git could not run: {exc}"
    err = p.stderr.decode("utf-8", errors="replace").strip()
    return p.returncode, (p.stdout if binary else p.stdout.decode("utf-8", errors="replace")), err


def _load(data, label):
    try:
        doc = json.loads(data.decode("utf-8-sig") if isinstance(data, bytes) else data)
    except ValueError as exc:
        return None, f"{label} is not valid JSON: {exc}"
    return (doc, None) if isinstance(doc, dict) else (None, f"{label} is not a JSON object")


def check_against(cdir, ref):
    """Items for every contract schema in `cdir` compared with the same file at the git ref `ref`.

    Outside a git repository, with git missing, or with an unknown ref the result is one FAIL item naming the cause."""
    cdir = Path(cdir)
    rc, out, err = _git(cdir, "rev-parse", "--show-prefix")
    if rc != 0:
        return [item("FAIL", f"cannot compare with {ref}: {cdir.as_posix()} is not inside a git repository or git is not "
                             f"available ({err or 'no detail'})")]
    prefix = out.strip()
    rc, _, err = _git(cdir, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if rc != 0:
        return [item("FAIL", f"cannot compare with {ref}: no such git ref or commit in {cdir.as_posix()}"
                             + (f" ({err})" if err else ""))]
    rc, listing, _ = _git(cdir, "ls-tree", "--name-only", ref)   # the folder the command runs in
    at_ref = {Path(line).name for line in listing.splitlines()} if rc == 0 else set()
    at_ref = {n for n in at_ref if re.fullmatch(r"C\d+-.+\.schema\.json", n)}
    now = {p.name: p for p in cdir.glob(SCHEMA_GLOB) if re.match(r"^C\d+-", p.name)}
    items = []
    for name in sorted(set(now) | at_ref):
        items.append(_one(cdir, prefix, ref, name, now.get(name), name in at_ref))
    return items


def _one(cdir, prefix, ref, name, path, existed):
    cid = name.split("-")[0]
    rel = f"{prefix}{name}"
    if path is None:
        return item("FAIL", f"{cid} was deleted since {ref}: a contract is never deleted, it is superseded", rel)
    new_bytes = path.read_bytes()
    if not existed:
        return item("OK", f"{cid} is a new contract since {ref}", rel)
    rc, old_bytes, err = _git(cdir, "show", f"{ref}:{rel}", binary=True)
    if rc != 0:
        return item("FAIL", f"{cid}: cannot read {name} at {ref}: {err}", rel)
    if old_bytes == new_bytes:
        return item("OK", f"{cid} unchanged since {ref}", rel)
    new, problem = _load(new_bytes, name)
    if problem:
        return item("FAIL", f"{cid}: {problem}", rel)
    old, problem = _load(old_bytes, f"{name} at {ref}")
    if problem:
        return item("FAIL", f"{cid}: {problem}", rel)
    new_version = parse_version(new.get("contract_version"))
    if new_version is None:
        return item("FAIL", f"{cid}: {name} has no valid contract_version (like '1.0')", rel)
    old_version = parse_version(old.get("contract_version")) or (0, 0)
    if not changed(old, new):
        return item("OK", f"{cid} unchanged in content since {ref} (version {old.get('contract_version')} "
                          f"to {new.get('contract_version')})", rel)
    found = classify(old, new)
    old_text, new_text = old.get("contract_version"), new.get("contract_version")
    if found.breaking:
        needed = f"{old_version[0] + 1}.0"
        if new_version[0] > old_version[0]:
            return item("OK", f"{cid} changed with breaking change(s) and a major bump from {old_text} to {new_text}", rel)
        return item("FAIL", f"{cid} {name} has breaking change(s) since {ref} but contract_version is {new_text} "
                            f"(was {old_text}); it needs {needed} or higher. Breaking: {'; '.join(found.breaking)}"
                            + (f". Additive: {'; '.join(found.additive)}" if found.additive else ""), rel)
    if new_version > old_version:
        return item("OK", f"{cid} changed additively and the version moved from {old_text} to {new_text}", rel)
    needed = f"{old_version[0]}.{old_version[1] + 1}"
    return item("FAIL", f"{cid} {name} has additive change(s) since {ref} but contract_version is {new_text} "
                        f"(was {old_text}); it needs {needed} or higher. Additive: {'; '.join(found.additive)}", rel)
