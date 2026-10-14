"""Area `tech`: lint the technology matrix of the sizing and the technology decisions (C25).

`tech lint` reads the Technology matrix rows of the sizing and fails any row without an exact version (a range, a wildcard
or a bare major is refused), a primary source URL or a verified date that exists; a date older than the window (90 days by
default, `--max-age-days`) is a warning. Every `docs/design/tech/*.json` decision must satisfy C25 (a risky chosen candidate
needs a spike that passed) and equal a matrix row. Exit codes: 0 ok, 1 failure, 2 warnings.
"""
import argparse
from datetime import date
from pathlib import Path

from batuta_lib import config
from batuta_lib import contract as core
from batuta_lib import spec_model as sm
from batuta_lib.output import emit, item

AREA = "tech"
HELP = "Technology matrix: pinned, sourced and fresh versions; decisions with spikes."
DEFAULT_MAX_AGE_DAYS = 90


def _age_item(subject, verified, today, max_age, path):
    try:
        days = (today - date.fromisoformat(verified)).days
    except ValueError:
        return None
    if days > max_age:
        return item("WARN", f"{subject}: verified {verified}, older than {max_age} days ({days} days ago); verify it again on its primary source", path)
    return None


def matrix_rows(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    return sm.read_rows("C23", "Technology matrix", sm.strip_comments(text), True)


def lint(root=".", sizing=None, tech_dir=None, max_age=DEFAULT_MAX_AGE_DAYS, today=None, config_arg=None):
    root = Path(root)
    today = today or date.today()
    items = []
    try:
        path, places = sm.find_sizing(root, sizing, config_arg)
    except config.ConfigError as exc:
        return [item("FAIL", f"configuration: {exc}")]
    if path is None or not path.is_file():
        return [item("FAIL", "no sizing found; expected one of: " + ", ".join(places) + " (or pass --sizing)")]
    label = sm.rel(path, root)
    schema, _, _ = sm.schema_and_sections("C23")
    rows = matrix_rows(path)
    if rows is None:
        return [item("FAIL", f"{label}: no Technology matrix table (Tool, Version, Primary source URL, Verified date)", label)]
    bad = 0
    for r in rows:
        subject = f"{r.get('Tool', '?')} {r.get('Version', '')}".strip()
        errors = core.validate_def(r, schema, "technology_row")
        for e in errors:
            items.append(item("FAIL", f"technology {subject}: {_reason(e)}", label))
            bad += 1
        if not errors:
            warn = _age_item(f"technology {subject}", r["Verified date"], today, max_age, label)
            items.append(warn or item("OK", f"technology {subject}: exact version, source and a verified date within {max_age} days", label))
    folder = Path(tech_dir) if tech_dir else root / sm.TECH_DIR
    c25 = core.find_schema(config.contracts_dir(), "C25")
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        fl = sm.rel(f, root)
        errors = core.validate_file(f, c25, "C25")
        if errors:
            items.extend(item("FAIL", f"{fl}: {e}", fl) for e in errors)
            continue
        doc = core.loads_strict(f.read_text(encoding="utf-8-sig"))
        if not any(r.get("Tool") == doc["tool"] and r.get("Version") == doc["version"] for r in rows):
            items.append(item("FAIL", f"{fl}: {doc['tool']} {doc['version']} is not a row of the sizing's Technology matrix", fl))
            continue
        warn = _age_item(f"{fl}", doc["verified_date"], today, max_age, fl)
        items.append(warn or item("OK", f"{fl} satisfies C25 and equals a matrix row", fl))
    return items


def _reason(error):
    if "/Version" in error:
        return "version " + error
    if "Primary source URL" in error:
        return "primary source URL " + error
    return error


def _cmd_lint(args):
    today = date.fromisoformat(args.today) if args.today else None
    items = lint(args.root, args.sizing, args.tech_dir, args.max_age_days, today, args.config)
    n = {t: sum(1 for i in items if i["tag"] == t) for t in ("OK", "WARN", "FAIL")}
    return emit(AREA, "lint", items, f"tech lint: {n['OK']} ok, {n['WARN']} warning(s), {n['FAIL']} failure(s)", bool(getattr(args, "json", False)))


def register(subparsers):
    p = subparsers.add_parser("lint", help="lint the Technology matrix of the sizing and the technology decisions (C25)")
    p.add_argument("--root", default=".", help="project root (default: the current folder)")
    p.add_argument("--sizing", help="the sizing.md to read (default: found under the coordination root)")
    p.add_argument("--tech-dir", help=f"the technology decisions folder (default: {sm.TECH_DIR} under --root)")
    p.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS, help="warn when a verified date is older (default 90)")
    p.add_argument("--today", help="YYYY-MM-DD to measure ages from (default: today; for reproducible runs)")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the C20 JSON object")
    p.set_defaults(func=_cmd_lint)
