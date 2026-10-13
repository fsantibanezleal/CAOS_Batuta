"""Area `skeleton`: the deployed walking skeleton states what is real.

Verb:
    check  the readiness document (C27) is current and labels every component real or served by a provider with its
           provenance; the catalog's contract tests exist and their status is recorded; the preview record (C29) is valid
           and, with `--check-network`, every preview URL answers

Before L6-skeleton there is no readiness document and the check says SKIP. With `--release` every component that is not real
(a provider serves it, it is missing, partial or stale, or a model answers from its baseline) is listed as a gap and fails,
the rule the L9-promote gate applies. The network is never touched unless `--check-network` is given.
Exit codes: 0 ok, 1 failure, 2 warnings or an honest partial.
"""
from pathlib import Path

from batuta_lib import gate_model, readiness
from batuta_lib.output import emit, item

AREA = "skeleton"
HELP = "Walking skeleton: readiness document, provider labels, contract tests and previews."


def _check(args):
    root = Path(args.root or ".")
    items = []
    found = readiness.find_readiness(root, args.readiness)
    if found is None:
        items.append(item("FAIL" if args.require else "SKIP",
                          "no readiness document (data/derived/readiness.json or docs/design/readiness.json)"
                          + ("" if args.require else "; it exists from L6-skeleton on")))
    else:
        items.extend(readiness.check_readiness(root, found, catalog=args.catalog, head=args.head, lag=args.lag,
                                               release=args.release, tests=True, tests_record=args.tests_record))
    info = gate_model.GIT.info(root)
    head = args.head or (info[1] if info else None)
    items.extend(readiness.check_previews(root, args.previews, args.url or [], head=head, network=args.check_network,
                                          explicit=bool(args.previews)))
    bad = [i for i in items if i["tag"] == "FAIL"]
    return emit(AREA, "check", items, f"{len(bad)} problem(s)" if bad else "the skeleton states what is real", bool(getattr(args, "json", False)))


def register(subparsers):
    p = subparsers.add_parser("check", help="check the readiness document, contract tests and previews")
    p.add_argument("--root", help="the project folder (default: the current folder)")
    p.add_argument("--readiness", help="the readiness document (default: data/derived/readiness.json or docs/design/readiness.json)")
    p.add_argument("--previews", help="the preview record (C29; default: docs/design/previews.json when it exists)")
    p.add_argument("--catalog", help="the contract catalog (default: docs/contracts/catalog.md)")
    p.add_argument("--head", help="the head commit (default: HEAD)")
    p.add_argument("--lag", type=int, default=0, help="commits that changed files outside specs/ the readiness may be behind (default 0)")
    p.add_argument("--release", action="store_true", help="list every component that is not real as a gap and fail")
    p.add_argument("--require", action="store_true", help="a missing readiness document is a failure, not a skip")
    p.add_argument("--tests-record", metavar="FILE", help='JSON {"results": {"<test path>": "pass"|"fail"}} of the contract tests')
    p.add_argument("--url", action="append", metavar="URL", help="a preview URL to check (repeatable; fetched only with --check-network)")
    p.add_argument("--check-network", action="store_true", help="fetch each preview URL (off by default)")
    p.set_defaults(func=_check)
