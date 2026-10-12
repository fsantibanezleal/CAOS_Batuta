"""Stdlib validator for the JSON Schema subset used by Batuta data contracts (contracts/).

Supported keywords (draft 2020-12 semantics): type, enum, const, pattern, required, properties,
additionalProperties (bool or schema), items, minItems, minimum, maximum, maxLength, minLength, $ref to
`#/$defs/<name>` in the same file, $defs (root only), description. Root-only metadata: $schema, $id, title,
contract_id, contract_version. Any other keyword makes `load_schema` refuse the schema, so a schema never
silently promises more than the validator checks.

Error strings look like `/path/to/field: message` (JSON pointer; the root is `/`). Markdown and JSONL helpers
prefix them with where they came from (`front matter`, `table 'T' row 2`, `line 5`).
"""
import copy
import fnmatch
import json
import re
from functools import lru_cache
from pathlib import Path

from batuta_lib import frontmatter as fm

KEYWORDS = {"type", "enum", "const", "pattern", "required", "properties", "additionalProperties", "items",
            "minItems", "minimum", "maximum", "maxLength", "minLength", "$ref", "$defs", "description"}
ROOT_META = {"$schema", "$id", "title", "contract_id", "contract_version"}
FIXTURE_KEYS = ("_why", "_expect", "_recorded")
TYPES = {"string", "integer", "number", "boolean", "null", "object", "array"}


# ------------------------------------------------------------------ strict JSON and patterns


def _refuse_constant(name):
    raise ValueError(f"{name} is not valid JSON (use null or a finite number)")


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key '{key}'")
        out[key] = value
    return out


def loads_strict(text):
    """json.loads that refuses NaN, Infinity and duplicate object keys (ValueError with the reason)."""
    return json.loads(text, parse_constant=_refuse_constant, object_pairs_hook=_no_duplicates)


def _anchor(pattern):
    r"""Translate a JSON Schema (ECMA-262) pattern for Python: `$` means the end of the text (`\Z`), never before a
    trailing newline. Escaped dollars and dollars inside a character class stay literal."""
    out, i, in_class = [], 0, False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "$":
            out.append(r"\Z")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


@lru_cache(maxsize=None)
def compile_pattern(pattern):
    """The compiled form used everywhere: ASCII digits and word characters, and `$` anchored at the very end."""
    return re.compile(_anchor(pattern), re.ASCII)


# ------------------------------------------------------------------ schema checking


def _esc(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check(node, path, root, errs, is_root):
    here = path or "/"
    if not isinstance(node, dict):
        errs.append(f"schema at {here}: a schema must be an object")
        return
    for key in node:
        if key in KEYWORDS:
            continue
        if key in ROOT_META and is_root:
            continue
        if key == "title" and not is_root:
            continue
        errs.append(f"unsupported keyword '{key}' at {here}")
    if "type" in node:
        t = node["type"]
        ts = t if isinstance(t, list) else [t]
        if not ts or not all(isinstance(x, str) and x in TYPES for x in ts):
            errs.append(f"invalid type {t!r} at {here}")
    if "enum" in node and not (isinstance(node["enum"], list) and node["enum"]):
        errs.append(f"enum at {here} must be a non-empty list")
    if "pattern" in node:
        try:
            compile_pattern(node["pattern"])
        except (re.error, TypeError) as exc:
            errs.append(f"invalid pattern at {here}: {exc}")
    if "required" in node and not (isinstance(node["required"], list) and all(isinstance(x, str) for x in node["required"])):
        errs.append(f"required at {here} must be a list of strings")
    for k in ("minimum", "maximum"):
        if k in node and not _is_num(node[k]):
            errs.append(f"{k} at {here} must be a number")
    for k in ("minItems", "minLength", "maxLength"):
        if k in node and not (isinstance(node[k], int) and not isinstance(node[k], bool) and node[k] >= 0):
            errs.append(f"{k} at {here} must be a non-negative integer")
    if "description" in node and not isinstance(node["description"], str):
        errs.append(f"description at {here} must be a string")
    if "$ref" in node:
        ref = node["$ref"]
        defs = root.get("$defs", {}) if isinstance(root.get("$defs"), dict) else {}
        if not (isinstance(ref, str) and ref.startswith("#/$defs/") and ref[len("#/$defs/"):] in defs):
            errs.append(f"$ref at {here} must point to '#/$defs/<name>' in the same file (got {ref!r})")
    if "properties" in node:
        if isinstance(node["properties"], dict):
            for name, sub in node["properties"].items():
                _check(sub, f"{path}/properties/{_esc(name)}", root, errs, False)
        else:
            errs.append(f"properties at {here} must be an object")
    if "additionalProperties" in node and not isinstance(node["additionalProperties"], bool):
        _check(node["additionalProperties"], f"{path}/additionalProperties", root, errs, False)
    if "items" in node:
        _check(node["items"], f"{path}/items", root, errs, False)
    if "$defs" in node:
        if not is_root:
            errs.append(f"$defs at {here} is only allowed at the schema root")
        elif isinstance(node["$defs"], dict):
            for name, sub in node["$defs"].items():
                _check(sub, f"/$defs/{_esc(name)}", root, errs, False)
        else:
            errs.append("$defs must be an object")


def _ref_cycles(schema, errs):
    """A `$ref` chain that returns to where it started never ends: every instance would fail with a depth error.
    (Recursion through properties or items is fine: it consumes the instance.)"""
    if not isinstance(schema, dict) or not isinstance(schema.get("$defs"), dict):
        return
    defs = schema["$defs"]
    reported = set()
    starts = [("(root)", schema)] + list(defs.items())
    for name, node in starts:
        chain, cur = [name], node
        while isinstance(cur, dict) and isinstance(cur.get("$ref"), str) and cur["$ref"].startswith("#/$defs/"):
            nxt = cur["$ref"][len("#/$defs/"):]
            if nxt in chain:
                cyc = chain[chain.index(nxt):] + [nxt]
                key = frozenset(cyc)
                if key not in reported:
                    reported.add(key)
                    errs.append("$ref cycle: " + " -> ".join(cyc) + " (a chain of $ref that never reaches a schema)")
                break
            if nxt not in defs:
                break
            chain.append(nxt)
            cur = defs[nxt]


def check_schema(schema):
    """Return a list of problems (empty when the schema stays inside the supported subset)."""
    errs = []
    _check(schema, "", schema if isinstance(schema, dict) else {}, errs, True)
    if not errs:
        _ref_cycles(schema, errs)
    return errs


_FILE_CACHE = {}


def _cached(path, build):
    """Load a contract file once per (path, size, mtime): `contract lint` reads each schema once per fixture otherwise.
    Callers get their own copy."""
    path = Path(path)
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns, build.__name__)
    if key not in _FILE_CACHE:
        _FILE_CACHE[key] = build(path)
    return copy.deepcopy(_FILE_CACHE[key])


def _build_schema(path):
    try:
        schema = loads_strict(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ValueError(f"{path.name}: invalid JSON ({exc})") from exc
    problems = check_schema(schema)
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return schema


def load_schema(path):
    return _cached(path, _build_schema)


# ------------------------------------------------------------------ validation


def _type_name(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, dict):
        return "object"
    if isinstance(v, list):
        return "array"
    return type(v).__name__


def _is_type(v, t):
    if t == "integer":
        return (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, float) and v.is_integer())
    if t == "number":
        return _is_num(v)
    return _type_name(v) == t


def _eq(a, b):
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _walk(inst, sch, root, path, errs, depth=0):
    here = path or "/"
    if depth > 200:
        errs.append(f"{here}: schema nesting too deep")
        return
    if "$ref" in sch:
        _walk(inst, root["$defs"][sch["$ref"][len("#/$defs/"):]], root, path, errs, depth + 1)
    if "type" in sch:
        ts = sch["type"] if isinstance(sch["type"], list) else [sch["type"]]
        if not any(_is_type(inst, t) for t in ts):
            errs.append(f"{here}: expected {'|'.join(ts)}, got {_type_name(inst)}")
            return
    if "enum" in sch and not any(_eq(inst, e) for e in sch["enum"]):
        errs.append(f"{here}: value {inst!r} not in enum {sch['enum']}")
    if "const" in sch and not _eq(inst, sch["const"]):
        errs.append(f"{here}: expected constant {sch['const']!r}, got {inst!r}")
    if isinstance(inst, str):
        if "pattern" in sch and not compile_pattern(sch["pattern"]).search(inst):
            errs.append(f"{here}: value {inst!r} does not match pattern {sch['pattern']}")
        if "minLength" in sch and len(inst) < sch["minLength"]:
            errs.append(f"{here}: length {len(inst)} is below minLength {sch['minLength']}")
        if "maxLength" in sch and len(inst) > sch["maxLength"]:
            errs.append(f"{here}: length {len(inst)} exceeds maxLength {sch['maxLength']}")
    if _is_num(inst):
        if "minimum" in sch and inst < sch["minimum"]:
            errs.append(f"{here}: {inst} must be >= {sch['minimum']}")
        if "maximum" in sch and inst > sch["maximum"]:
            errs.append(f"{here}: {inst} must be <= {sch['maximum']}")
    if isinstance(inst, dict):
        for name in sch.get("required", []):
            if name not in inst:
                errs.append(f"{here}: missing required property '{name}'")
        props = sch.get("properties", {})
        for name, sub in props.items():
            if name in inst:
                _walk(inst[name], sub, root, f"{path}/{_esc(name)}", errs, depth + 1)
        extra = sch.get("additionalProperties", True)
        for name in inst:
            if name in props:
                continue
            if extra is False:
                errs.append(f"{path}/{_esc(name)}: unexpected property '{name}'")
            elif isinstance(extra, dict):
                _walk(inst[name], extra, root, f"{path}/{_esc(name)}", errs, depth + 1)
    if isinstance(inst, list):
        if "minItems" in sch and len(inst) < sch["minItems"]:
            errs.append(f"{here}: {len(inst)} items is fewer than minItems {sch['minItems']}")
        if "items" in sch:
            for i, item in enumerate(inst):
                _walk(item, sch["items"], root, f"{path}/{i}", errs, depth + 1)


def validate(instance, schema):
    """Return a list of error strings (empty when the instance satisfies the schema)."""
    errs = []
    _walk(instance, schema, schema, "", errs)
    return errs


def validate_def(instance, schema, name):
    """Validate against `#/$defs/<name>` of the schema."""
    return validate(instance, {"$ref": "#/$defs/" + name, "$defs": schema.get("$defs", {})})


# ------------------------------------------------------------------ semantic checks (what a plain schema cannot say)


def _check_c12(inst, schema):
    errs, units = [], inst.get("units", [])
    ids = [u.get("id") for u in units]
    seen = set()
    for i, u in enumerate(units):
        if u["id"] in seen:
            errs.append(f"/units/{i}/id: duplicate unit id '{u['id']}'")
        seen.add(u["id"])
        if u["load"] == "path" and not u.get("paths"):
            errs.append(f"/units/{i}: load=path requires non-empty 'paths'")
        if u["load"] == "trigger" and not u.get("triggers"):
            errs.append(f"/units/{i}: load=trigger requires non-empty 'triggers'")
        for field in ("requires", "related"):
            for ref in u.get(field, []):
                if ref not in ids:
                    errs.append(f"/units/{i}/{field}: unknown unit '{ref}'")
    graph = {u["id"]: [r for r in u.get("requires", []) if r in ids] for u in units}
    state = {}

    def visit(node, stack):
        state[node] = 1
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                cyc = stack[stack.index(nxt):] + [nxt] if nxt in stack else [node, nxt]
                errs.append("/units: requires cycle: " + " requires ".join(cyc))
            elif nxt not in state:
                visit(nxt, stack + [nxt])
        state[node] = 2

    for node in graph:
        if node not in state:
            visit(node, [node])
    return errs


def _check_c16(inst, schema):
    if "hookSpecificOutput" in inst:
        out = inst["hookSpecificOutput"]
        event = out.get("hookEventName") if isinstance(out, dict) else None
        name = {"PreToolUse": "output_pretooluse", "SessionStart": "output_sessionstart"}.get(event)
        if name is None:
            return [f"/hookSpecificOutput/hookEventName: unsupported output event {event!r}"]
        return validate_def(inst, schema, name)
    if "decision" in inst:
        return validate_def(inst, schema, "output_block")
    if "hook_event_name" in inst:
        event = inst["hook_event_name"]
        name = f"input_{event}"
        if not isinstance(event, str) or name not in schema.get("$defs", {}):
            return [f"/hook_event_name: unsupported hook event {event!r}"]
        return validate_def(inst, schema, name)
    return ["/: not a hook input or output (no hook_event_name, decision or hookSpecificOutput)"]


def _check_c25(inst, schema):
    """A tool decision: the optional evaluation names the chosen candidate, which must be the row; a risky
    candidate carries a spike, and a risky chosen candidate a spike that passed."""
    ev = inst.get("evaluation")
    if ev is None:
        return []
    errs, cands = [], ev["candidates"]
    names = [c["name"] for c in cands]
    for i, name in enumerate(names):
        if names.index(name) != i:
            errs.append(f"/evaluation/candidates/{i}/name: duplicate candidate '{name}'")
    chosen = next((c for c in cands if c["name"] == ev["chosen"]), None)
    if chosen is None:
        return errs + [f"/evaluation/chosen: '{ev['chosen']}' is not a candidate name"]
    if chosen["name"] != inst["tool"]:
        errs.append(f"/tool: '{inst['tool']}' differs from the chosen candidate '{chosen['name']}'")
    if chosen["version"] != inst["version"]:
        errs.append(f"/version: '{inst['version']}' differs from the chosen candidate's version '{chosen['version']}'")
    for i, c in enumerate(cands):
        if c.get("risky") and not c.get("spike"):
            errs.append(f"/evaluation/candidates/{i}/spike: a risky candidate carries a spike (command, result, evidence)")
    if chosen.get("risky") and (chosen.get("spike") or {}).get("result") != "pass":
        errs.append(f"/evaluation/chosen: '{chosen['name']}' is risky and can be chosen only after a spike that passed "
                    f"(result is '{(chosen.get('spike') or {}).get('result', 'absent')}')")
    return errs


def _text_ok(v):
    """A reason: a non-blank string, or an object with a non-blank string 'en'."""
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, dict):
        en = v.get("en")
        return isinstance(en, str) and bool(en.strip())
    return False


PROVIDER_KINDS = ("stub", "simulator", "fixture", "baseline")


def check_declaration_states(states, path, can_be_absent):
    """The availability rule of C26: a component that can be absent declares `available` and at least one
    non-available state; a state is declared once; the test ids are required by the schema."""
    errs, seen = [], set()
    for i, st in enumerate(states):
        name = st.get("state")
        if name in seen:
            errs.append(f"{path}/{i}/state: duplicate state '{name}'")
        seen.add(name)
    if can_be_absent:
        if "available" not in seen:
            errs.append(f"{path}: a component that can be absent must declare the 'available' state")
        if not (seen - {"available"}):
            errs.append(f"{path}: a component that can be absent must declare at least one non-available state")
    return errs


def _check_runtime_block(inst, path=""):
    errs = []
    state = inst.get("state")
    if state != "available" and not _text_ok(inst.get("reason")):
        errs.append(f"{path}/reason: state '{state}' must state a reason (a non-blank text)")
    if inst.get("age") is None and state not in ("available", "missing"):
        errs.append(f"{path}/age: age may be null only for available and missing, not '{state}'")
    if state == "provider" and inst.get("provenance") not in PROVIDER_KINDS:
        errs.append(f"{path}/provenance: a provider answer names its kind: {', '.join(PROVIDER_KINDS)}")
    return errs


def _check_c26(inst, schema):
    # Dispatch on the document shape: a declaration has `components`, a runtime block has `state`.
    if "components" in inst:
        errs = validate(inst, schema)
        if errs:
            return errs
        for i, comp in enumerate(inst["components"]):
            errs.extend(check_declaration_states(comp["states"], f"/components/{i}/states", comp["can_be_absent"]))
        return errs
    if "state" in inst:
        errs = validate_def(inst, schema, "runtime_block")
        return errs or _check_runtime_block(inst)
    return ["/: not an availability declaration (no 'components') nor a runtime block (no 'state')"]


def _check_c27(inst, schema):
    """The readiness rules of ADR-0080 decision 4 and of the product template's readiness schema."""
    errs = []
    for i, e in enumerate(inst["contracts"]):
        here = f"/contracts/{i}"
        state, prov, status = e["state"], e["provenance"], e["status"]
        if state == "available":
            if e["reason"] is not None:
                errs.append(f"{here}/reason: an available entry has no reason (null)")
            if prov != "real":
                errs.append(f"{here}/provenance: an available entry is served by the real producer (provenance 'real')")
        elif not _text_ok(e["reason"]):
            errs.append(f"{here}/reason: state '{state}' must state a reason (a non-blank text)")
        if state == "partial":
            if not e["missing"]:
                errs.append(f"{here}/missing: a partial entry lists what is missing")
        elif e["missing"]:
            errs.append(f"{here}/missing: only a partial entry lists what is missing")
        if state == "missing":
            if prov is not None:
                errs.append(f"{here}/provenance: nothing answered, so provenance must be null when the state is missing")
        elif prov is None:
            errs.append(f"{here}/provenance: provenance is null only when the state is missing")
        if state == "provider" and prov not in PROVIDER_KINDS:
            errs.append(f"{here}/provenance: a provider entry is served by a stub, simulator, fixture or baseline")
        if state == "training" and prov not in ("real", "baseline"):
            errs.append(f"{here}/provenance: a training model answers with the released model (real) or the baseline")
        if status != "real" and prov == "real":
            errs.append(f"{here}/provenance: status '{status}' means a provider serves the row, so provenance cannot be 'real'")
    ids = [e["id"] for e in inst["contracts"]]
    for i, x in enumerate(ids):
        if ids.index(x) != i:
            errs.append(f"/contracts/{i}/id: duplicate id '{x}'")
    return errs


def _check_c28(inst, schema):
    errs = []
    serving = inst.get("serving")
    unreleased = inst["status"] in ("planned", "training", "candidate")
    if serving is None:
        if unreleased:
            errs.append(f"/serving: required while the model is {inst['status']}: it must say which version or baseline answered")
        return errs
    if serving["alias"] != inst["alias"]:
        errs.append(f"/serving/alias: '{serving['alias']}' differs from the entry alias '{inst['alias']}'")
    if unreleased and serving["answered_by"] == inst["version"]:
        errs.append(f"/serving/answered_by: version '{inst['version']}' is {inst['status']} and cannot be the one that answers; "
                    f"name a released version or 'baseline'")
    return errs


_RELPATH = re.compile(r"(?!.*(^|/)\.\.(/|\Z))[^/\\:][^\\:]*\Z")


def _bad_relpath(p):
    return not (isinstance(p, str) and _RELPATH.fullmatch(p) and "//" not in p and not p.startswith("./") and "/./" not in p)


def _check_c01(inst, schema):
    errs, d = [], inst.get("dispatch")
    if d is None:
        return errs
    if d["default_lane"] not in d["lanes"]:
        errs.append(f"/dispatch/default_lane: '{d['default_lane']}' is not one of the enabled lanes {d['lanes']}")
    providers = d.get("providers", {})
    for lane in d["lanes"]:
        if lane.startswith("provider:") and lane[len("provider:"):] not in providers:
            errs.append(f"/dispatch/lanes: lane '{lane}' needs dispatch.providers.{lane[len('provider:'):]}")
    return errs


def _check_c04_line(inst, schema):
    errs = []
    if inst["status"] == "accepted":
        absent = [k for k in ("accepted_by", "accepted_at") if k not in inst]
        if absent:
            errs.append(f"/{absent[0]}: an accepted row records who accepted it and when (missing: {', '.join(absent)})")
    if inst["status"] == "superseded" and "superseded_by" not in inst:
        errs.append("/superseded_by: a superseded row names the row that replaces it")
    return errs


def _check_c06(inst, schema):
    errs = []
    for key in ("contracts_sha256", "named_tests_sha256", "adrs_sha256"):
        for path in inst[key]:
            if _bad_relpath(path):
                errs.append(f"/{key}: key {path!r} is not a POSIX relative path (no leading slash or ./, no backslash, drive or ..)")
    return errs


def _check_c07(inst, schema):
    errs = []
    for i, e in enumerate(inst["entries"]):
        if "supersedes" in e and "change_request" not in e:
            errs.append(f"/entries/{i}/change_request: an entry that supersedes another names the approved change request")
        if "change_request" in e and "supersedes" not in e:
            errs.append(f"/entries/{i}/supersedes: a change_request goes with the sha256 it supersedes")
    return errs


def _check_c30(inst, schema):
    kind = inst.get("kind")
    if kind not in ("request", "result"):
        return [f"/kind: must be 'request' or 'result', got {kind!r}"]
    errs = validate_def(inst, schema, kind)
    if errs:
        return errs
    if kind == "request":
        lane = inst["lane"]
        if lane.startswith("provider:") and inst.get("provider", lane[len("provider:"):]) != lane[len("provider:"):]:
            errs.append(f"/provider: '{inst['provider']}' differs from the lane '{lane}'")
        if not lane.startswith("provider:") and "provider" in inst:
            errs.append("/provider: only a provider:<name> lane names a provider")
        return errs
    if inst["lane"] != "subagent":
        absent = [k for k in ("tokens_in", "tokens_out", "cost_usd") if k not in inst]
        if absent:
            errs.append(f"/{absent[0]}: a run on the '{inst['lane']}' lane records tokens_in, tokens_out and cost_usd (missing: {', '.join(absent)})")
    if inst["status"] in ("error", "timeout", "over-budget") and not inst.get("error"):
        errs.append(f"/error: status '{inst['status']}' states what happened")
    if inst["status"] in ("complete", "incomplete", "defective") and "report" not in inst:
        errs.append(f"/report: status '{inst['status']}' means a report was written; name its path")
    return errs


HOOK_STDOUT = {"SessionStart": ("none", "sessionstart"), "PreToolUse": ("none", "block", "pretooluse"),
               "SubagentStop": ("none", "block"), "UserPromptSubmit": ("none", "block"), "Stop": ("none", "block")}


def _check_c31(inst, schema):
    """A hook registry (`handlers`) or the rendered hooks.json (`hooks`)."""
    if "handlers" in inst:
        errs = validate_def(inst, schema, "registry")
        if errs:
            return errs
        ids = []
        for i, h in enumerate(inst["handlers"]):
            here = f"/handlers/{i}"
            if h["id"] in ids:
                errs.append(f"{here}/id: duplicate handler id '{h['id']}'")
            ids.append(h["id"])
            if h["argv"][-1] != h["id"]:
                errs.append(f"{here}/argv: the last argument is the handler id '{h['id']}'")
            if not HOOK_ARGV0.fullmatch(h["argv"][0]):
                errs.append(f"{here}/argv/0: the interpreter is a bare command name (no path), got {h['argv'][0]!r}")
            if h["argv"][1] != LAUNCHER_PATH:
                errs.append(f"{here}/argv/1: the launcher is {LAUNCHER_PATH} (no machine path), got {h['argv'][1]!r}")
            if "matcher" in h and h["event"] != "PreToolUse":
                errs.append(f"{here}/matcher: only a PreToolUse handler has a matcher")
            if h["stdout"] not in HOOK_STDOUT[h["event"]]:
                errs.append(f"{here}/stdout: a {h['event']} handler writes one of {', '.join(HOOK_STDOUT[h['event']])}")
            if h["failure"] == "fail-open" and set(h["exit_codes"]) != {"0"}:
                errs.append(f"{here}/exit_codes: a fail-open handler always exits 0 (internal errors are logged, never block)")
            if h["failure"] == "fail-closed" and "2" not in h["exit_codes"]:
                errs.append(f"{here}/exit_codes: a fail-closed handler declares exit code 2 (block)")
        return errs
    if "hooks" in inst:
        errs = validate_def(inst, schema, "hooks_file")
        if errs:
            return errs
        for event, groups in inst["hooks"].items():
            for gi, g in enumerate(groups):
                if "matcher" in g and event != "PreToolUse":
                    errs.append(f"/hooks/{event}/{gi}/matcher: only PreToolUse groups carry a matcher")
        return errs
    return ["/: not a hook registry (no 'handlers') nor a hooks file (no 'hooks')"]


COMMIT_TRAILER = re.compile(r"([A-Za-z][A-Za-z0-9-]*): (.*)\Z", re.ASCII)
HOOK_ARGV0 = re.compile(r"[A-Za-z0-9._-]+\Z", re.ASCII)
LAUNCHER_PATH = "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py"


def parse_commit_message(text):
    """Split a commit message into (subject, lines after the subject, body lines, trailers as (key, value) pairs).
    Lines starting with '#' are git comments and are dropped. The trailers are the last paragraph when it follows a
    blank line and every line of it is `Key: value`."""
    lines = [ln.rstrip("\r") for ln in text.lstrip("﻿").split("\n") if not ln.startswith("#")]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    subject = lines[0] if lines else ""
    rest = lines[1:]
    paras, cur = [], []
    for ln in rest:
        if ln.strip():
            cur.append(ln)
        elif cur:
            paras.append(cur)
            cur = []
    if cur:
        paras.append(cur)
    trailers = []
    separated = not rest or not rest[0].strip()
    if separated and paras and all(COMMIT_TRAILER.fullmatch(ln) for ln in paras[-1]):
        trailers = [tuple(COMMIT_TRAILER.fullmatch(ln).groups()) for ln in paras[-1]]
        paras.pop()
    body = [ln for p in paras for ln in p]
    return subject, rest, body, trailers


def check_commit_message(text, schema=None):
    """C32: `[red] T-001 title`, `[green] T-001 title` or `[refactor] T-001 title`, a blank line, an optional body, and
    optionally the trailer `Test-Change-Approved: <change request id>` in the last paragraph."""
    subject, rest, body, trailers = parse_commit_message(text)
    if not subject:
        return ["the commit message is empty"]
    errs = []
    if schema is not None:
        errs.extend(validate({"subject": subject, "trailers": dict(trailers)}, schema))
        if any("/subject" in e and "pattern" in e for e in errs):
            errs = [e for e in errs if not ("/subject" in e and "pattern" in e)]
            errs.append(f"/subject: {subject!r} must be '[red|green|refactor] T-NNN <title>'")
    if rest and rest[0].strip():
        errs.append("a blank line must follow the subject")
    keys = [k for k, _ in trailers]
    for k in sorted(set(keys)):
        if keys.count(k) > 1:
            errs.append(f"trailer '{k}' appears more than once")
    for ln in rest:
        if ln.startswith("Test-Change-Approved") and "Test-Change-Approved" not in keys:
            errs.append("the 'Test-Change-Approved' trailer belongs in the last paragraph, after a blank line")
            break
    return errs


SEMANTIC = {"C01": _check_c01, "C06": _check_c06, "C07": _check_c07, "C12": _check_c12, "C25": _check_c25,
            "C27": _check_c27, "C28": _check_c28, "C30": _check_c30, "C31": _check_c31}
SEMANTIC_LINE = {"C04": _check_c04_line}   # contract id -> check(doc, schema) for one JSONL line
SEMANTIC_TEXT = {"C32": check_commit_message}   # contract id -> check(text, schema) for a plain-text artifact


def validate_instance(contract_id, instance, schema):
    """Structural validation, then the contract's semantic checks (only when the structure is sound)."""
    if contract_id == "C16":
        errs = validate(instance, schema)
        return errs or (_check_c16(instance, schema) if isinstance(instance, dict) else [])
    if contract_id == "C26":
        if not isinstance(instance, dict):
            return validate(instance, schema)
        return _check_c26(instance, schema)
    errs = validate(instance, schema)
    if errs:
        return errs
    check = SEMANTIC.get(contract_id)
    return check(instance, schema) if check else []


# ------------------------------------------------------------------ JSONL


def validate_jsonl(text, schema, contract_id=None):
    """One JSON value per line; blank lines and lines starting with '#' are skipped. With a contract id, the
    line's semantic checks run when the structure is sound."""
    errs = []
    for n, line in enumerate(re.split(r"\r\n|\n|\r", text.lstrip("﻿")), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            doc = loads_strict(line)
        except ValueError as exc:
            msg = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
            errs.append(f"line {n}: invalid JSON ({msg})")
            continue
        found = validate(doc, schema)
        if not found and contract_id in SEMANTIC_LINE:
            found = SEMANTIC_LINE[contract_id](doc, schema)
        errs.extend(f"line {n} {e}" for e in found)
    return errs


# ------------------------------------------------------------------ Markdown


def _strip_ticks(cell):
    cell = cell.strip()
    if len(cell) > 1 and cell.startswith("`") and cell.endswith("`") and cell.count("`") == 2:
        return cell[1:-1]
    return cell


def _coerce(cell, kind):
    if kind == "list":
        items = [_strip_ticks(x) for x in cell.split(",")]
        items = [x for x in items if x]
        return [] if items in (["-"], ["none"]) else items
    cell = _strip_ticks(cell)
    if kind == "int":
        if cell == "":
            return None
        return int(cell) if re.fullmatch(r"-?\d+", cell) else cell
    return cell


def _norm_header(h):
    return " ".join(h.lower().split())


def _bind_headers(found, tspec):
    """Map the headers of a found table to the spec. Returns (canonical name per column, missing required names).

    `exact` (default): the found headers must equal the spec headers. `contains`: compared lower-cased, the spec
    headers (and `optional_headers`) may appear in any order among extra columns, which keep their own name."""
    if tspec.get("headers_match", "exact") == "exact":
        return (list(found), []) if found == tspec["headers"] else (None, list(tspec["headers"]))
    canon = {_norm_header(h): h for h in list(tspec["headers"]) + list(tspec.get("optional_headers", []))}
    names = [canon.get(_norm_header(h), h) for h in found]
    missing = [h for h in tspec["headers"] if h not in names]
    return (names if not missing else None), missing


def _table_rows(names, rows, coerce):
    out = []
    for r in rows:
        if not any(c.strip() for c in r):
            continue
        out.append({h: _coerce(c, coerce.get(h)) for h, c in zip(names, r)})
    return out


def read_table(text, table_spec, ci=False):
    """Find the first table matching the spec; return (rows as dicts, section) or None."""
    for section, headers, rows in fm.section_tables(_body_of(text)):
        names, _ = _bind_headers(headers, table_spec)
        if names is None:
            continue
        want = table_spec.get("section")
        if want:
            same = (section or "").lower() == want.lower() if ci else section == want
            if not same:
                continue
        return _table_rows(names, rows, table_spec.get("coerce", {})), section
    return None


def _body_of(text):
    try:
        return fm.parse(text)[1]
    except ValueError:
        return text


SECTIONS_KEYS = {"contract_id", "contract_version", "description", "front_matter", "coerce", "mode", "line_prefix",
                 "min_lines", "sections", "required_sections", "required_sections_when", "case_insensitive_titles",
                 "section_patterns", "line_rules", "forbidden", "forbidden_prose", "final_lines", "tables", "rules"}
TABLE_KEYS = {"name", "headers", "headers_match", "optional_headers", "row_def", "min_rows", "optional", "section", "coerce"}
RULE_KEYS = {
    "nonempty_sections": {"sections"},
    "forbid_text": {"pattern"},
    "forbid_rows": {"table", "match"},
    "require_text_if_rows": {"table", "match", "pattern"},
    "unique_column": {"table", "column"},
    "ids_match": {"table", "column", "sections_pattern"},
    "require_keys": {"keys"},
    "forbid_keys": {"keys"},
    "disjoint_scopes": {"table", "owner_column", "scope_column"},
    "row_requires": {"table", "when_column", "when_not_in", "column", "pattern"},
    "item_rule": {"section", "item_pattern", "require"},
    "section_text": {"section", "pattern"},
    "section_order": {"first", "then"},
    "lines_per_row": {"table", "match", "pattern"},
    "relpath_columns": {"table", "columns"},
    "min_rows": {"table", "min"},
    "exit_code": {"section", "expect"},
}
RULE_COMMON = {"type", "when", "message"}
PATTERN_KEYS = {"pattern", "sections_pattern", "item_pattern", "require"}


def check_sections_spec(spec):
    """Problems of a sections file (empty when every key is known, so a typo never silently turns a rule off)."""
    errs = []
    if not isinstance(spec, dict):
        return ["the sections file must be a JSON object"]

    def pat(p, where):
        try:
            compile_pattern(p)
        except (re.error, TypeError) as exc:
            errs.append(f"invalid pattern at {where}: {exc}")

    for k in spec:
        if k not in SECTIONS_KEYS:
            errs.append(f"unknown key '{k}' at the top level")
    for sp in spec.get("section_patterns", []):
        for k in sp:
            if k not in {"pattern", "min"}:
                errs.append(f"unknown key '{k}' in section_patterns")
        pat(sp.get("pattern", ""), "section_patterns")
    for title, rule in spec.get("line_rules", {}).items():
        for k in rule:
            if k not in {"pattern", "min"}:
                errs.append(f"unknown key '{k}' in line_rules['{title}']")
        pat(rule.get("pattern", ""), f"line_rules['{title}']")
    for p in spec.get("forbidden", []) + spec.get("forbidden_prose", []) + spec.get("final_lines", []):
        pat(p, "forbidden, forbidden_prose or final_lines")
    for i, t in enumerate(spec.get("tables", [])):
        for k in t:
            if k not in TABLE_KEYS:
                errs.append(f"unknown key '{k}' in tables[{i}]")
        if t.get("headers_match", "exact") not in ("exact", "contains"):
            errs.append(f"tables[{i}].headers_match must be 'exact' or 'contains'")
    for i, r in enumerate(spec.get("rules", [])):
        rt = r.get("type")
        if rt not in RULE_KEYS:
            errs.append(f"unknown rule type {rt!r} in rules[{i}]")
            continue
        for k in r:
            if k not in RULE_KEYS[rt] | RULE_COMMON:
                errs.append(f"unknown key '{k}' in rules[{i}] ({rt})")
        for k in PATTERN_KEYS & set(r):
            pat(r[k], f"rules[{i}].{k}")
    for i, r in enumerate(spec.get("required_sections_when", [])):
        for k in r:
            if k not in {"when", "sections"}:
                errs.append(f"unknown key '{k}' in required_sections_when[{i}]")
    return errs


def _build_sections(spec_path):
    try:
        spec = loads_strict(spec_path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ValueError(f"{spec_path.name}: invalid JSON ({exc})") from exc
    problems = check_sections_spec(spec)
    if problems:
        raise ValueError(f"{spec_path.name}: " + "; ".join(problems))
    return spec


def load_sections_spec(schema_path):
    schema_path = Path(schema_path)
    spec_path = schema_path.with_name(schema_path.name.replace(".schema.json", ".sections.json"))
    if not spec_path.is_file():
        raise ValueError(f"{spec_path.name}: missing (a Markdown contract needs a sections file next to its schema)")
    return _cached(spec_path, _build_sections)


def _when(rule, meta):
    return all(meta.get(k) in v for k, v in rule.get("when", {}).items())


def _matches(row, match):
    return all(row.get(k) in v for k, v in match.items())


def _validate_lines(text, schema, spec):
    prefix = spec.get("line_prefix", "- ")
    errs, count = [], 0
    for n, line in enumerate(re.split(r"\r\n|\n|\r", text.lstrip("﻿")), 1):
        if line.startswith(prefix):
            count += 1
            errs.extend(f"line {n} {e}" for e in validate(line, schema))
    if count < spec.get("min_lines", 0):
        errs.append(f"no lesson lines (lines starting with {prefix!r}) found; at least {spec.get('min_lines')} required")
    return errs


# ---- write scopes (the sizing check's overlap rule: same path, a directory above a path, or globs that meet)


def _scopes(cell):
    """Normalised paths of a write-scope cell (split on comma, semicolon, `<br>`; backticks removed)."""
    out = []
    for part in re.split(r"[,;]|<br\s*/?>", cell):
        path = part.strip().strip("`").strip().replace("\\", "/")
        path = re.sub(r"^\./", "", path)
        if path:
            out.append(path)
    return out


def _is_glob(path):
    return any(ch in path for ch in "*?[")


def _glob_prefix(path):
    cut = min(path.index(ch) for ch in "*?[" if ch in path)
    return path[: path.rfind("/", 0, cut) + 1]


def scopes_overlap(a, b):
    if a == b:
        return True
    for left, right in ((a, b), (b, a)):
        if left.endswith("/") and right.startswith(left):
            return True
        if _is_glob(left):
            if not _is_glob(right) and not right.endswith("/") and fnmatch.fnmatchcase(right, left):
                return True
            if _is_glob(right) or right.endswith("/"):
                base = _glob_prefix(right) if _is_glob(right) else right
                pre = _glob_prefix(left)
                if base.startswith(pre) or pre.startswith(base):
                    return True
    return False


_FENCED = re.compile(r"^[ \t]*```.*?^[ \t]*```[^\n]*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_EXIT = re.compile(r"\b(?:exit(?:ed)?(?:\s+(?:code|status))?|rc|returncode)\s*[:=]?\s*(-?\d+)", re.IGNORECASE | re.ASCII)


def prose(text):
    """The text without fenced code blocks and inline code spans (a report may quote what it must not contain)."""
    return _INLINE_CODE.sub("", _FENCED.sub("", text))


def cell_path(token):
    """The path inside a catalog cell token: a provider `kind:path` loses its kind and an `(active)` marker, a test
    `path::name` and a schema `path#anchor` lose the suffix. Empty for `-`."""
    tok = re.sub(r"\((?:active|real)\)", "", token.strip().strip("`"), flags=re.I).strip()
    tok = re.sub(r"^(stub|simulator|fixture|baseline):", "", tok)
    if re.match(r"^[a-z][a-z0-9+.-]*:(?![\\/])", tok) and "::" not in tok.split("/")[0]:
        return ""   # an unknown provider kind: the schema reports it, the path is not examined twice
    tok = tok.split("::")[0].split("#")[0].strip()
    return "" if tok in ("", "-") else tok


def _items(body):
    """Items of a list section as text, continuation lines joined to their item."""
    items = []
    for line in body.splitlines():
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            items.append([m.group(1)])
        elif items and line.strip():
            items[-1].append(line.strip())
    return [" ".join(parts) for parts in items]


def _find_title(titles, name):
    """Index of the first title that starts with `name` (both lower-cased), or None."""
    name = name.lower()
    for i, t in enumerate(titles):
        if t.lower().startswith(name):
            return i
    return None


def validate_markdown(text, schema, spec):
    """Validate a Markdown artifact: its header against the schema, then sections, tables and rules of the spec."""
    if spec.get("mode") == "lines":
        return _validate_lines(text, schema, spec)
    text = text.lstrip("﻿")
    errs = []
    meta, body = {}, text
    fmode = spec.get("front_matter", "required")
    if fmode == "required":
        try:
            meta, body = fm.parse(text)
        except ValueError as exc:
            return [f"front matter: {exc}"]
        errs.extend(f"front matter {e}" for e in validate(meta, schema))
    elif fmode == "bullets":
        try:
            meta = fm.header_bullets(text)
        except ValueError as exc:
            return [f"header: {exc}"]
        for key, kind in spec.get("coerce", {}).items():
            if key in meta:
                meta[key] = _coerce(meta[key], kind)
        errs.extend(f"header {e}" for e in validate(meta, schema))
    else:
        try:
            meta, body = fm.parse(text)
        except ValueError:
            meta, body = {}, text
    ci = bool(spec.get("case_insensitive_titles"))
    fold = (lambda s: s.lower()) if ci else (lambda s: s)
    try:
        titles = [fold(t) for t in fm.sections(body)]
        bodies = {fold(k): v for k, v in fm.section_bodies(body).items()}
        found_tables = [(fold(s) if s else s, h, r) for s, h, r in fm.section_tables(body)]
    except ValueError as exc:
        return errs + [f"body: {exc}"]
    # required sections, in order
    pos = 0
    for req in spec.get("sections", []):
        req = fold(req)
        try:
            idx = titles.index(req, pos)
        except ValueError:
            if req in titles:
                errs.append(f"sections: '{req}' is out of order (expected after '{titles[pos - 1] if pos else '(start)'}')")
            else:
                errs.append(f"sections: missing required section '{req}'")
            continue
        pos = idx + 1
    # required sections, in any order, case-insensitive, matched by title prefix (as the delegation tools do)
    wanted = list(spec.get("required_sections", []))
    for cond in spec.get("required_sections_when", []):
        if _when(cond, meta):
            wanted += cond["sections"]
    for name in wanted:
        if _find_title(titles, name) is None:
            errs.append(f"sections: missing required section '{name}'")
    for sp in spec.get("section_patterns", []):
        n = sum(1 for t in titles if compile_pattern(sp["pattern"]).search(t))
        if n < sp.get("min", 1):
            errs.append(f"sections: at least {sp.get('min', 1)} section(s) matching {sp['pattern']!r} required, found {n}")
    for title, rule in spec.get("line_rules", {}).items():
        if fold(title) not in bodies:
            continue
        n = sum(1 for ln in bodies[fold(title)].splitlines() if compile_pattern(rule["pattern"]).search(ln))
        if n < rule.get("min", 1):
            errs.append(f"section '{title}': at least {rule.get('min', 1)} line(s) matching {rule['pattern']!r} required, found {n}")
    for pat in spec.get("forbidden", []):
        for n, ln in enumerate(text.splitlines(), 1):
            if compile_pattern(pat).search(ln):
                errs.append(f"placeholder text matching {pat!r} on line {n}")
                break
    for pat in spec.get("forbidden_prose", []):
        for n, ln in enumerate(prose(text).splitlines(), 1):
            if compile_pattern(pat).search(ln):
                errs.append(f"placeholder text matching {pat!r} in the prose (prose line {n})")
                break
    finals = spec.get("final_lines")
    if finals:
        tail = [ln for ln in text.splitlines() if ln.strip()][-len(finals):]
        if len(tail) < len(finals) or not all(compile_pattern(p).search(ln) for p, ln in zip(finals, tail)):
            errs.append("final lines must match " + " then ".join(repr(p) for p in finals))
    # tables
    named = {}
    for tspec in spec.get("tables", []):
        name = tspec.get("name", "|".join(tspec["headers"]))
        hit, lacks = None, None
        for section, headers, rows in found_tables:
            if tspec.get("section") and section != fold(tspec["section"]):
                continue
            names, missing = _bind_headers(headers, tspec)
            if names is not None:
                hit = (names, rows)
                break
            lacks = lacks or missing
        if hit is None:
            if tspec.get("section") and fold(tspec["section"]) not in titles:
                continue   # the missing section is reported once, by the sections check
            if not tspec.get("optional"):
                extra = f"; the closest table lacks: {', '.join(lacks)}" if lacks and len(lacks) < len(tspec["headers"]) else ""
                errs.append(f"table '{name}' not found (expected columns: {' | '.join(tspec['headers'])}{extra})")
            continue
        names, rows = hit
        coerce = tspec.get("coerce", {})
        dicts = _table_rows(names, rows, coerce)
        named[name] = dicts
        if len(dicts) < tspec.get("min_rows", 0):
            errs.append(f"table '{name}' needs at least {tspec['min_rows']} row(s), found {len(dicts)}")
        if tspec.get("row_def"):
            row_schema = {"$ref": "#/$defs/" + tspec["row_def"], "$defs": schema.get("$defs", {})}
        else:
            row_schema = schema
        for i, row in enumerate(dicts, 1):
            errs.extend(f"table '{name}' row {i} {e}" for e in validate(row, row_schema))
    # rules
    for rule in spec.get("rules", []):
        rt = rule.get("type")
        if rt in ("forbid_rows", "require_text_if_rows", "unique_column", "ids_match", "disjoint_scopes", "row_requires",
                  "lines_per_row", "relpath_columns", "min_rows"):
            tbl = rule.get("table")
            if tbl not in named:
                continue
        if not _when(rule, meta):
            continue
        if rt == "nonempty_sections":
            for t in rule["sections"]:
                if fold(t) in bodies and not bodies[fold(t)].strip():
                    errs.append(f"section '{t}' must not be empty")
        elif rt == "forbid_text":
            for n, ln in enumerate(body.splitlines(), 1):
                if compile_pattern(rule["pattern"]).search(ln):
                    errs.append(f"text matching {rule['pattern']!r} is not allowed here (body line {n})")
                    break
        elif rt == "forbid_rows":
            hits = [i for i, r in enumerate(named[rule["table"]], 1) if _matches(r, rule["match"])]
            if hits:
                errs.append(rule.get("message", "forbidden rows present") + f" (table '{rule['table']}' rows {hits})")
        elif rt == "require_text_if_rows":
            if any(_matches(r, rule["match"]) for r in named[rule["table"]]) and not compile_pattern(rule["pattern"]).search(body):
                errs.append(rule.get("message", f"text matching {rule['pattern']!r} required"))
        elif rt == "lines_per_row":
            rows_n = sum(1 for r in named[rule["table"]] if _matches(r, rule["match"]))
            lines_n = sum(1 for ln in body.splitlines() if compile_pattern(rule["pattern"]).search(ln))
            if lines_n < rows_n:
                errs.append(rule.get("message", f"a line matching {rule['pattern']!r} is required per matching row")
                            + f" (table '{rule['table']}': {rows_n} row(s), {lines_n} line(s))")
        elif rt == "unique_column":
            seen = set()
            for r in named[rule["table"]]:
                v = r.get(rule["column"])
                if v in seen:
                    errs.append(f"table '{rule['table']}' column '{rule['column']}': duplicate value {v!r}")
                seen.add(v)
        elif rt == "ids_match":
            sec_ids = {}
            for tt in titles:
                m = compile_pattern(rule["sections_pattern"]).search(tt)
                if m:
                    sec_ids[m.group(1).lower()] = m.group(1)
            row_ids = {str(r.get(rule["column"])).lower(): str(r.get(rule["column"])) for r in named[rule["table"]]}
            for s in sorted(set(sec_ids) - set(row_ids)):
                errs.append(f"section '{sec_ids[s]}' has no row in table '{rule['table']}' (column '{rule['column']}')")
            for s in sorted(set(row_ids) - set(sec_ids) - {"none"}):
                errs.append(f"row '{row_ids[s]}' of table '{rule['table']}' has no matching section")
        elif rt == "disjoint_scopes":
            owned = []
            for r in named[rule["table"]]:
                owned.extend((str(r.get(rule["owner_column"])), p) for p in _scopes(str(r.get(rule["scope_column"], ""))))
            reported = set()
            for i, (ua, pa) in enumerate(owned):
                for ub, pb in owned[i + 1:]:
                    if ua != ub and scopes_overlap(pa, pb) and (ua, ub) not in reported:
                        reported.add((ua, ub))
                        errs.append(f"write scopes overlap: {ua} ({pa}) and {ub} ({pb})")
        elif rt == "row_requires":
            skip = {x.lower() for x in rule["when_not_in"]}
            for i, r in enumerate(named[rule["table"]], 1):
                if str(r.get(rule["when_column"], "")).strip().lower() in skip:
                    continue
                if not compile_pattern(rule["pattern"]).search(str(r.get(rule["column"], ""))):
                    errs.append(rule.get("message", f"column '{rule['column']}' must match {rule['pattern']!r}")
                                + f" (table '{rule['table']}' row {i})")
        elif rt == "min_rows":
            n = len(named[rule["table"]])
            if n < rule["min"]:
                errs.append(rule.get("message", f"table '{rule['table']}' needs at least {rule['min']} row(s)") + f" (found {n})")
        elif rt == "exit_code":
            sec = bodies.get(fold(rule["section"]))
            if sec is None:
                continue
            codes = [int(c) for c in _EXIT.findall(sec)]
            if not codes:
                errs.append(f"'{rule['section']}' states no exit code (write 'exit code N')")
            elif rule["expect"] == "nonzero" and not any(codes):
                errs.append(f"'{rule['section']}' has no non-zero exit code: the tests must fail before the code exists")
            elif rule["expect"] == "zero" and 0 not in codes:
                errs.append(f"'{rule['section']}' has no exit code 0: the checks must pass after the code")
        elif rt == "relpath_columns":
            for i, r in enumerate(named[rule["table"]], 1):
                for col in rule["columns"]:
                    v = r.get(col)
                    for tok in (v if isinstance(v, list) else [v] if isinstance(v, str) else []):
                        path = cell_path(tok)
                        if path and _bad_relpath(path):
                            errs.append(f"table '{rule['table']}' row {i} column '{col}': {path!r} is not a POSIX relative path "
                                        f"(no leading slash or ./, no backslash, drive letter or ..)")
        elif rt == "item_rule":
            sec = bodies.get(fold(rule["section"]))
            if sec is None:
                continue
            for item in _items(sec):
                if compile_pattern(rule["item_pattern"]).search(item) and not compile_pattern(rule["require"]).search(item):
                    errs.append(rule.get("message", f"item must match {rule['require']!r}") + f" (item: {item[:40]})")
        elif rt == "section_text":
            sec = bodies.get(fold(rule["section"]))
            if sec is not None and not compile_pattern(rule["pattern"]).search(sec):
                errs.append(rule.get("message", f"section '{rule['section']}' must match {rule['pattern']!r}"))
        elif rt == "section_order":
            a, b = _find_title(titles, rule["first"]), _find_title(titles, rule["then"])
            if a is not None and b is not None and b < a:
                errs.append(rule.get("message", f"section '{rule['then']}' comes before '{rule['first']}'"))
        elif rt == "require_keys":
            for k in rule["keys"]:
                if k not in meta:
                    errs.append(f"front matter requires '{k}' here")
        elif rt == "forbid_keys":
            for k in rule["keys"]:
                if k in meta:
                    errs.append(f"front matter must not contain '{k}'")
        else:
            errs.append(f"unknown rule type {rt!r} in the sections file")
    return errs


# ------------------------------------------------------------------ files and fixtures


def fixture_meta(path):
    """Return (why, expect) stated by a fixture, or (None, None). json: `_why`/`_expect`; md: `<!-- why: .. -->`; jsonl: `# why: ..`."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            return None, None
        if isinstance(doc, dict):
            return doc.get("_why"), doc.get("_expect")
        return None, None
    why = expect = None
    for line in text.splitlines()[:6]:
        s = line.strip()
        m = re.match(r"^(?:<!--\s*|#\s*)(why|expect):\s*(.*?)\s*(?:-->)?$", s)
        if m:
            if m.group(1) == "why":
                why = m.group(2)
            else:
                expect = m.group(2)
    return why, expect


def validate_file(path, schema_path, contract_id=None):
    """Validate an artifact file (.json, .jsonl or .md) against a contract schema file."""
    path = Path(path)
    schema = load_schema(schema_path)
    cid = contract_id or schema.get("contract_id")
    text = path.read_text(encoding="utf-8-sig")
    ext = path.suffix
    if ext == ".json":
        try:
            doc = loads_strict(text)
        except json.JSONDecodeError as exc:
            return [f"/: invalid JSON ({exc.msg}, line {exc.lineno})"]
        except ValueError as exc:
            return [f"/: invalid JSON ({exc})"]
        if isinstance(doc, dict):
            doc = {k: v for k, v in doc.items() if k not in FIXTURE_KEYS}
        return validate_instance(cid, doc, schema)
    if ext == ".jsonl":
        return validate_jsonl(text, schema, cid)
    if ext == ".md":
        return validate_markdown(text, schema, load_sections_spec(schema_path))
    if ext == ".txt" and cid in SEMANTIC_TEXT:
        return SEMANTIC_TEXT[cid](text, schema)
    return [f"/: unsupported file type {ext!r} (expected .json, .jsonl or .md)"]


def find_schema(contracts_dir, contract_id):
    found = sorted(Path(contracts_dir).glob(f"{contract_id}-*.schema.json"))
    return found[0] if found else None
