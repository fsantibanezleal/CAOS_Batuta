"""Area `gate`: only verified results are approved and promoted.

Verbs:
    evidence-lint  check one gate evidence file (C09): verdict rules, reproductions, routed role and model
    status         show or update the status file of a feature (C10), atomically
    check          enforce gate order, evidence, the freeze approval, human waivers, phase and the release rules
    thresholds     the quality thresholds only ratchet up (C11): `--check` or `--propose name=value`
    promote        merge only on green for the exact head commit (a pull request, or a local branch with evidence)
    hook-stop      the Stop hook as a command (reads the hook payload on stdin)

The Stop handler `gate-stop` blocks once when a unit with uncommitted changes has a failing gate check; on the second
attempt it appends a dated UNVERIFIED line to the unit's status file and lets the session end. A session that changed no
unit is never blocked. Files are written only with `--apply` (dry run by default), atomically.
Exit codes: 0 ok, 1 failure or refusal, 2 warnings or honest partial.
"""
import datetime
import json
import os
import sys
from pathlib import Path

from batuta_lib import config, evidence, gate_model, promote, thresholds
from batuta_lib import frontmatter as fm
from batuta_lib.output import emit, item

AREA = "gate"
HELP = "Gates: evidence lint, status, gate check, ratcheting thresholds, promotion on green, Stop hook."


def _json(args):
    return bool(getattr(args, "json", False))


def _root(args):
    return Path(getattr(args, "root", None) or ".")


def _cfg(args, root):
    return config.load(config_arg=getattr(args, "config", None), project_root=root).config


def _fail(verb, args, message):
    return emit(AREA, verb, [item("FAIL", message)], message, _json(args))


# ------------------------------------------------------------------ evidence-lint

def _evidence_lint(args):
    path = Path(args.file)
    try:
        cfg = _cfg(args, _root(args))
        text = gate_model.read(path)
    except (config.ConfigError, OSError, UnicodeDecodeError) as exc:
        return _fail("evidence-lint", args, str(exc))
    items, meta = evidence.lint_text(text, cfg, expect_gate=args.gate, expect_feature=args.feature, path=path.as_posix(),
                                     today=args.today)
    if meta and path.parent.name == "evidence" and path.stem != meta.get("gate"):
        items.append(item("FAIL", f"file name {path.name} does not name the gate {meta.get('gate')}", path.as_posix()))
    bad = [i for i in items if i["tag"] == "FAIL"]
    if not bad and meta:
        items.append(item("OK", f"valid evidence: gate {meta['gate']}, verdict {meta['verdict']}, {meta['role']} on {meta['model']}",
                          path.as_posix()))
    return emit(AREA, "evidence-lint", items, f"{len(bad)} problem(s)" if bad else "evidence is valid", _json(args))


# ------------------------------------------------------------------ status

def _parse_set(text):
    gate, sep, state = str(text).partition("=")
    if not sep or gate not in gate_model.GATES:
        raise ValueError(f"'{text}' is not <gate>=<state> with a gate of {', '.join(gate_model.GATES)}")
    if state not in gate_model.STATES:
        raise ValueError(f"'{state}' is not a gate state ({', '.join(gate_model.STATES)})")
    return gate, state


def _status(args):
    root, feature = _root(args), args.feature
    status, items = gate_model.load_status(root, feature)
    if status is None:
        return emit(AREA, "status", items, f"{feature}: status cannot be read", _json(args))
    if not args.set:
        for g in gate_model.GATES:
            items.append(item("OK", f"{g}: {status.state(g)}"))
        return emit(AREA, "status", items, f"{feature} phase {status.meta['phase']}", _json(args))
    try:
        cfg = _cfg(args, root)
        wanted = [_parse_set(s) for s in args.set]
    except (config.ConfigError, ValueError) as exc:
        return emit(AREA, "status", [item("REFUSED", str(exc))], "nothing changed", _json(args))
    gates = {g: status.state(g) for g in gate_model.GATES}
    refused = []
    for gate, state in wanted:
        gates[gate] = state
    for gate, state in wanted:
        idx = gate_model.GATES.index(gate)
        if state == "waived":
            refused.append(f"{gate}: an agent never sets a waiver; a human writes the waiver line (gate, reason, by, date) in the status file")
        elif state == "passed":
            open_before = next((g for g in gate_model.GATES[:idx] if gates[g] not in gate_model.COMPLETE), None)
            if open_before:
                refused.append(f"{gate}: the earlier gate {open_before} is {gates[open_before]}; gates pass in order")
                continue
            repo = gate_model.Repo(root, args.head) if not args.no_commit_check else None
            if repo is not None and not repo.ok:
                refused.append(f"{gate}: cannot verify the evidence commit: not a git repository (use --no-commit-check)")
                continue
            found, _ = gate_model.gate_evidence_items(root, feature, gate, cfg, repo, args.today or gate_model.today_iso(),
                                                      gate == "L9-promote", None)
            refused.extend(f"{gate}: {i['message']}" for i in found if i["tag"] == "FAIL")
            if gate == "L5-freeze" and not any(r.startswith("L5-freeze") for r in refused):
                refused.extend(f"{gate}: {p}" for p in gate_model.approval_problems(root, feature, cfg))
        else:
            later = next((g for g in gate_model.GATES[idx + 1:] if gates[g] in gate_model.COMPLETE), None)
            if later:
                refused.append(f"{gate}: the later gate {later} is {gates[later]}; reset the later gates first")
    if refused:
        return emit(AREA, "status", [item("REFUSED", r) for r in refused], "nothing changed", _json(args))
    meta = {k: (dict(v) if isinstance(v, dict) else v) for k, v in status.meta.items()}
    meta["gates"] = dict(meta.get("gates", {}))
    changes = []
    for gate, state in wanted:
        if meta["gates"].get(gate, "pending") != state:
            changes.append(f"{gate}: {meta['gates'].get(gate, 'pending')} -> {state}")
            meta["gates"][gate] = state
    if not changes:
        return emit(AREA, "status", [item("SAME", "the gates already have these states")], "no change", _json(args))
    gate_model.recompute_phase(meta)
    text = gate_model.render_status(status.prefix, meta, status.body)
    problems = gate_model.status_errors(text)
    if problems:
        return emit(AREA, "status", [item("FAIL", f"the updated status would not satisfy C10: {p}") for p in problems],
                    "nothing written", _json(args))
    rel = status.path.relative_to(root).as_posix()
    if args.apply:
        gate_model.write_atomic(status.path, text)
    out = [item("CHANGED", c + ("" if args.apply else " (dry run; use --apply)"), rel) for c in changes]
    out.append(item("CHANGED", f"phase is now {meta['phase']}", rel))
    return emit(AREA, "status", out, f"{feature} phase {meta['phase']}", _json(args))


# ------------------------------------------------------------------ check

def _check(args):
    root = _root(args)
    try:
        cfg = _cfg(args, root)
    except config.ConfigError as exc:
        return _fail("check", args, str(exc))
    items = gate_model.check_feature(root, args.feature, cfg, head=args.head, today=args.today, release=args.release,
                                     strict_commits=args.strict_commits, commit_check=not args.no_commit_check,
                                     readiness_path=args.readiness, catalog=args.catalog, lag=args.lag)
    bad = [i for i in items if i["tag"] == "FAIL"]
    return emit(AREA, "check", items, f"{args.feature}: {len(bad)} failure(s)" if bad else f"{args.feature}: every gate rule holds", _json(args))


# ------------------------------------------------------------------ thresholds

def _thresholds(args):
    root = _root(args)
    try:
        cfg = _cfg(args, root)
    except config.ConfigError as exc:
        return _fail("thresholds", args, str(exc))
    if args.propose:
        items = thresholds.propose(root, args.file, cfg, args.propose, reason=args.reason, today=args.today, apply=args.apply)
    else:
        items = thresholds.check(root, args.file, cfg, against=args.against)
    bad = [i for i in items if i["tag"] in ("FAIL", "REFUSED")]
    return emit(AREA, "thresholds", items, "refused" if bad else "thresholds hold", _json(args))


# ------------------------------------------------------------------ promote

def _promote(args):
    root = _root(args)
    if args.pr:
        if not args.repo:
            return emit(AREA, "promote", [item("REFUSED", "--pr needs --repo owner/repo")], "refused", _json(args))
        items = promote.promote_pr(args.repo, args.pr, sha=args.sha, evidence_path=args.local_evidence,
                                   required=args.require or (), apply=args.apply)
    elif args.local_evidence:
        branch = args.branch or gate_model.GIT.branch(root)
        if not branch or not args.into:
            return emit(AREA, "promote", [item("REFUSED", "a local promotion names --branch (default: the checked-out branch) and --into")],
                        "refused", _json(args))
        items = promote.promote_local(root, branch, args.into, args.local_evidence, sha=args.sha, apply=args.apply)
    else:
        return emit(AREA, "promote", [item("REFUSED", "nothing proves a green head: give --pr (with --repo) to read the checks, or "
                                                     "--local-evidence with --branch and --into for a repository without CI")],
                    "refused", _json(args))
    code_tags = {i["tag"] for i in items}
    summary = "refused" if code_tags & {"REFUSED", "FAIL"} else ("pending: wait and run again" if "WARN" in code_tags else "green")
    return emit(AREA, "promote", items, f"promotion {summary}", _json(args))


# ------------------------------------------------------------------ the Stop handler

def _project_root(start):
    cur = Path(start).resolve()
    for p in [cur, *list(cur.parents)[:6]]:
        if (p / "specs").is_dir():
            return p
    return None


def _scope_paths(root, feature):
    try:
        meta, _ = fm.parse(evidence.strip_comments(gate_model.read(root / "specs" / feature / "status.md")))
    except (OSError, ValueError):
        return []
    scope = meta.get("scope", [])
    return [str(s).strip("/") for s in scope] if isinstance(scope, list) else []


def _units_in_scope(root, dirty):
    """Features of this project that have uncommitted changes: a path under specs/<feature>/ or under a `scope` path of the
    feature's status file."""
    found = []
    for status in sorted((root / "specs").glob("*/status.md")):
        feature = status.parent.name
        scope = [f"specs/{feature}"] + _scope_paths(root, feature)
        if any(d == s or d.startswith(s + "/") for d in dirty for s in scope):
            found.append(feature)
    return found


def _append_unverified(root, feature, today, message):
    path = root / "specs" / feature / "status.md"
    if not path.is_file():
        return
    line = f"- {today} UNVERIFIED: stopped with a failing gate check: {message[:200]}"
    text = path.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n")
    if line in text:
        return
    gate_model.write_atomic(path, text + ("" if text.endswith("\n") else "\n") + line + "\n")


def handler(payload):
    """Stop hook (C31 handler result). Fail open: an unreadable project, git or configuration allows the stop."""
    allow = {"contract_version": "1.0", "exit_code": 0, "output": None}
    try:
        root = _project_root((payload or {}).get("cwd") or os.getcwd())
        if root is None:
            return allow
        dirty = gate_model.GIT.dirty(root)
        if not dirty:
            return allow
        cfg = config.load(project_root=root).config
        today = datetime.date.today().isoformat()
        failing = {}
        for feature in _units_in_scope(root, dirty):
            found = gate_model.check_feature(root, feature, cfg, today=today)
            bad = [i["message"] for i in found if i["tag"] == "FAIL"]
            if bad:
                failing[feature] = bad
        if not failing:
            return allow
        if (payload or {}).get("stop_hook_active") is True:
            for feature, bad in failing.items():
                _append_unverified(root, feature, today, bad[0])
            return allow
        parts = [f"{feature}: " + " | ".join(bad[:3]) for feature, bad in failing.items()]
        reason = ("Gate check fails for a unit you changed: " + "; ".join(parts) + ". Fix it and stop again; if you stop again "
                  "without fixing it, an UNVERIFIED line is written to the unit's status file and the stop is allowed.")
        return {"contract_version": "1.0", "exit_code": 0, "output": {"decision": "block", "reason": reason}}
    except Exception:   # noqa: BLE001 (a quality hook never blocks on its own error)
        return allow


HOOKS = {"gate-stop": handler}


def _hook_stop(args):
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    result = handler(payload)
    if result["output"] is not None:
        print(json.dumps(result["output"]))
    if result.get("message"):
        print(result["message"], file=sys.stderr)
    return result["exit_code"]


# ------------------------------------------------------------------ registration

def register(subparsers):
    p = subparsers.add_parser("evidence-lint", help="check a gate evidence file (C09)")
    p.add_argument("file", help="specs/<feature>/evidence/<gate>.md")
    p.add_argument("--gate", help="the gate the file must be evidence for")
    p.add_argument("--feature", help="the feature the file must be evidence for")
    p.add_argument("--root", help="the project folder (default: the current folder)")
    p.add_argument("--today", help="today's date YYYY-MM-DD (tests)")
    p.set_defaults(func=_evidence_lint)

    p = subparsers.add_parser("status", help="show or update the status file of a feature (C10)")
    p.add_argument("feature", help="the feature id NNN-slug")
    p.add_argument("--root", help="the project folder (default: the current folder)")
    p.add_argument("--set", action="append", metavar="GATE=STATE", help="set a gate to pending, passed or failed (never waived); repeatable")
    p.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    p.add_argument("--head", help="the commit evidence is checked against (default: HEAD)")
    p.add_argument("--no-commit-check", action="store_true", help="do not verify evidence commits against git")
    p.add_argument("--today", help="today's date YYYY-MM-DD (tests)")
    p.set_defaults(func=_status)

    p = subparsers.add_parser("check", help="enforce the gate rules of a feature")
    p.add_argument("feature", help="the feature id NNN-slug")
    p.add_argument("--root", help="the project folder (default: the current folder)")
    p.add_argument("--head", help="the head commit (default: HEAD)")
    p.add_argument("--release", action="store_true", help="apply the release rules (readiness gaps, current evidence) before L9 is passed")
    p.add_argument("--strict-commits", action="store_true", help="require every gate's evidence to describe the head")
    p.add_argument("--no-commit-check", action="store_true", help="do not verify evidence commits against git (reported as a WARN)")
    p.add_argument("--readiness", help="the readiness document (default: data/derived/readiness.json or docs/design/readiness.json)")
    p.add_argument("--catalog", help="the contract catalog (default: docs/contracts/catalog.md)")
    p.add_argument("--lag", type=int, default=0, help="commits the readiness document may be behind the head (default 0)")
    p.add_argument("--today", help="today's date YYYY-MM-DD (tests)")
    p.set_defaults(func=_check)

    p = subparsers.add_parser("thresholds", help="check or propose ratcheting thresholds (C11)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="check the ratchet (the default)")
    mode.add_argument("--propose", metavar="NAME=VALUE", help="raise (or add) a threshold; a decrease needs a waiver")
    p.add_argument("--root", help="the project folder (default: the current folder)")
    p.add_argument("--file", default=thresholds.DEFAULT_PATH, help=f"the thresholds file (default {thresholds.DEFAULT_PATH})")
    p.add_argument("--reason", help="why the value changes (recorded in the history)")
    p.add_argument("--against", metavar="REF", help="compare with the file at this git reference (a committed baseline)")
    p.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    p.add_argument("--today", help="today's date YYYY-MM-DD (tests)")
    p.set_defaults(func=_thresholds)

    p = subparsers.add_parser("promote", help="merge only on green for the exact head commit")
    p.add_argument("--repo", help="owner/repo of the pull request")
    p.add_argument("--pr", help="the pull request number")
    p.add_argument("--branch", help="a local branch to promote (default: the checked-out branch)")
    p.add_argument("--into", help="the branch that receives the merge (local promotion)")
    p.add_argument("--local-evidence", metavar="FILE", help="test output naming the exact head SHA, for a head without CI checks")
    p.add_argument("--sha", help="the head the caller reviewed; refuse if the head moved")
    p.add_argument("--require", action="append", metavar="CHECK", help="a check that must have run and succeeded; repeatable")
    p.add_argument("--root", help="the repository folder for a local promotion (default: the current folder)")
    p.add_argument("--apply", action="store_true", help="run the merge (default: print the command)")
    p.set_defaults(func=_promote)

    p = subparsers.add_parser("hook-stop", help="the Stop hook as a command: reads the payload on stdin")
    p.set_defaults(func=_hook_stop)
