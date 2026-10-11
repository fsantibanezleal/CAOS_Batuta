"""Area `contract`: lint the data contracts, validate an artifact against one, compute parallel waves.

Module layout contract (shared with harness.py): AREA, HELP, register(subparsers), and functions callable
without the CLI. `register` receives the area's verb sub-parsers action; each verb sets `func(args) -> exit code`.
Verbs print tag-prefixed lines (OK, WARN, FAIL, ...) and, with --json, the C20 object. Exit codes: 0 ok,
1 failure, 2 warnings.
"""
import argparse
import json
import re
from pathlib import Path

from harness_lib import contract as core
from harness_lib import frontmatter as fm

AREA = "contract"
HELP = "Data contracts: lint schemas and fixtures, validate an artifact, compute parallel waves."

C22_HEADERS = ["Interface", "Contract file", "Producer", "Consumers", "Version"]


# ------------------------------------------------------------------ items and output


def item(tag, message, path=None):
    d = {"tag": tag, "message": message}
    if path:
        d["path"] = path
    return d


def exit_code(items):
    tags = {i["tag"] for i in items}
    if "FAIL" in tags or "REFUSED" in tags:
        return 1
    if "WARN" in tags:
        return 2
    return 0


def emit(verb, items, summary, as_json):
    code = exit_code(items)
    if as_json:
        print(json.dumps({"contract_version": "1.0", "tool": "harness", "area": AREA, "verb": verb,
                          "exit_code": code, "items": items, "summary": summary}, indent=2))
    else:
        for i in items:
            print(f"{i['tag']} {i['message']}" + (f" ({i['path']})" if i.get("path") else ""))
        print(summary)
    return code


def _short(errors, n=2):
    shown = "; ".join(errors[:n])
    return shown + (f"; and {len(errors) - n} more" if len(errors) > n else "")


# ------------------------------------------------------------------ locating contracts


def _own_contracts_dir():
    """The contracts shipped with this harness: next to the plugin (plugins/harness/contracts) or at the repo root."""
    here = Path(__file__).resolve()
    for base in (here.parents[3], here.parents[5] if len(here.parents) > 5 else here.parents[3]):
        if (base / "contracts").is_dir():
            return base / "contracts"
    return here.parents[3] / "contracts"


def _contracts_dir(root):
    if root is not None:
        return Path(root) / "contracts"
    if (Path.cwd() / "contracts").is_dir():
        return Path.cwd() / "contracts"
    return _own_contracts_dir()


def _own_spec(cid):
    """(schema, sections spec) of a built-in contract (C21, C22) used by the graph command."""
    sp = core.find_schema(_own_contracts_dir(), cid)
    if sp is None:
        raise ValueError(f"{cid} schema not found in {_own_contracts_dir()}")
    return core.load_schema(sp), core.load_sections_spec(sp)


# ------------------------------------------------------------------ lint


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
    ok = True
    if readme_text is not None and not re.search(rf"\b{cid}\b", readme_text):
        items.append(item("FAIL", f"{cid} is not listed in the catalog (contracts/README.md)", rel))
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
        else:
            items.append(item("WARN", f"{label}: fixture name must start with valid- or invalid-", fxrel))
    if valid == 0 or invalid == 0:
        items.append(item("FAIL", f"{cid} needs at least one valid and one invalid fixture (found {valid} and {invalid})", rel))
        ok = False
    if ok:
        items.append(item("OK", f"{cid} {name}: schema loads; {valid} valid and {invalid} invalid fixture(s) behave as labeled", rel))
    return schema


def _lint_spec_interfaces(root, cdir, items):
    c22 = core.find_schema(cdir, "C22")
    schema = None
    if c22 is not None:
        try:
            schema = core.load_schema(c22)
        except ValueError:
            schema = None
    for spec in sorted((root / "specs").glob("*/spec.md")) if (root / "specs").is_dir() else []:
        rel = spec.relative_to(root).as_posix()
        try:
            found = core.read_table(spec.read_text(encoding="utf-8"), {"headers": C22_HEADERS})
        except ValueError as exc:
            items.append(item("FAIL", f"{rel}: cannot read the Interfaces table: {exc}", rel))
            continue
        if found is None:
            items.append(item("WARN", f"{rel}: no Interfaces table (C22) found", rel))
            continue
        rows, _ = found
        bad = 0
        for i, row in enumerate(rows, 1):
            errs = core.validate(row, schema) if schema else []
            for e in errs:
                items.append(item("FAIL", f"{rel} interface row {i} {e}", rel))
                bad += 1
            target = row["Contract file"]
            if errs and not target:
                continue
            f = root / target
            if not f.is_file():
                items.append(item("FAIL", f"{rel}: interface '{row['Interface']}' names contract file '{target}' that does not exist", rel))
                bad += 1
            elif target.endswith(".schema.json"):
                try:
                    core.load_schema(f)
                except ValueError as exc:
                    items.append(item("FAIL", f"{rel}: interface '{row['Interface']}' contract file does not load: {exc}", rel))
                    bad += 1
        if not bad:
            items.append(item("OK", f"{rel}: {len(rows)} interface row(s) resolve to existing contract files", rel))


def lint(root):
    """Lint every schema, fixture and spec interface row under root. Returns a list of items."""
    root = Path(root)
    cdir = root / "contracts"
    items = []
    if not cdir.is_dir():
        return [item("FAIL", "no contracts folder found", str(cdir.as_posix()))]
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
    if "C01" in loaded and "C14" in loaded:
        budgets = loaded["C01"].get("properties", {}).get("budgets")
        if _canon(budgets) != _canon(loaded["C14"]):
            items.append(item("FAIL", "C14 does not equal the budgets block of C01 (type, required, properties)", "contracts"))
        else:
            items.append(item("OK", "C14 equals the budgets block of C01", "contracts"))
    _lint_spec_interfaces(root, cdir, items)
    return items


# ------------------------------------------------------------------ validate


def validate_artifact(cid, file, root=None):
    cdir = _contracts_dir(root)
    sp = core.find_schema(cdir, cid)
    if sp is None:
        return [item("FAIL", f"no schema for contract {cid} in {cdir.as_posix()}")]
    f = Path(file)
    if not f.is_file():
        return [item("FAIL", f"file not found: {f.as_posix()}")]
    try:
        errs = core.validate_file(f, sp, cid)
    except ValueError as exc:
        return [item("FAIL", f"cannot validate against {cid}: {exc}", f.as_posix())]
    if errs:
        return [item("FAIL", e, f.as_posix()) for e in errs]
    return [item("OK", f"{f.name} satisfies {cid}", f.as_posix())]


# ------------------------------------------------------------------ graph


def _norm(p):
    p = p.replace("\\", "/")
    return p[2:] if p.startswith("./") else p


def _read_rows(path, cid, items, label):
    """Validate the table file against its built-in contract and return the rows, or None after adding FAIL items."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        items.append(item("FAIL", f"cannot read {label} file: {exc}", Path(path).as_posix()))
        return None
    schema, spec = _own_spec(cid)
    spec = dict(spec)
    if cid == "C22":
        spec["tables"] = [dict(t, optional=True) for t in spec["tables"]]
    errs = core.validate_markdown(text, schema, spec)
    if errs:
        items.extend(item("FAIL", f"{label}: {e}", Path(path).as_posix()) for e in errs)
        return None
    found = core.read_table(text, spec["tables"][0])
    return found[0] if found else []


def compute_waves(tasks, frozen):
    """tasks: list of dicts with Task, Contracts, Depends. Returns (waves, items); waves is None on FAIL."""
    items = []
    ids = [t["Task"] for t in tasks]
    byid = {t["Task"]: t for t in tasks}
    for t in tasks:
        for d in t["Depends"]:
            if d not in byid:
                items.append(item("FAIL", f"{t['Task']} depends on unknown task {d}"))
    if items:
        return None, items
    # cycle detection on Depends
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
            waves[n] = 1 + max([waves[d] for d in before[n]], default=0)
        remaining -= set(ready)
    return waves, items


def graph(tasks_path, interfaces_path, root=None):
    """Compute the waves of a C21 tasks file against a C22 interfaces file. Returns a list of items."""
    root = Path(root) if root is not None else Path.cwd()
    items = []
    try:
        tasks = _read_rows(tasks_path, "C21", items, "tasks")
        ifaces = _read_rows(interfaces_path, "C22", items, "interfaces")
    except ValueError as exc:
        return [item("FAIL", str(exc))]
    if tasks is None or ifaces is None:
        return items
    if not ifaces:
        items.append(item("WARN", "no interface table found: every contract is treated as unfrozen", Path(interfaces_path).as_posix()))
    declared = {_norm(r["Contract file"]) for r in ifaces}
    frozen = {c for c in declared if (root / c).is_file()}
    used = []
    for t in tasks:
        t["Contracts"] = [_norm(c) for c in t["Contracts"]]
        for c in t["Contracts"]:
            if c not in used:
                used.append(c)
    for c in used:
        if c not in declared:
            items.append(item("WARN", f"contract {c} is not declared in the interfaces table (treated as unfrozen)"))
        elif c not in frozen:
            items.append(item("WARN", f"contract {c} is declared but its file is missing (unfrozen)"))
    waves, problems = compute_waves(tasks, frozen)
    if waves is None:
        return items + problems
    byid = {t["Task"]: t for t in tasks}
    for t in tasks:
        for d in t["Depends"]:
            for c in sorted((set(t["Contracts"]) & set(byid[d]["Contracts"])) & frozen):
                items.append(item("WARN", f"coupling: {t['Task']} depends on {d} while both use the frozen contract {c}; "
                                          f"depend on the contract, not on the other task's code, or drop the edge"))
    for t in tasks:
        if t["Wave"] is not None and t["Wave"] != waves[t["Task"]]:
            items.append(item("WARN", f"Wave column of {t['Task']} says {t['Wave']} but the computed wave is {waves[t['Task']]}"))
    for n in sorted(set(waves.values())):
        members = sorted(k for k, v in waves.items() if v == n)
        items.append(item("OK", f"wave {n}: " + ", ".join(members)))
    return items


# ------------------------------------------------------------------ CLI


def _wants_json(args):
    return bool(getattr(args, "json", False))


def _cmd_lint(args):
    root = Path(args.root) if args.root else Path.cwd()
    items = lint(root)
    n_ok = sum(1 for i in items if i["tag"] == "OK")
    n_fail = sum(1 for i in items if i["tag"] == "FAIL")
    n_warn = sum(1 for i in items if i["tag"] == "WARN")
    return emit("lint", items, f"lint: {n_ok} ok, {n_warn} warning(s), {n_fail} failure(s)", _wants_json(args))


def _cmd_validate(args):
    items = validate_artifact(args.contract_id, args.file, args.root)
    n_fail = sum(1 for i in items if i["tag"] == "FAIL")
    return emit("validate", items, f"validate {args.contract_id}: {'ok' if not n_fail else str(n_fail) + ' error(s)'}", _wants_json(args))


def _cmd_graph(args):
    items = graph(args.tasks, args.interfaces, args.root)
    n_waves = sum(1 for i in items if i["tag"] == "OK" and i["message"].startswith("wave "))
    n_warn = sum(1 for i in items if i["tag"] == "WARN")
    n_fail = sum(1 for i in items if i["tag"] == "FAIL")
    return emit("graph", items, f"graph: {n_waves} wave(s), {n_warn} warning(s), {n_fail} failure(s)", _wants_json(args))


def _json_flag(p):
    # SUPPRESS keeps a harness-wide --json from being reset by the verb parser's default.
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the C20 JSON object")


def register(subparsers):
    p = subparsers.add_parser("lint", help="check every schema, fixture and spec interface row under a root")
    p.add_argument("--root", help="project root holding contracts/ (default: current directory)")
    _json_flag(p)
    p.set_defaults(func=_cmd_lint)

    p = subparsers.add_parser("validate", help="validate one artifact file against a contract")
    p.add_argument("contract_id", help="contract id such as C02")
    p.add_argument("file", help="artifact file (.json, .jsonl or .md)")
    p.add_argument("--root", help="project root holding contracts/ (default: current directory, else the harness contracts)")
    _json_flag(p)
    p.set_defaults(func=_cmd_validate)

    p = subparsers.add_parser("graph", help="compute parallel waves from a tasks file (C21) and an interfaces file (C22)")
    p.add_argument("--tasks", required=True, help="tasks.md with the C21 table")
    p.add_argument("--interfaces", required=True, help="spec.md with the C22 interfaces table")
    p.add_argument("--root", help="project root that contract file paths are relative to (default: current directory)")
    _json_flag(p)
    p.set_defaults(func=_cmd_graph)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="harness.py contract", description=HELP)
    subs = parser.add_subparsers(dest="verb")
    register(subs)
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)
