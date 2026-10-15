"""Area `provider`: every dependency that can be absent declares what happens when it is.

Verbs:
    lint   every catalog row (C22) declares its availability states (available, partial, stale, provider(kind), training,
           missing) in the missing-data behavior column, each with a test that exists and is its own; the provider state
           matches the provider column; model cards (C28) validate
    check  a response carries a valid runtime availability block (C26), and with `--id` its state is one the catalog row
           declares; a provider answer always names its provenance

Availability states are CAOS ADR-0080's exactly; there is no alias. Exit codes: 0 ok, 1 failure, 2 warnings.
"""
from pathlib import Path

from batuta_lib import readiness
from batuta_lib.output import emit, item

AREA = "provider"
HELP = "Providers: declared availability states with tests (lint) and runtime availability blocks (check)."


def _json(args):
    return bool(getattr(args, "json", False))


def _lint(args):
    root = Path(args.root or ".")
    items = readiness.lint_catalog(root, args.catalog or readiness.CATALOG_PATH, explicit=bool(args.catalog), models=args.models)
    bad = [i for i in items if i["tag"] == "FAIL"]
    return emit(AREA, "lint", items, f"{len(bad)} problem(s)" if bad else "every declared state has its test", _json(args))


def _check(args):
    root = Path(args.root or ".")
    if args.catalog and not args.id:
        return emit(AREA, "check", [item("FAIL", "--catalog needs --id: the catalog row whose declared states the response is held to")],
                    "refused", _json(args))
    catalog = None
    if args.id:
        catalog = readiness._abs(root, args.catalog or readiness.CATALOG_PATH)
        if not catalog.is_file():
            return emit(AREA, "check", [item("FAIL", f"catalog not found: {catalog.as_posix()}")], "refused", _json(args))
    items = readiness.check_response(args.response, root=root, catalog=catalog, row_id=args.id)
    bad = [i for i in items if i["tag"] == "FAIL"]
    return emit(AREA, "check", items, "the response breaks its declaration" if bad else "the response matches its declaration", _json(args))


def register(subparsers):
    p = subparsers.add_parser("lint", help="check the declared availability states of the catalog")
    p.add_argument("--root", help="the project folder (default: the current folder)")
    p.add_argument("--catalog", help=f"the contract catalog (default {readiness.CATALOG_PATH}; absent at the default is a skip)")
    p.add_argument("--models", help="a folder of <id>/card.json model cards (C28) to validate")
    p.set_defaults(func=_lint)

    p = subparsers.add_parser("check", help="check a response's runtime availability block against its declaration")
    p.add_argument("--response", required=True, help="a JSON response holding an availability block (or the block itself)")
    p.add_argument("--root", help="the project folder (default: the current folder)")
    p.add_argument("--catalog", help=f"the contract catalog (default {readiness.CATALOG_PATH} when --id is given)")
    p.add_argument("--id", help="the catalog row the response answers for")
    p.set_defaults(func=_check)
