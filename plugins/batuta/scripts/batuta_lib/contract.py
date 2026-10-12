"""Stdlib validator for the JSON Schema subset used by Batuta data contracts (contracts/).

Supported keywords (draft 2020-12 semantics): type, enum, const, pattern, required, properties,
additionalProperties (bool or schema), items, minItems, minimum, maximum, maxLength, minLength, $ref to
`#/$defs/<name>` in the same file, $defs (root only), description. Root-only metadata: $schema, $id, title,
contract_id, contract_version. Any other keyword makes `load_schema` refuse the schema, so a schema never
silently promises more than the validator checks.

Error strings look like `/path/to/field: message` (JSON pointer; the root is `/`). Markdown and JSONL helpers
prefix them with where they came from (`front matter`, `table 'T' row 2`, `line 5`).
"""
import json
import re
from pathlib import Path

from batuta_lib import frontmatter as fm

KEYWORDS = {"type", "enum", "const", "pattern", "required", "properties", "additionalProperties", "items",
            "minItems", "minimum", "maximum", "maxLength", "minLength", "$ref", "$defs", "description"}
ROOT_META = {"$schema", "$id", "title", "contract_id", "contract_version"}
FIXTURE_KEYS = ("_why", "_expect", "_recorded")
TYPES = {"string", "integer", "number", "boolean", "null", "object", "array"}


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
            re.compile(node["pattern"])
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


def check_schema(schema):
    """Return a list of problems (empty when the schema stays inside the supported subset)."""
    errs = []
    _check(schema, "", schema if isinstance(schema, dict) else {}, errs, True)
    return errs


def load_schema(path):
    path = Path(path)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name}: invalid JSON ({exc})") from exc
    problems = check_schema(schema)
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return schema


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
        if "pattern" in sch and not re.search(sch["pattern"], inst):
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
    names = [c.get("name") for c in inst.get("candidates", [])]
    if inst["decision"] != "open" and inst["decision"] not in names:
        return [f"/decision: '{inst['decision']}' is neither 'open' nor a candidate name"]
    return []


def _text_ok(v):
    """A reason: a non-blank string, or an object with a non-blank string 'en'."""
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, dict):
        en = v.get("en")
        return isinstance(en, str) and bool(en.strip())
    return False


def check_declaration_states(states, path, can_be_absent):
    """The availability rule shared by C23 and C26: a component that can be absent declares `available` and at
    least one non-available state; a state is declared once; the test ids are required by the schema."""
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
    errs = []
    if not (inst.get("contracts") or inst.get("components")):
        return ["/: readiness needs at least one entry in contracts or components"]
    for key in ("contracts", "components"):
        for i, e in enumerate(inst.get(key, [])):
            here = f"/{key}/{i}"
            state, prov = e["state"], e["provenance"]
            if state != "available" and not _text_ok(e["reason"]):
                errs.append(f"{here}/reason: state '{state}' must state a reason (a non-blank text)")
            if state == "available" and prov != "real":
                errs.append(f"{here}/provenance: an available entry is served by the real producer (provenance 'real')")
            if state == "partial" and not e.get("missing"):
                errs.append(f"{here}/missing: a partial entry lists what is missing")
            if state == "missing" and prov is not None:
                errs.append(f"{here}/provenance: nothing answered, so provenance must be null when the state is missing")
            if state in ("synthetic", "provider") and prov not in ("stub", "simulator", "fixture", "baseline"):
                errs.append(f"{here}/provenance: a synthetic entry is served by a stub, simulator, fixture or baseline")
            if state == "training" and prov not in ("real", "baseline"):
                errs.append(f"{here}/provenance: a training model answers with the released model (real) or the baseline")
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


def unit_providers(inv):
    """Map contract id to the set of unit ids that provide it (a unit's own provides, or its components' provides)."""
    comp_unit = {c.get("id"): c.get("unit") for c in inv.get("components", [])}
    out = {}
    for u in inv.get("units", []):
        for c in u.get("provides", []):
            out.setdefault(c, set()).add(u["id"])
    for c in inv.get("components", []):
        for cid in c.get("provides", []):
            if comp_unit.get(c["id"]):
                out.setdefault(cid, set()).add(comp_unit[c["id"]])
    return out


def _check_c23(inst, schema):
    errs = []
    comp_ids = [c["id"] for c in inst["components"]]
    unit_ids = [u["id"] for u in inst["units"]]
    contract_ids = [c["id"] for c in inst["contracts"]]
    for key, ids in (("components", comp_ids), ("units", unit_ids), ("contracts", contract_ids), ("repos", [r["id"] for r in inst["repos"]])):
        seen = set()
        for i, x in enumerate(ids):
            if x in seen:
                errs.append(f"/{key}/{i}/id: duplicate {key[:-1]} id '{x}'")
            seen.add(x)
    for i, c in enumerate(inst["components"]):
        if c["unit"] not in unit_ids:
            errs.append(f"/components/{i}/unit: unknown unit '{c['unit']}'")
        for field in ("provides", "consumes"):
            for cid in c[field]:
                if cid not in contract_ids:
                    errs.append(f"/components/{i}/{field}: unknown contract '{cid}'")
        if c.get("can_be_absent"):
            if "availability" not in c:
                errs.append(f"/components/{i}: a component that can be absent must declare availability")
            else:
                errs.extend(check_declaration_states(c["availability"], f"/components/{i}/availability", True))
        elif "availability" in c:
            errs.extend(check_declaration_states(c["availability"], f"/components/{i}/availability", False))
    for i, u in enumerate(inst["units"]):
        for cid in u["components"]:
            if cid not in comp_ids:
                errs.append(f"/units/{i}/components: unknown component '{cid}'")
        for field in ("provides", "consumes"):
            for cid in u[field]:
                if cid not in contract_ids:
                    errs.append(f"/units/{i}/{field}: unknown contract '{cid}'")
    if errs:
        return errs
    providers = unit_providers(inst)
    for i, u in enumerate(inst["units"]):
        for cid in u["consumes"]:
            if not providers.get(cid):
                errs.append(f"/units/{i}/consumes: unit '{u['id']}' consumes contract '{cid}' that nobody provides")
    return errs


SEMANTIC = {"C12": _check_c12, "C23": _check_c23, "C25": _check_c25, "C27": _check_c27, "C28": _check_c28}


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


def validate_jsonl(text, schema):
    """One JSON value per line; blank lines and lines starting with '#' are skipped."""
    errs = []
    for n, line in enumerate(re.split(r"\r\n|\n|\r", text), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as exc:
            errs.append(f"line {n}: invalid JSON ({exc.msg})")
            continue
        errs.extend(f"line {n} {e}" for e in validate(doc, schema))
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
        return [] if items == ["-"] else items
    cell = _strip_ticks(cell)
    if kind == "int":
        if cell == "":
            return None
        return int(cell) if re.fullmatch(r"-?\d+", cell) else cell
    return cell


def read_table(text, table_spec):
    """Find the first table whose headers equal table_spec['headers']; return (rows as dicts, section) or None."""
    for section, headers, rows in fm.section_tables(_body_of(text)):
        if headers == table_spec["headers"]:
            if table_spec.get("section") and section != table_spec["section"]:
                continue
            coerce = table_spec.get("coerce", {})
            return [{h: _coerce(c, coerce.get(h)) for h, c in zip(headers, r)} for r in rows], section
    return None


def _body_of(text):
    try:
        return fm.parse(text)[1]
    except ValueError:
        return text


def load_sections_spec(schema_path):
    schema_path = Path(schema_path)
    spec_path = schema_path.with_name(schema_path.name.replace(".schema.json", ".sections.json"))
    if not spec_path.is_file():
        raise ValueError(f"{spec_path.name}: missing (a Markdown contract needs a sections file next to its schema)")
    try:
        return json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{spec_path.name}: invalid JSON ({exc})") from exc


def _when(rule, meta):
    return all(meta.get(k) in v for k, v in rule.get("when", {}).items())


def _matches(row, match):
    return all(row.get(k) in v for k, v in match.items())


def _validate_lines(text, schema, spec):
    prefix = spec.get("line_prefix", "- ")
    errs, count = [], 0
    for n, line in enumerate(re.split(r"\r\n|\n|\r", text), 1):
        if line.startswith(prefix):
            count += 1
            errs.extend(f"line {n} {e}" for e in validate(line, schema))
    if count < spec.get("min_lines", 0):
        errs.append(f"no lesson lines (lines starting with {prefix!r}) found; at least {spec.get('min_lines')} required")
    return errs


def validate_markdown(text, schema, spec):
    """Validate a Markdown artifact: front matter against the schema, then sections, tables and rules of the spec."""
    if spec.get("mode") == "lines":
        return _validate_lines(text, schema, spec)
    errs = []
    meta, body = {}, text
    if spec.get("front_matter", "required") == "required":
        try:
            meta, body = fm.parse(text)
        except ValueError as exc:
            return [f"front matter: {exc}"]
        errs.extend(f"front matter {e}" for e in validate(meta, schema))
    else:
        try:
            meta, body = fm.parse(text)
        except ValueError:
            meta, body = {}, text
    try:
        titles = fm.sections(body)
        bodies = fm.section_bodies(body)
        found_tables = fm.section_tables(body)
    except ValueError as exc:
        return errs + [f"body: {exc}"]
    # required sections, in order
    pos = 0
    for req in spec.get("sections", []):
        try:
            idx = titles.index(req, pos)
        except ValueError:
            if req in titles:
                errs.append(f"sections: '{req}' is out of order (expected after '{titles[pos - 1] if pos else '(start)'}')")
            else:
                errs.append(f"sections: missing required section '{req}'")
            continue
        pos = idx + 1
    for sp in spec.get("section_patterns", []):
        n = sum(1 for t in titles if re.search(sp["pattern"], t))
        if n < sp.get("min", 1):
            errs.append(f"sections: at least {sp.get('min', 1)} section(s) matching {sp['pattern']!r} required, found {n}")
    for title, rule in spec.get("line_rules", {}).items():
        if title not in bodies:
            continue
        n = sum(1 for ln in bodies[title].splitlines() if re.search(rule["pattern"], ln))
        if n < rule.get("min", 1):
            errs.append(f"section '{title}': at least {rule.get('min', 1)} line(s) matching {rule['pattern']!r} required, found {n}")
    for pat in spec.get("forbidden", []):
        for n, ln in enumerate(text.splitlines(), 1):
            if re.search(pat, ln):
                errs.append(f"placeholder text matching {pat!r} on line {n}")
                break
    finals = spec.get("final_lines")
    if finals:
        tail = [ln for ln in text.splitlines() if ln.strip()][-len(finals):]
        if len(tail) < len(finals) or not all(re.search(p, ln) for p, ln in zip(finals, tail)):
            errs.append("final lines must match " + " then ".join(repr(p) for p in finals))
    # tables
    named = {}
    for tspec in spec.get("tables", []):
        name = tspec.get("name", "|".join(tspec["headers"]))
        hit = None
        for section, headers, rows in found_tables:
            if headers == tspec["headers"] and (not tspec.get("section") or section == tspec["section"]):
                hit = (headers, rows)
                break
        if hit is None:
            if not tspec.get("optional"):
                errs.append(f"table '{name}' not found (expected columns: {' | '.join(tspec['headers'])})")
            continue
        headers, rows = hit
        coerce = tspec.get("coerce", {})
        dicts = [{h: _coerce(c, coerce.get(h)) for h, c in zip(headers, r)} for r in rows]
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
        if rt in ("forbid_rows", "require_text_if_rows", "unique_column", "ids_match"):
            tbl = rule.get("table")
            if tbl not in named:
                continue
        if not _when(rule, meta):
            continue
        if rt == "nonempty_sections":
            for t in rule["sections"]:
                if t in bodies and not bodies[t].strip():
                    errs.append(f"section '{t}' must not be empty")
        elif rt == "forbid_text":
            for n, ln in enumerate(body.splitlines(), 1):
                if re.search(rule["pattern"], ln):
                    errs.append(f"text matching {rule['pattern']!r} is not allowed here (body line {n})")
                    break
        elif rt == "forbid_rows":
            hits = [i for i, r in enumerate(named[rule["table"]], 1) if _matches(r, rule["match"])]
            if hits:
                errs.append(rule.get("message", "forbidden rows present") + f" (table '{rule['table']}' rows {hits})")
        elif rt == "require_text_if_rows":
            if any(_matches(r, rule["match"]) for r in named[rule["table"]]) and not re.search(rule["pattern"], body):
                errs.append(rule.get("message", f"text matching {rule['pattern']!r} required"))
        elif rt == "unique_column":
            seen = set()
            for r in named[rule["table"]]:
                v = r.get(rule["column"])
                if v in seen:
                    errs.append(f"table '{rule['table']}' column '{rule['column']}': duplicate value {v!r}")
                seen.add(v)
        elif rt == "ids_match":
            sec_ids = set()
            for t in titles:
                m = re.search(rule["sections_pattern"], t)
                if m:
                    sec_ids.add(m.group(1))
            row_ids = {r.get(rule["column"]) for r in named[rule["table"]]}
            for s in sorted(sec_ids - row_ids):
                errs.append(f"section '{s}' has no row in table '{rule['table']}' (column '{rule['column']}')")
            for s in sorted(row_ids - sec_ids - {None}):
                errs.append(f"row '{s}' of table '{rule['table']}' has no matching section")
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
    text = path.read_text(encoding="utf-8")
    ext = path.suffix
    if ext == ".json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            return [f"/: invalid JSON ({exc.msg}, line {exc.lineno})"]
        if isinstance(doc, dict):
            doc = {k: v for k, v in doc.items() if k not in FIXTURE_KEYS}
        return validate_instance(cid, doc, schema)
    if ext == ".jsonl":
        return validate_jsonl(text, schema)
    if ext == ".md":
        return validate_markdown(text, schema, load_sections_spec(schema_path))
    return [f"/: unsupported file type {ext!r} (expected .json, .jsonl or .md)"]


def find_schema(contracts_dir, contract_id):
    found = sorted(Path(contracts_dir).glob(f"{contract_id}-*.schema.json"))
    return found[0] if found else None
