"""Area `contract`: lint the data contracts and a project's artifacts, validate one artifact against a contract,
compute the parallel waves.

Module layout contract (shared with batuta.py): AREA, HELP, register(subparsers), and functions callable without
the CLI. `register` receives the area's verb sub-parsers action; each verb sets `func(args) -> exit code`. Verbs print
tag-prefixed lines (OK, WARN, FAIL, ...) and, with --json, the C20 object, through `batuta_lib.output`. Exit codes:
0 ok, 1 failure, 2 warnings.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from batuta_lib import config
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm
from batuta_lib.output import emit, exit_code, item  # noqa: F401  (item and exit_code are part of this module's surface)

AREA = "contract"
HELP = "Data contracts: lint schemas, fixtures and a project's artifacts, validate an artifact, compute parallel waves."

MIN_VALID, MIN_INVALID = 2, 3
NONE_CELLS = {"", "-", "n/a", "na", "none", "no"}
CATALOG_PATH = "docs/contracts/catalog.md"
READINESS_PATHS = ("data/derived/readiness.json", "docs/design/readiness.json")
TECH_GLOB = "docs/design/tech/*.json"


def _short(errors, n=2):
    shown = "; ".join(errors[:n])
    return shown + (f"; and {len(errors) - n} more" if len(errors) > n else "")


# ------------------------------------------------------------------ locating contracts


def _own_contracts_dir():
    """The contracts shipped with this plugin: `contracts/` inside the plugin folder, never the repository root."""
    return config.contracts_dir()


def _contracts_dirs(root):
    """Directories searched for a contract id: the project's `contracts/` (when a root is given), then the plugin's."""
    dirs = []
    if root is not None:
        dirs.append(Path(root) / "contracts")
    dirs.append(_own_contracts_dir())
    return dirs


def _find_contract(root, cid):
    for d in _contracts_dirs(root):
        sp = core.find_schema(d, cid) if d.is_dir() else None
        if sp is not None:
            return sp
    return None


def _own_spec(cid):
    """(schema, sections spec or None) of a built-in contract loaded from the plugin."""
    sp = core.find_schema(_own_contracts_dir(), cid)
    if sp is None:
        raise ValueError(f"{cid} schema not found in {_own_contracts_dir()}")
    has_sections = sp.with_name(sp.name.replace(".schema.json", ".sections.json")).is_file()
    return core.load_schema(sp), (core.load_sections_spec(sp) if has_sections else None)


# ------------------------------------------------------------------ lint of a contracts folder


def _canon(node):
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k not in core.KEYWORDS or k in ("description", "$defs"):
            continue
        if k == "properties":
            out[k] = {n: _canon(s) for n, s in v.items()}
        elif k == "items" or (k == "additionalProperties" and isinstance(v, dict)):
            out[k] = _canon(v)
        else:
            out[k] = v
    return out


def _fixtures(cdir, cid):
    d = cdir / "fixtures" / cid
    return sorted(p for p in d.iterdir() if p.is_file()) if d.is_dir() else []


def _lint_contract(cdir, sp, readme_text, items, root):
    cid = sp.name.split("-")[0]
    name = sp.name[len(cid) + 1:-len(".schema.json")]
    rel = sp.relative_to(root).as_posix()
    catalog = Path(cdir.name) / "README.md"
    ok = True
    if readme_text is not None and not re.search(rf"\b{cid}\b", readme_text):
        items.append(item("FAIL", f"{cid} is not listed in the catalog ({catalog.as_posix()})", rel))
        ok = False
    try:
        schema = core.load_schema(sp)
    except ValueError as exc:
        items.append(item("FAIL", f"{cid} schema does not load: {exc}", rel))
        return None
    if schema.get("contract_id") != cid:
        items.append(item("FAIL", f"{cid} schema has contract_id {schema.get('contract_id')!r}, expected {cid!r}", rel))
        ok = False
    if not re.fullmatch(r"\d+\.\d+", str(schema.get("contract_version", ""))):
        items.append(item("FAIL", f"{cid} schema needs a contract_version like '1.0'", rel))
        ok = False
    if sp.with_name(sp.name.replace(".schema.json", ".sections.json")).is_file():
        try:
            core.load_sections_spec(sp)
        except ValueError as exc:
            items.append(item("FAIL", f"{cid} sections file does not load: {exc}", rel))
            return None
    valid = invalid = 0
    for fx in _fixtures(cdir, cid):
        label = f"{cid}/{fx.name}"
        fxrel = fx.relative_to(root).as_posix()
        if fx.name.startswith("valid-"):
            valid += 1
            try:
                errs = core.validate_file(fx, sp)
            except ValueError as exc:
                items.append(item("FAIL", f"{label}: cannot validate: {exc}", fxrel))
                ok = False
                continue
            if errs:
                items.append(item("FAIL", f"{label}: expected valid, got {len(errs)} error(s): {_short(errs)}", fxrel))
                ok = False
        elif fx.name.startswith("invalid-"):
            invalid += 1
            why, expect = core.fixture_meta(fx)
            if not why:
                items.append(item("FAIL", f"{label} states no reason (add _why, a why comment, or a '# why:' line)", fxrel))
                ok = False
            try:
                errs = core.validate_file(fx, sp)
            except ValueError as exc:
                items.append(item("FAIL", f"{label}: cannot validate: {exc}", fxrel))
                ok = False
                continue
            if not errs:
                items.append(item("FAIL", f"{label}: expected invalid but it validated", fxrel))
                ok = False
            elif expect and not any(expect in e for e in errs):
                items.append(item("FAIL", f"{label}: errors do not mention {expect!r}: {_short(errs)}", fxrel))
                ok = False
            elif len(errs) > 1 and len({e.split(':')[0] for e in errs}) > 1 and not expect:
                items.append(item("WARN", f"{label}: fails for {len(errs)} reasons and states none to look for", fxrel))
        else:
            items.append(item("WARN", f"{label}: fixture name must start with valid- or invalid-", fxrel))
    if valid < MIN_VALID or invalid < MIN_INVALID:
        items.append(item("FAIL", f"{cid} needs at least {MIN_VALID} valid and {MIN_INVALID} invalid fixtures "
                                  f"(found {valid} and {invalid})", rel))
        ok = False
    if ok:
        items.append(item("OK", f"{cid} {name}: schema loads; {valid} valid and {invalid} invalid fixture(s) behave as labeled", rel))
    return schema


def _path(schema, *keys):
    node = schema
    for k in keys:
        node = node.get(k, {}) if isinstance(node, dict) else {}
    return node or None


def _gate_sets(loaded):
    out = {}
    if "C01" in loaded:
        out["C01 gates.critical"] = _path(loaded["C01"], "properties", "gates", "properties", "critical", "items", "enum")
    if "C09" in loaded:
        out["C09 gate"] = _path(loaded["C09"], "properties", "gate", "enum")
    if "C10" in loaded:
        c10 = loaded["C10"]
        phases = _path(c10, "properties", "phase", "enum")
        out["C10 phase"] = [g for g in phases if g != "done"] if phases else None
        gates = _path(c10, "properties", "gates", "properties")
        out["C10 gates"] = list(gates) if gates else None
        out["C10 waivers"] = _path(c10, "properties", "waivers", "items", "properties", "gate", "enum")
    return out


# (label, [(contract id, path into its schema)], canonical value or None): every listed value must be identical (and equal
# to the canonical value when there is one)
EQUALITIES = [
    ("the catalog id pattern of C21 Contracts, C22 id and C23 Boundaries",
     [("C21", ("properties", "Contracts", "items", "pattern")), ("C22", ("properties", "id", "pattern")),
      ("C23", ("$defs", "boundary_row", "properties", "Contract ID", "pattern"))], None),
    ("the exact-version pattern of C23 and C25",
     [("C23", ("$defs", "technology_row", "properties", "Version", "pattern")), ("C25", ("properties", "version", "pattern")),
      ("C25", ("$defs", "candidate", "properties", "version", "pattern"))], None),
    ("the lane pattern of C01 and C30",
     [("C01", ("$defs", "lane", "pattern")), ("C30", ("$defs", "lane", "pattern"))], None),
    ("the environment variable name pattern of C01 and C30",
     [("C01", ("$defs", "provider", "properties", "credential_env", "pattern")),
      ("C30", ("$defs", "request", "properties", "credential_env", "pattern"))], None),
    ("the availability states of C26 and C27",
     [("C26", ("$defs", "state", "enum")), ("C27", ("$defs", "entry", "properties", "state", "enum"))], None),
    ("the change-request id pattern of C07, C32 and C33",
     [("C07", ("$defs", "entry", "properties", "change_request", "pattern")),
      ("C32", ("properties", "trailers", "properties", "Test-Change-Approved", "pattern")),
      ("C33", ("$defs", "request_row", "properties", "Id", "pattern"))], None),
    ("the relative path pattern of C01, C04, C07, C28 and C30 (and the validator's)",
     [("C01", ("properties", "coordination_root", "pattern")), ("C01", ("properties", "knowledge_manifest", "pattern")),
      ("C04", ("$defs", "ledger_row", "properties", "Brief", "pattern")), ("C04", ("$defs", "ledger_row", "properties", "Report", "pattern")),
      ("C07", ("$defs", "entry", "properties", "path", "pattern")), ("C28", ("properties", "io_contract", "pattern")),
      ("C30", ("$defs", "request", "properties", "brief", "pattern")), ("C30", ("$defs", "request", "properties", "report", "pattern")),
      ("C30", ("$defs", "request", "properties", "write_scope", "items", "pattern")),
      ("C30", ("$defs", "result", "properties", "report", "pattern")), ("C30", ("$defs", "result", "properties", "patch", "pattern"))],
     core.REL_PATH_PATTERN),
]

# (label, (contract id, path), (contract id, path)): every value of the first is a value of the second
SUBSETS = [
    ("every C30 result status is a C04 status (a dispatch outcome is written to the ledger as it is)",
     ("C30", ("$defs", "result", "properties", "status", "enum")), ("C04", ("$defs", "ledger_row", "properties", "Status", "enum"))),
]


def _lint_consistency(loaded, items):
    if "C01" in loaded and "C14" in loaded:
        budgets = loaded["C01"].get("properties", {}).get("budgets")
        if _canon(budgets) != _canon(loaded["C14"]):
            items.append(item("FAIL", "C14 does not equal the budgets block of C01 (type, required, properties)", "contracts"))
        else:
            items.append(item("OK", "C14 equals the budgets block of C01", "contracts"))
    gates = {k: v for k, v in _gate_sets(loaded).items() if v is not None}
    if len(gates) > 1:
        first_name, first = next(iter(gates.items()))
        diff = [k for k, v in gates.items() if v != first]
        if diff:
            items.append(item("FAIL", f"gate names differ: {first_name} is {first}, but " + "; ".join(f"{k} is {gates[k]}" for k in diff),
                              "contracts"))
        else:
            items.append(item("OK", f"gate names are the same in {', '.join(gates)} ({len(first)} lifecycle gates)", "contracts"))
    for label, refs, canonical in EQUALITIES:
        values = []
        for cid, keys in refs:
            if cid in loaded:
                values.append((f"{cid} {'/'.join(keys)}", _path(loaded[cid], *keys)))
        if len(values) < 2:
            continue
        reference = canonical if canonical is not None else values[0][1]
        if any(v is None for _, v in values) or any(v != reference for _, v in values):
            items.append(item("FAIL", f"{label} differ: " + "; ".join(f"{n} = {v!r}" for n, v in values), "contracts"))
        else:
            items.append(item("OK", f"{label} are equal", "contracts"))
    for label, (a_id, a_keys), (b_id, b_keys) in SUBSETS:
        if a_id in loaded and b_id in loaded:
            a, b = _path(loaded[a_id], *a_keys), _path(loaded[b_id], *b_keys)
            missing = sorted(set(a or []) - set(b or []))
            if a is None or b is None or missing:
                items.append(item("FAIL", f"{label}: not in {b_id}: {', '.join(missing) or '(path not found)'}", "contracts"))
            else:
                items.append(item("OK", label, "contracts"))


def _lint_hooks(plugin_dir, items):
    """Handler discovery (C31): the area modules define `HOOKS = {id: handler}`, an id is defined once, and every handler id
    that `hooks/hooks.json` runs resolves to one of them. The modules are read, never imported."""
    plugin_dir = Path(plugin_dir)
    areas_dir = plugin_dir / "scripts" / "batuta_lib" / "areas"
    found, problems = core.discover_hook_ids(areas_dir) if areas_dir.is_dir() else ({}, [])
    items.extend(item("FAIL", f"hook handlers: {p}", "hooks") for p in problems)
    if not problems:
        items.append(item("OK", f"{len(found)} hook handler id(s) defined in the area modules, each once", "hooks"))
    hooks_json = plugin_dir / "hooks" / "hooks.json"
    if not hooks_json.is_file():
        return
    rel = "hooks/hooks.json"
    schema_path = core.find_schema(_own_contracts_dir(), "C31")
    errs = core.validate_file(hooks_json, schema_path, "C31")
    if errs:
        items.extend(item("FAIL", f"{rel}: {e}", rel) for e in errs)
        return
    doc = core.loads_strict(hooks_json.read_text(encoding="utf-8-sig"))
    ids = [core.hook_entry_id(h) for groups in doc["hooks"].values() for g in groups for h in g["hooks"]]
    unknown = sorted({i for i in ids if i not in found})
    if unknown:
        items.extend(item("FAIL", f"{rel}: handler id '{i}' is defined by no area module (HOOKS = {{id: handler}})", rel) for i in unknown)
    else:
        items.append(item("OK", f"{rel} satisfies C31; its {len(ids)} entr(ies) resolve to a handler each", rel))


def _lint_contracts_folder(cdir, root, items):
    readme = cdir / "README.md"
    readme_text = readme.read_text(encoding="utf-8") if readme.is_file() else None
    if readme_text is None:
        items.append(item("FAIL", "contracts/README.md (the catalog) is missing", "contracts/README.md"))
    schemas = sorted(p for p in cdir.glob("C*-*.schema.json") if re.match(r"^C\d+-", p.name))
    if not schemas:
        items.append(item("FAIL", "no contract schemas (C<nn>-<name>.schema.json) found", "contracts"))
    loaded = {}
    for sp in schemas:
        s = _lint_contract(cdir, sp, readme_text, items, root)
        if s is not None:
            loaded[sp.name.split("-")[0]] = s
    _lint_consistency(loaded, items)


# ------------------------------------------------------------------ reading a Markdown contract's table


def _body_rows(path, cid, table_name, items, label):
    """Validate a Markdown file against its built-in contract; return the named table's rows, or None after FAIL items."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        items.append(item("FAIL", f"cannot read {label} file: {exc}", Path(path).as_posix()))
        return None
    schema, spec = _own_spec(cid)
    errs = core.validate_markdown(text, schema, spec)
    if errs:
        items.extend(item("FAIL", f"{label}: {e}", Path(path).as_posix()) for e in errs)
        return None
    tspec = next(t for t in spec["tables"] if t["name"] == table_name)
    found = core.read_table(text, tspec, bool(spec.get("case_insensitive_titles")))
    return found[0] if found else []


def read_catalog(path, items=None):
    items = [] if items is None else items
    return _body_rows(path, "C22", "Catalog", items, "catalog")


def read_sizing_units(path, items=None):
    items = [] if items is None else items
    return _body_rows(path, "C23", "Parallel units", items, "sizing")


# ------------------------------------------------------------------ project artifacts


def _sha256_lf(path):
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def catalog_path_items(rows, root):
    """The existence rules of the catalog check: the schema file, every producer and consumer test and the provider path
    exist under the repository root. Returns FAIL items."""
    out = []
    root = Path(root)
    for row in rows:
        cid = row["id"]
        targets = [("schema file", row["schema file"])]
        targets += [("producer test", t) for t in row["producer test"]] + [("consumer test", t) for t in row["consumer test"]]
        targets += [("provider", row["provider"])]
        for column, value in targets:
            p = core.cell_path(value)
            if p and not (root / p).exists():
                out.append(item("FAIL", f"{cid}: {column} path not found: {p}", CATALOG_PATH))
    return out


def _tech_items(root, matrix_rows, items):
    for f in sorted(Path(root).glob(TECH_GLOB)):
        rel = f.relative_to(root).as_posix()
        errs = core.validate_file(f, core.find_schema(_own_contracts_dir(), "C25"))
        if errs:
            items.extend(item("FAIL", f"{rel}: {e}", rel) for e in errs)
            continue
        doc = core.loads_strict(f.read_text(encoding="utf-8-sig"))
        if matrix_rows is not None and not any(r["Tool"] == doc["tool"] and r["Version"] == doc["version"] for r in matrix_rows):
            items.append(item("FAIL", f"{rel}: {doc['tool']} {doc['version']} is not a row of the sizing's Technology matrix", rel))
        else:
            items.append(item("OK", f"{rel} satisfies C25", rel))


def _read_matrix(sizing_path):
    """Rows of the Technology matrix of a sizing that already validated, or None."""
    text = Path(sizing_path).read_text(encoding="utf-8-sig")
    schema, spec = _own_spec("C23")
    tspec = next(t for t in spec["tables"] if t["name"] == "Technology matrix")
    found = core.read_table(text, tspec, True)
    return found[0] if found else None


def _interface_ids(spec_text):
    """The catalog ids named by a spec's Interfaces section (first token of each list item), or [] for none."""
    body = fm.section_bodies(_body_text(spec_text)).get("Interfaces", "")
    ids = []
    for ln in body.splitlines():
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+([a-z0-9][a-z0-9-]*)(?:\s|:|$)", ln)
        if m and m.group(1) != "none":
            ids.append(m.group(1))
    return ids


def _body_text(text):
    try:
        return fm.parse(text)[1]
    except ValueError:
        return text


def _first_existing(root, rels):
    for rel in rels:
        if (Path(root) / rel).is_file():
            return Path(root) / rel
    return None


def _sizing_candidates(root, coord):
    root = Path(root)
    found = []
    for pattern in (f"{coord}/sizing.md", f"{coord}/*/sizing.md", "sizing.md"):
        found.extend(sorted(root.glob(pattern)))
    return found


def lint(root=None, sizing=None, catalog=None, readiness=None):
    """Lint the plugin's own contracts (root None), or a project under `root`: its contracts/ folder when present,
    its configuration, `sizing.md` (C23), the contract catalog (C22), the readiness document (C27), the technology
    decisions (C25), and the specs and tasks that name catalog ids, with the cross-file rules between them.
    Returns a list of items."""
    items = []
    if root is None:
        cdir = _own_contracts_dir()
        _lint_contracts_folder(cdir, cdir.parent, items)
        _lint_hooks(cdir.parent, items)
        return items
    root = Path(root)
    found_any = False
    cdir = root / "contracts"
    if cdir.is_dir():
        found_any = True
        _lint_contracts_folder(cdir, root, items)
    coord = config.PROJECT_DIR
    cfg = root / config.PROJECT_DIR / config.FILE_NAME
    if cfg.is_file():
        found_any = True
        try:
            r = config.load(config_arg=str(cfg), env={})
            coord = r.config["coordination_root"] if "coordination_root" in r.config else coord
            items.append(item("OK", f"{cfg.relative_to(root).as_posix()} satisfies C01", cfg.relative_to(root).as_posix()))
        except config.ConfigError as exc:
            items.append(item("FAIL", str(exc), cfg.relative_to(root).as_posix()))
    sizing_path = Path(sizing) if sizing else (_sizing_candidates(root, coord) or [None])[0]
    catalog_path = Path(catalog) if catalog else _first_existing(root, [CATALOG_PATH])
    readiness_path = Path(readiness) if readiness else _first_existing(root, READINESS_PATHS)
    cat_rows = unit_rows = matrix = None
    if sizing_path is not None:
        found_any = True
        sub = []
        unit_rows = read_sizing_units(sizing_path, sub)
        items.extend(sub or [item("OK", f"{_rel(sizing_path, root)} satisfies C23", _rel(sizing_path, root))])
        matrix = _read_matrix(sizing_path) if unit_rows is not None else None
    if catalog_path is not None:
        found_any = True
        sub = []
        cat_rows = read_catalog(catalog_path, sub)
        if cat_rows is not None:
            sub = catalog_path_items(cat_rows, root)
            items.extend(sub or [item("OK", f"{_rel(catalog_path, root)} satisfies C22; {len(cat_rows)} contract(s), every path exists",
                                      _rel(catalog_path, root))])
        else:
            items.extend(sub)
    if readiness_path is not None:
        found_any = True
        errs = core.validate_file(readiness_path, core.find_schema(_own_contracts_dir(), "C27"))
        rel = _rel(readiness_path, root)
        if errs:
            items.extend(item("FAIL", f"{rel}: {e}", rel) for e in errs)
        else:
            items.append(item("OK", f"{rel} satisfies C27", rel))
            if cat_rows is not None:
                _readiness_items(readiness_path, catalog_path, cat_rows, rel, items)
    if (root / "docs" / "design" / "tech").is_dir():
        found_any = True
        _tech_items(root, matrix, items)
    if sizing_path is not None and cat_rows is not None and unit_rows is not None:
        _sizing_catalog_items(sizing_path, unit_rows, cat_rows, root, items)
    if cat_rows is not None:
        _spec_items(root, cat_rows, (unit_rows or None), items)
    if not found_any:
        items.append(item("FAIL", f"nothing to lint under {root.as_posix()}: no contracts folder, {coord}/batuta.json, sizing.md, "
                                  f"{CATALOG_PATH} or readiness document found", "contracts"))
    return items


def _rel(path, root):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _readiness_items(readiness_path, catalog_path, cat_rows, rel, items):
    doc = core.loads_strict(Path(readiness_path).read_text(encoding="utf-8-sig"))
    ids = {r["id"]: r for r in cat_rows}
    for e in doc["contracts"]:
        row = ids.get(e["id"])
        if row is None:
            items.append(item("FAIL", f"{rel}: contract '{e['id']}' is not a row of the catalog", rel))
        elif e["version"] != row["version"]:
            items.append(item("WARN", f"{rel}: '{e['id']}' is at version {e['version']} but the catalog says {row['version']}", rel))
    missing = sorted(set(ids) - {e["id"] for e in doc["contracts"]})
    if missing:
        items.append(item("WARN", f"{rel}: catalog rows without a readiness entry: {', '.join(missing)}", rel))
    if doc["catalog_sha256"] != _sha256_lf(catalog_path):
        items.append(item("WARN", f"{rel} is stale: its catalog_sha256 is not the hash of the current catalog; compute it again", rel))


def _sizing_catalog_items(sizing_path, unit_rows, cat_rows, root, items):
    rel = _rel(sizing_path, root)
    cat_ids = {r["id"] for r in cat_rows}
    problems = 0
    for u in unit_rows:
        for c in u["Depends on contract ids"]:
            if c not in cat_ids:
                items.append(item("FAIL", f"{rel}: unit '{u['Unit']}' depends on contract '{c}' that is not a row of the catalog", rel))
                problems += 1
    text = Path(sizing_path).read_text(encoding="utf-8-sig")
    schema, spec = _own_spec("C23")
    tspec = next(t for t in spec["tables"] if t["name"] == "Boundaries")
    found = core.read_table(text, tspec, True)
    for b in (found[0] if found else []):
        if b["Contract ID"] not in cat_ids:
            items.append(item("FAIL", f"{rel}: boundary '{b['ID']}' names contract '{b['Contract ID']}' that is not a row of the catalog", rel))
            problems += 1
    if not problems:
        items.append(item("OK", f"{rel}: every boundary and unit dependency names a row of the catalog", rel))


def _spec_items(root, cat_rows, unit_rows, items):
    cat_ids = {r["id"] for r in cat_rows}
    unit_ids = {u["Unit"] for u in unit_rows} if unit_rows else None
    for spec in sorted((root / "specs").glob("*/spec.md")) if (root / "specs").is_dir() else []:
        rel = _rel(spec, root)
        bad = [i for i in _interface_ids(spec.read_text(encoding="utf-8-sig")) if i not in cat_ids]
        for i in bad:
            items.append(item("FAIL", f"{rel}: interface '{i}' is not a row of the catalog", rel))
        if not bad:
            items.append(item("OK", f"{rel}: every interface names a row of the catalog", rel))
    for tasks in sorted((root / "specs").glob("*/tasks.md")) if (root / "specs").is_dir() else []:
        rel = _rel(tasks, root)
        sub = []
        rows = _body_rows(tasks, "C21", "Tasks", sub, "tasks")
        if rows is None:
            items.extend(sub)
            continue
        bad = 0
        for t in rows:
            for c in t["Contracts"]:
                if c not in cat_ids:
                    items.append(item("FAIL", f"{rel}: task {t['Task']} uses contract '{c}' that is not a row of the catalog", rel))
                    bad += 1
            if unit_ids is not None and t["Unit"] not in ("", "-") and t["Unit"] not in unit_ids:
                items.append(item("FAIL", f"{rel}: task {t['Task']} names unit '{t['Unit']}' that is not a row of the sizing's Parallel units", rel))
                bad += 1
        if not bad:
            items.append(item("OK", f"{rel}: {len(rows)} task(s) satisfy C21 and name rows of the catalog and the sizing", rel))


# ------------------------------------------------------------------ validate


def validate_artifact(cid, file, root=None):
    sp = _find_contract(root, cid)
    if sp is None:
        where = ", ".join(d.as_posix() for d in _contracts_dirs(root))
        return [item("FAIL", f"no schema for contract {cid} in {where}")]
    f = Path(file)
    if not f.is_file():
        return [item("FAIL", f"file not found: {f.as_posix()}")]
    try:
        errs = core.validate_file(f, sp, cid)
    except ValueError as exc:
        return [item("FAIL", f"cannot validate against {cid}: {exc}", f.as_posix())]
    if errs:
        return [item("FAIL", e, f.as_posix()) for e in errs]
    if cid == "C22" and root is not None:
        sub = []
        rows = read_catalog(f, sub)
        paths = catalog_path_items(rows, root) if rows is not None else sub
        if paths:
            return [dict(i, path=f.as_posix()) for i in paths]
    return [item("OK", f"{f.name} satisfies {cid}", f.as_posix())]


# ------------------------------------------------------------------ graph


def compute_waves(tasks, frozen, base=2):
    """tasks: list of dicts with Task, Contracts, Depends. Waves start at `base` (wave 0 is the contracts, wave 1 the
    walking skeleton). Returns (waves, items); waves is None on FAIL."""
    items = []
    ids = [t["Task"] for t in tasks]
    byid = {t["Task"]: t for t in tasks}
    for t in tasks:
        for d in t["Depends"]:
            if d not in byid:
                items.append(item("FAIL", f"{t['Task']} depends on unknown task {d}"))
    if items:
        return None, items
    state = {}

    def visit(n, stack):
        state[n] = 1
        for d in byid[n]["Depends"]:
            if state.get(d) == 1:
                cyc = stack[stack.index(d):] + [d]
                items.append(item("FAIL", "dependency cycle: " + " then ".join(cyc)))
            elif d not in state:
                visit(d, stack + [d])
        state[n] = 2

    for n in sorted(ids):
        if n not in state:
            visit(n, [n])
    if items:
        return None, items
    anc = {}

    def ancestors(n):
        if n not in anc:
            out = set()
            for d in byid[n]["Depends"]:
                out |= {d} | ancestors(d)
            anc[n] = out
        return anc[n]

    before = {n: set(byid[n]["Depends"]) for n in ids}
    order = sorted(ids)
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            shared_unfrozen = (set(byid[a]["Contracts"]) & set(byid[b]["Contracts"])) - frozen
            if shared_unfrozen and a not in ancestors(b) and b not in ancestors(a):
                before[b].add(a)
    waves, remaining = {}, set(ids)
    while remaining:
        ready = sorted(n for n in remaining if before[n] <= set(waves))
        if not ready:
            return None, [item("FAIL", "ordering conflict between Depends edges and shared unfrozen contracts: " + ", ".join(sorted(remaining)))]
        for n in ready:
            waves[n] = max([waves[d] + 1 for d in before[n]], default=base)
        remaining -= set(ready)
    return waves, items


def compute_unit_waves(unit_rows, catalog_rows):
    """Waves of the sizing's units. A contract is frozen when its catalog row says `frozen: yes`; a unit that depends
    on a frozen contract can start at wave 2, one that depends on an unfrozen contract starts after the unit that owns
    its catalog row. Returns (waves {unit: wave}, items); waves is None on FAIL."""
    items = []
    catalog = {r["id"]: r for r in catalog_rows}
    units = {u["Unit"]: u for u in unit_rows}
    deps = {}
    for uid, u in units.items():
        deps[uid] = set()
        for c in u["Depends on contract ids"]:
            row = catalog.get(c)
            if row is None:
                items.append(item("FAIL", f"unit {uid} depends on contract '{c}' that is not a row of the catalog"))
                continue
            if row.get("frozen") == "yes":
                continue
            owner = row["owner"]
            if owner in units and owner != uid:
                deps[uid].add(owner)
            elif owner not in units:
                items.append(item("WARN", f"contract '{c}' is not frozen and its owner '{owner}' is not a unit of the sizing; "
                                          f"unit {uid} cannot be ordered after it"))
    if any(i["tag"] == "FAIL" for i in items):
        return None, items
    state = {}

    def visit(uid, stack):
        state[uid] = 1
        for d in sorted(deps[uid]):
            if state.get(d) == 1:
                items.append(item("FAIL", "unit dependency cycle: " + " then ".join(stack[stack.index(d):] + [d])))
            elif d not in state:
                visit(d, stack + [d])
        state[uid] = 2

    for uid in sorted(units):
        if uid not in state:
            visit(uid, [uid])
    if any(i["tag"] == "FAIL" for i in items):
        return None, items
    waves, remaining = {}, set(units)
    while remaining:
        ready = sorted(u for u in remaining if deps[u] <= set(waves))
        for u in ready:
            waves[u] = max([waves[d] + 1 for d in deps[u]], default=2)
        remaining -= set(ready)
    return waves, items


def graph(catalog_path, sizing_path=None, tasks_path=None):
    """The waves, in one numbering: wave 0 the contracts (the frozen ones are listed), wave 1 the walking skeleton, then
    the sizing's units and the tasks from wave 2. Returns a list of items."""
    items = []
    try:
        cat_rows = read_catalog(catalog_path, items)
        unit_rows = read_sizing_units(sizing_path, items) if sizing_path else None
        tasks = _body_rows(tasks_path, "C21", "Tasks", items, "tasks") if tasks_path else None
    except ValueError as exc:
        return [item("FAIL", str(exc))]
    if cat_rows is None or (sizing_path and unit_rows is None) or (tasks_path and tasks is None):
        return items
    catalog = {r["id"]: r for r in cat_rows}
    frozen = sorted(i for i, r in catalog.items() if r.get("frozen") == "yes")
    items.append(item("OK", "wave 0: " + (", ".join(frozen) if frozen else "(no frozen contract yet)")))
    items.append(item("OK", "wave 1: walking skeleton"))
    unit_waves = {}
    if unit_rows is not None:
        unit_waves, problems = compute_unit_waves(unit_rows, cat_rows)
        if unit_waves is None:
            return items + problems
        items.extend(p for p in problems if p["tag"] == "WARN")
        for n in sorted(set(unit_waves.values())):
            items.append(item("OK", f"wave {n}: " + ", ".join(sorted(u for u, w in unit_waves.items() if w == n))))
    if tasks is None:
        return items
    for t in tasks:
        for c in t["Contracts"]:
            if c not in catalog:
                items.append(item("FAIL", f"task {t['Task']} uses contract '{c}' that is not a row of the catalog"))
        if unit_rows is not None and t["Unit"] not in ("", "-") and t["Unit"] not in unit_waves:
            items.append(item("FAIL", f"task {t['Task']} names unit '{t['Unit']}' that is not a row of the sizing's Parallel units"))
    if any(i["tag"] == "FAIL" for i in items):
        return items
    loose = [t for t in tasks if unit_rows is None or t["Unit"] in ("", "-")]
    task_wave = {}
    if loose:
        waves, problems = compute_waves(loose, set(frozen))
        if waves is None:
            return items + problems
        task_wave.update(waves)
    units_of = {}
    for t in tasks:
        if t["Unit"] not in ("", "-") and unit_rows is not None:
            task_wave[t["Task"]] = unit_waves[t["Unit"]]
            units_of[t["Task"]] = t["Unit"]
            u = next(r for r in unit_rows if r["Unit"] == t["Unit"])
            allowed = set(u["Depends on contract ids"]) | {i for i, r in catalog.items() if r["owner"] == t["Unit"]}
            for c in t["Contracts"]:
                if c not in allowed:
                    items.append(item("WARN", f"task {t['Task']} uses contract '{c}' that unit {t['Unit']} neither depends on nor owns"))
    byid = {t["Task"]: t for t in tasks}
    for t in tasks:
        for d in t["Depends"]:
            if d not in byid:
                items.append(item("FAIL", f"{t['Task']} depends on unknown task {d}"))
                continue
            if task_wave[d] > task_wave[t["Task"]]:
                items.append(item("FAIL", f"{t['Task']} (wave {task_wave[t['Task']]}) depends on {d}, which runs later in wave {task_wave[d]}"))
            elif task_wave[d] == task_wave[t["Task"]] and units_of.get(d) != units_of.get(t["Task"]):
                items.append(item("WARN", f"coupling: {t['Task']} depends on {d} in the same wave of another unit; "
                                          f"depend on the contract, not on the other task's code"))
            else:
                for c in sorted((set(t["Contracts"]) & set(byid[d]["Contracts"])) & set(frozen)):
                    items.append(item("WARN", f"coupling: {t['Task']} depends on {d} while both use the frozen contract {c}; "
                                              f"depend on the contract, not on the other task's code, or drop the edge"))
    for t in tasks:
        if t["Wave"] is not None and t["Wave"] != task_wave.get(t["Task"]):
            items.append(item("WARN", f"Wave column of {t['Task']} says {t['Wave']} but the computed wave is {task_wave.get(t['Task'])}"))
    if loose and unit_rows is None:
        for n in sorted({w for w in task_wave.values()}):
            items.append(item("OK", f"wave {n}: " + ", ".join(sorted(k for k, v in task_wave.items() if v == n))))
    else:
        for t in tasks:
            if t["Task"] in units_of:
                items.append(item("OK", f"task {t['Task']} runs in unit {units_of[t['Task']]} (wave {task_wave[t['Task']]})"))
            else:
                items.append(item("OK", f"task {t['Task']} runs in wave {task_wave[t['Task']]}"))
    return items


# ------------------------------------------------------------------ CLI


def _wants_json(args):
    return bool(getattr(args, "json", False))


def _cmd_lint(args):
    items = lint(args.root, args.sizing, args.catalog, args.readiness)
    n_ok = sum(1 for i in items if i["tag"] == "OK")
    n_fail = sum(1 for i in items if i["tag"] == "FAIL")
    n_warn = sum(1 for i in items if i["tag"] == "WARN")
    return emit(AREA, "lint", items, f"lint: {n_ok} ok, {n_warn} warning(s), {n_fail} failure(s)", _wants_json(args))


def _cmd_validate(args):
    items = validate_artifact(args.contract_id, args.file, args.root)
    n_fail = sum(1 for i in items if i["tag"] == "FAIL")
    return emit(AREA, "validate", items, f"validate {args.contract_id}: {'ok' if not n_fail else str(n_fail) + ' error(s)'}", _wants_json(args))


def _cmd_graph(args):
    if not args.catalog:
        items = [item("FAIL", "graph needs --catalog (the contract catalog, C22); --sizing and --tasks are optional")]
    else:
        items = graph(args.catalog, args.sizing, args.tasks)
    n_waves = sum(1 for i in items if i["tag"] == "OK" and i["message"].startswith("wave "))
    n_warn = sum(1 for i in items if i["tag"] == "WARN")
    n_fail = sum(1 for i in items if i["tag"] == "FAIL")
    return emit(AREA, "graph", items, f"graph: {n_waves} wave(s), {n_warn} warning(s), {n_fail} failure(s)", _wants_json(args))


def _json_flag(p):
    # SUPPRESS keeps a Batuta-wide --json from being reset by the verb parser's default.
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the C20 JSON object")


def register(subparsers):
    p = subparsers.add_parser("lint", help="check Batuta's own contracts, or a project's sizing, catalog, readiness and contracts")
    p.add_argument("--root", help="project root to lint: contracts/, sizing.md, docs/contracts/catalog.md, readiness, specs "
                                  "(default: Batuta's own contracts)")
    p.add_argument("--sizing", help="the sizing.md to lint (default: found under the coordination root)")
    p.add_argument("--catalog", help=f"the contract catalog (default: {CATALOG_PATH} under --root)")
    p.add_argument("--readiness", help="the readiness document (default: data/derived/readiness.json or docs/design/readiness.json under --root)")
    _json_flag(p)
    p.set_defaults(func=_cmd_lint)

    p = subparsers.add_parser("validate", help="validate one artifact file against a contract")
    p.add_argument("contract_id", help="contract id such as C02")
    p.add_argument("file", help="artifact file (.json, .jsonl, .md or, for C32, .txt)")
    p.add_argument("--root", help="project root: its contracts/ is searched first, and for C22 the catalog's paths must exist under it")
    _json_flag(p)
    p.set_defaults(func=_cmd_validate)

    p = subparsers.add_parser("graph", help="compute the parallel waves from the catalog, the sizing and a tasks file")
    p.add_argument("--catalog", help="the contract catalog (C22); a contract is frozen when its row says frozen: yes")
    p.add_argument("--sizing", help="sizing.md (C23): its Parallel units become waves 2 and up")
    p.add_argument("--tasks", help="tasks.md (C21): each task's wave, in the same numbering")
    _json_flag(p)
    p.set_defaults(func=_cmd_graph)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="batuta.py contract", description=HELP)
    subs = parser.add_subparsers(dest="verb")
    register(subs)
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)
