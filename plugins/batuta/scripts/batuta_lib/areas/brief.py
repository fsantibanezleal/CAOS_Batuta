"""Area `brief`: create a delegation brief from the template and lint it before launch.

Verbs:
    new   write a brief from `templates/brief.md` into `<coordination_root>/delegation/<id>.brief.md` and add its row
          to `ledger.md` in the same folder (created with the C04 header when absent; existing rows and optional columns
          are kept byte for byte). The id is `<topic>-<date>`, with `-2`, `-3` when the same id exists.
    lint  refuse a brief that still has template slots, misses a required section, a header field, a deliverable or a
          check with a backticked command (C02), and warn about an escalation, the fable model, more than eight
          deliverables and a write scope that overlaps another open brief of the ledger.

`--agent` sets the model and the kind from the role table of the plugin; `general-purpose` has no pinned model, so
`--model` is required with it. Exit codes: 0 ok, 1 failure or refusal, 2 warnings.
"""
from __future__ import annotations

import sys
from pathlib import Path

from batuta_lib import config, delegation
from batuta_lib.output import emit, item

AREA = "brief"
HELP = "Delegation briefs: create one from the template (with its ledger row) and lint it before launch."


def _wants_json(args):
    return bool(getattr(args, "json", False))


def _context(args, verb):
    """(root, config dict, failure exit code or None); WARN lines go to stderr."""
    try:
        root, resolved, warnings = delegation.project_config(args)
    except config.ConfigError as exc:
        return None, None, emit(AREA, verb, [item("FAIL", f"configuration: {exc}")], f"brief {verb} failed", _wants_json(args))
    for line in warnings:
        print(line, file=sys.stderr)
    return root, resolved.config, None


def _new(args):
    root, cfg, failure = _context(args, "new")
    if failure is not None:
        return failure
    try:
        made = delegation.new_brief(root, cfg, args.slug, args.topic, args.agent, args.title, model=args.model, kind=args.kind,
                                    sizing=args.sizing, report=args.report, date=args.date)
    except delegation.LedgerLockError as exc:
        return emit(AREA, "new", [item("FAIL", f"the ledger is locked by another writer, nothing written: {exc}")],
                    "brief new failed", _wants_json(args))
    except delegation.LedgerError as exc:
        return emit(AREA, "new", [item("REFUSED", f"the ledger would not satisfy C04, nothing written: {exc}")],
                    "brief new refused", _wants_json(args))
    except (delegation.DelegationError, OSError) as exc:
        return emit(AREA, "new", [item("FAIL", str(exc))], "brief new failed", _wants_json(args))
    items = [item("NEW", f"brief {made['id']}", made["brief"].as_posix()),
             item("OK", "the report goes to " + made["report"].as_posix(), made["report"].as_posix()),
             item("CHANGED", "ledger row added", made["ledger"].as_posix())]
    items.extend(item("OK", f"note: {note}") for note in made["notes"])
    items.append(item("OK", "next: fill every <fill: ...> slot, then run: brief lint <brief>"))
    return emit(AREA, "new", items, f"brief {made['id']} written", _wants_json(args))


def _lint(args):
    root, _cfg, failure = _context(args, "lint")
    if failure is not None:
        return failure
    path = Path(args.brief)
    try:
        text = delegation.read_text(path)
    except OSError as exc:
        return emit(AREA, "lint", [item("FAIL", f"brief unreadable: {exc}", path.as_posix())], "brief lint failed", _wants_json(args))
    own = delegation.header_fields(text).get("id")
    errors, warnings = delegation.lint_brief(text, delegation.open_siblings(path.resolve().parent, own))
    folder = path.resolve().parent
    warnings = warnings + [f"{name} is in {folder.name}/ but has no row in its ledger (never deleted; add the row or remove the file)"
                           for name in delegation.unlisted_briefs(folder)]
    items = [item("FAIL", e, path.as_posix()) for e in errors] + [item("WARN", w, path.as_posix()) for w in warnings]
    if not errors:
        items.insert(0, item("OK", "brief passes the lint", path.as_posix()))
    return emit(AREA, "lint", items, ("LINT FAILED" if errors else "LINT OK") + f": {path.as_posix()}", _wants_json(args))


def register(subparsers):
    new = subparsers.add_parser("new", help="write a brief from the template and add a ledger row")
    new.add_argument("--slug", required=True, help="the initiative slug (the title of a new ledger)")
    new.add_argument("--topic", required=True, help="short kebab-case topic; the id is <topic>-<date>")
    new.add_argument("--agent", required=True, choices=list(delegation.AGENTS), help="the agent that runs it")
    new.add_argument("--title", required=True)
    new.add_argument("--model", choices=delegation.MODELS, help="override the agent's pinned model (an escalation)")
    new.add_argument("--kind", choices=list(delegation.KINDS), help="the brief kind (default: from the agent)")
    new.add_argument("--sizing", help="path of the product's sizing document, written into the brief header")
    new.add_argument("--report", help="report path inside the project root (default: next to the brief)")
    new.add_argument("--root", default=".", help="project root (default: the current folder)")
    new.add_argument("--date", help="ISO date for the id (default: today)")
    new.set_defaults(func=_new)
    lint = subparsers.add_parser("lint", help="check a brief before launching the agent")
    lint.add_argument("brief")
    lint.add_argument("--root", default=".", help="project root (default: the current folder)")
    lint.set_defaults(func=_lint)
