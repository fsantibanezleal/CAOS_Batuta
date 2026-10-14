"""Area `size`: lint the sizing (C23) and cross-check it against the contract catalog (C22).

`size lint` validates the sizing through the contract area's C23 rules (twelve sections, four tables, exact technology
versions, disjoint write scopes), then checks what only a cross-file reading can: every Boundaries row and every unit
dependency names a row of the catalog (an absent catalog leaves them unresolved, a FAIL naming the path expected), every
component has a unit, and it prints the estimate totals per unit and per repository.

A component has a unit when its Components line carries `(unit: <id>)` naming a row of the Parallel units table, or when the
component's name appears in a Modules row (module, responsibility or owner unit) or in a Parallel units row. Exit codes: 0 ok,
1 failure, 2 warnings.
"""
import argparse
import re
from pathlib import Path

from batuta_lib import config
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm
from batuta_lib import spec_model as sm
from batuta_lib.output import emit, item

AREA = "size"
HELP = "System sizing: lint sizing.md against C23 and the contract catalog, with estimate totals."

_COMPONENT = re.compile(r"^\s*[-*+]\s+([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\(([^)]*)\))?")
_UNIT_MARK = re.compile(r"\bunit:\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_COUNT = re.compile(r"(\d+)\s+([A-Za-z]+)")


def _tables(text):
    out = {}
    for name in ("Modules and functions", "Boundaries", "Parallel units"):
        out[name] = sm.read_rows("C23", name, text, True) or []
    return out


def _components(text):
    body = fm.section_bodies(text)
    for title, content in body.items():
        if title.lower() == "components":
            return [(m.group(1), l) for l in content.splitlines() if (m := _COMPONENT.match(l))]
    return []


def _repository_names(text):
    for title, content in fm.section_bodies(text).items():
        if title.lower() == "repositories":
            return [m.group(1) for m in (_COMPONENT.match(l) for l in content.splitlines()) if m]
    return []


def _estimate(cell):
    pairs = {}
    for n, noun in _COUNT.findall(cell):
        pairs[noun.lower()] = pairs.get(noun.lower(), 0) + int(n)
    if not pairs and cell.strip().upper() in ("S", "M", "L"):
        pairs[cell.strip().upper()] = 1
    return pairs


def _fmt(totals):
    return ", ".join(f"{n} {noun}" for noun, n in sorted(totals.items())) or "no countable estimate"


def _add(into, more):
    for k, v in more.items():
        into[k] = into.get(k, 0) + v


def lint(root=".", sizing=None, catalog=None, config_arg=None):
    root = Path(root)
    items = []
    try:
        path, places = sm.find_sizing(root, sizing, config_arg)
    except config.ConfigError as exc:
        return [item("FAIL", f"configuration: {exc}")]
    if path is None or not path.is_file():
        return [item("FAIL", "no sizing found; expected one of: " + ", ".join(places) + " (or pass --sizing)")]
    label = sm.rel(path, root)
    _, _, sp = sm.schema_and_sections("C23")
    errors = core.validate_file(path, sp, "C23")
    if errors:
        return [item("FAIL", f"{label}: {e}", label) for e in errors]
    items.append(item("OK", f"{label} satisfies C23", label))
    text = path.read_text(encoding="utf-8-sig")
    tables = _tables(text)
    units = {u["Unit"]: u for u in tables["Parallel units"]}

    cat_rows, cat_items = sm.read_catalog_rows(root, catalog)
    cat_label = sm.rel(sm.catalog_file(root, catalog), root)
    if cat_rows is None:
        why = "; ".join(i["message"] for i in cat_items) if cat_items else f"no catalog at {cat_label}"
        for b in tables["Boundaries"]:
            items.append(item("FAIL", f"boundary {b['ID']}: contract '{b['Contract ID']}' is unresolved ({why})", cat_label))
        for u in tables["Parallel units"]:
            for c in u["Depends on contract ids"]:
                items.append(item("FAIL", f"unit {u['Unit']}: contract '{c}' is unresolved ({why})", cat_label))
    else:
        ids = {r["id"] for r in cat_rows}
        bad = 0
        for b in tables["Boundaries"]:
            if b["Contract ID"] not in ids:
                items.append(item("FAIL", f"boundary {b['ID']}: contract '{b['Contract ID']}' is not a row of the catalog", cat_label))
                bad += 1
        for u in tables["Parallel units"]:
            for c in u["Depends on contract ids"]:
                if c not in ids:
                    items.append(item("FAIL", f"unit {u['Unit']}: depends on contract '{c}' that is not a row of the catalog", cat_label))
                    bad += 1
        if not bad:
            items.append(item("OK", "every boundary contract and unit dependency is a row of the catalog", cat_label))

    haystack = [" ".join(str(v) for v in m.values()).lower() for m in tables["Modules and functions"]]
    haystack += [(u["Unit"] + " " + u["Write scope"]).lower() for u in tables["Parallel units"]]
    unlinked = 0
    for name, note in _components(text):
        marked = _UNIT_MARK.search(note)
        if marked:
            if marked.group(1) in units:
                continue
            items.append(item("FAIL", f"component {name}: unit '{marked.group(1)}' is not a row of the Parallel units table", label))
            unlinked += 1
        elif not any(name.lower() in h for h in haystack):
            items.append(item("FAIL", f"component {name} has no unit: mark it `(unit: <id>)` or name it in a Modules or Parallel units row", label))
            unlinked += 1
    if not unlinked:
        items.append(item("OK", "every component has a unit", label))

    per_unit, per_repo = {}, {}
    repos = _repository_names(text)
    for m in tables["Modules and functions"]:
        est = _estimate(m["Size estimate"])
        if not est:
            items.append(item("WARN", f"module {m['Module']}: the estimate '{m['Size estimate']}' has no count or S, M, L size", label))
        _add(per_unit.setdefault(m["Owner unit"], {}), est)
        unit = units.get(m["Owner unit"], {})
        repo = unit.get("Repository") or (repos[0] if len(repos) == 1 else "unassigned")
        _add(per_repo.setdefault(repo, {}), est)
    for unit, totals in sorted(per_unit.items()):
        items.append(item("OK", f"estimate {unit}: {_fmt(totals)}", label))
    for repo, totals in sorted(per_repo.items()):
        items.append(item("OK", f"estimate repository {repo}: {_fmt(totals)}", label))
    return items


def _cmd_lint(args):
    items = lint(args.root, args.sizing, args.catalog, args.config)
    n = {t: sum(1 for i in items if i["tag"] == t) for t in ("OK", "WARN", "FAIL")}
    return emit(AREA, "lint", items, f"size lint: {n['OK']} ok, {n['WARN']} warning(s), {n['FAIL']} failure(s)", bool(getattr(args, "json", False)))


def register(subparsers):
    p = subparsers.add_parser("lint", help="lint sizing.md (C23) and cross-check it against the contract catalog (C22)")
    p.add_argument("--root", default=".", help="project root (default: the current folder)")
    p.add_argument("--sizing", help="the sizing.md to lint (default: found under the coordination root)")
    p.add_argument("--catalog", help=f"the contract catalog (default: {sm.CATALOG_PATH} under --root)")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the C20 JSON object")
    p.set_defaults(func=_cmd_lint)
