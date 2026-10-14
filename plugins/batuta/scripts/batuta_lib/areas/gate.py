"""Area `gate`: only verified results are approved and promoted.

Verbs:
    evidence-lint  check one gate evidence file (C09): verdict rules, reproductions, routed role and model
    status         show or update the status file of a feature (C10), atomically
    check          enforce gate order, evidence, the freeze approval, human waivers, phase and the release rules
    thresholds     the quality thresholds only ratchet up (C11): `--check` or `--propose name=value`
    promote        merge only on green for the exact head commit (a pull request, or a local branch with evidence)
    tests-record   write the contract-tests record (C34) that skeleton check and the release gate read
    hook-stop      the Stop hook as a command (reads the hook payload on stdin)

The Stop handler `gate-stop` blocks once when a unit with uncommitted changes has a failing gate check; on the second
attempt it appends a dated UNVERIFIED line to the unit's status file and lets the session end. A session that changed no
unit is never blocked. Files are written only with `--apply` (dry run by default), atomically.
Exit codes: 0 ok, 1 failure or refusal, 2 warnings or honest partial.
"""
import datetime
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from batuta_lib import config, evidence, gate_model, promote, readiness, thresholds
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm
from batuta_lib.output import emit, item

AREA = "gate"
HELP = "Gates: evidence lint, status, gate check, ratcheting thresholds, promotion on green, Stop hook."


def _json(args):
    return bool(getattr(args, "json", False))


def _root(args):
    return Path(getattr(args, "root", None) or ".")


def _resolved(args, root):
    return config.load(config_arg=getattr(args, "config", None), project_root=root)


def _cfg(args, root):
    return _resolved(args, root).config


def _from_project(resolved):
    """True when the configuration is the project's (or the defaults): then its gates settings are read from the base revision."""
    return resolved.source in ("project", "defaults")


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
        resolved = _resolved(args, root)
        wanted = [_parse_set(s) for s in args.set]
    except (config.ConfigError, ValueError) as exc:
        return emit(AREA, "status", [item("REFUSED", str(exc))], "nothing changed", _json(args))
    base, _problem = gate_model.base_revision(root)
    cfg, _notes = gate_model.settings_from_base(root, resolved.config, base, _from_project(resolved))
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
        resolved = _resolved(args, root)
    except config.ConfigError as exc:
        return _fail("check", args, str(exc))
    items = gate_model.check_feature(root, args.feature, resolved.config, head=args.head, today=args.today, release=args.release,
                                     strict_commits=args.strict_commits, commit_check=not args.no_commit_check,
                                     readiness_path=args.readiness, catalog=args.catalog, lag=args.lag, against=args.against,
                                     project_config=_from_project(resolved))
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


# ------------------------------------------------------------------ tests-record

def _run_test_file(root, rel, timeout):
    """pass, fail or skip for one test file: its unittest run exits 0 with tests run; no test ran is a skip."""
    if not rel.endswith(".py"):
        return "skip"
    if not (root / rel).is_file():
        return "fail"
    parent = Path(rel).parent.as_posix() or "."
    cmd = [sys.executable, "-B", "-m", "unittest", "discover", "-s", parent, "-p", Path(rel).name]
    try:
        p = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    except (OSError, subprocess.TimeoutExpired):
        return "fail"
    m = re.search(r"^Ran (\d+) tests?", p.stdout + p.stderr, re.M)
    ran = int(m.group(1)) if m else 0
    if p.returncode == 0 and ran > 0:
        return "pass"
    return "skip" if ran == 0 and p.returncode in (0, 5) else "fail"


def _tests_record(args):
    root = _root(args)
    refused = lambda msg: emit(AREA, "tests-record", [item("REFUSED", msg)], "nothing written", _json(args))   # noqa: E731
    info = gate_model.GIT.info(root)
    if info is None:
        return refused("not a git repository with a commit: a record names the commit the tests ran at")
    head, commit = info[1], info[1]
    if args.commit:
        commit = gate_model.resolve_commit(gate_model.GIT.history(root, head), args.commit)
        if commit is None:
            return refused(f"commit {args.commit!r} is not in the history of the head")
    results = {}
    if args.run:
        rows, errors = readiness.catalog_rows(root, readiness._abs(root, args.catalog or readiness.CATALOG_PATH))
        if rows is None:
            return refused("; ".join(errors))
        results.update({t: _run_test_file(root, t, args.timeout) for t in readiness.catalog_tests(rows)})
    for text in args.result or []:
        key, sep, value = text.rpartition("=")
        if not sep or not key:
            return refused(f"'{text}' is not <test path>=<pass|fail|skip>")
        results[key] = value
    if not results:
        return refused("nothing to record: give --result <test path>=<pass|fail|skip> or --run")
    out_rel = Path(args.output or gate_model.RECORD_PATH).as_posix()
    doc = {"contract_version": "1.0", "commit": commit, "generated": args.today or gate_model.today_iso(), "results": results}
    problems = readiness._validate("C34", doc)
    if problems:
        return emit(AREA, "tests-record", [item("REFUSED", f"the record would not satisfy C34: {p}") for p in problems],
                    "nothing written", _json(args))
    if commit == head and not args.allow_dirty:
        loose = [p for p in (gate_model.GIT.dirty(root) or []) if not p.startswith("specs/") and p != out_rel]
        if loose:
            return refused(f"uncommitted changes outside specs/ ({', '.join(loose[:3])}): the tests did not run at the commit; "
                           f"commit them first (or --allow-dirty)")
    text = json.dumps(doc, indent=2) + "\n"
    target = root / out_rel
    try:
        same = target.is_file() and target.read_text(encoding="utf-8") == text
    except OSError:
        same = False
    if same:
        return emit(AREA, "tests-record", [item("SAME", f"{out_rel} already holds this record", out_rel)], "no change", _json(args))
    tag = "CHANGED" if target.is_file() else "NEW"
    if args.apply:
        gate_model.write_atomic(target, text)
    note = "" if args.apply else " (dry run; use --apply)"
    return emit(AREA, "tests-record", [item(tag, f"{len(results)} result(s) at {commit[:12]}{note}", out_rel)],
                f"record for {commit[:12]}", _json(args))

# ------------------------------------------------------------------ the Stop handler

def _project_root(start):
    cur = Path(start).resolve()
    for p in [cur, *list(cur.parents)[:6]]:
        if (p / "specs").is_dir():
            return p
    return None


def _brace_expand(pattern):
    """`a/{b,c}.py` as ['a/b.py', 'a/c.py'] (one level, as the sizing's write scopes use it)."""
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m:
        return [pattern]
    return [x for alt in m.group(1).split(",") for x in _brace_expand(pattern[:m.start()] + alt + pattern[m.end():])]


def _in_scope(path, scopes):
    for scope in scopes:
        for pat in _brace_expand(scope):
            bare = pat.rstrip("/")
            if path == bare or path.startswith(bare + "/") or fnmatch.fnmatchcase(path, pat):
                return True
    return False


def _unit_scopes(root, feature, cfg):
    """The write scopes of the units that carry the feature's tasks: the `Unit` column of specs/<feature>/tasks.md names the
    units, the sizing's Parallel units table (in the coordination root) gives each unit's write scope."""
    try:
        tasks = gate_model.read(root / "specs" / feature / "tasks.md")
    except OSError:
        return []
    hit = core.read_table(tasks, {"headers": ["Task", "Unit"], "headers_match": "contains"})
    units = {str(r.get("Unit", "")).strip() for r in (hit[0] if hit else [])} - {"", "-"}
    coord = root / cfg.get("coordination_root", config.PROJECT_DIR)
    scopes = []
    for sizing in [coord / "sizing.md", *sorted(coord.glob("*/sizing.md")), root / "sizing.md"]:
        try:
            text = gate_model.read(sizing)
        except OSError:
            continue
        found = core.read_table(text, {"headers": ["Unit", "Write scope"], "headers_match": "contains", "section": "Parallel units"}, ci=True)
        for row in (found[0] if found else []):
            if str(row.get("Unit", "")).strip() in units:
                scopes.extend(core._scopes(str(row.get("Write scope", ""))))
        if found:
            break
    return scopes


def _scope_paths(root, feature, cfg):
    """The paths a unit owns beyond its specs folder: the `scope: [paths]` of its status file and the write scopes of its units."""
    try:
        meta, _ = fm.parse(evidence.strip_comments(gate_model.read(root / "specs" / feature / "status.md")))
    except (OSError, ValueError):
        meta = {}
    declared = meta.get("scope", [])
    own = [str(s).strip() for s in declared] if isinstance(declared, list) else []
    return own + _unit_scopes(root, feature, cfg)


def _units_in_scope(root, dirty, cfg):
    """Features of this project that have uncommitted changes: a path under specs/<feature>/, under a `scope` path of the
    feature's status file or in the write scope of a unit that carries its tasks."""
    found = []
    for status in sorted((root / "specs").glob("*/status.md")):
        feature = status.parent.name
        scopes = [f"specs/{feature}"] + _scope_paths(root, feature, cfg)
        if any(_in_scope(d, scopes) for d in dirty):
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


# The handler's own once-per-failure state (the host's `stop_hook_active` flag is only one of two ways it knows a stop is
# the second attempt): one line per held failure, bounded, replaced atomically.
STATE_NAME = "gate-stop.state"
MAX_STATE_ENTRIES = 1000


def _state_path(root, cfg):
    return root / cfg.get("coordination_root", config.PROJECT_DIR) / STATE_NAME


def _held_before(root, cfg, key):
    try:
        return key in gate_model.read(_state_path(root, cfg)).split("\n")
    except OSError:
        return False


def _remember_hold(root, cfg, key):
    """Record that this failure was held once. At most MAX_STATE_ENTRIES keys are kept (the oldest dropped first)."""
    path = _state_path(root, cfg)
    try:
        try:
            lines = [x for x in gate_model.read(path).split("\n") if x]
        except OSError:
            lines = []
        if key in lines:
            return
        gate_model.write_atomic(path, "\n".join((lines + [key])[-MAX_STATE_ENTRIES:]) + "\n")
    except OSError:
        pass   # the block still stands; only the extra loop guard is lost


def _failure_key(payload, failing):
    """One session's one set of failures: a different failure, or a different session, is held once again."""
    digest = hashlib.sha256("\n".join(f"{f}: {m}" for f, bad in sorted(failing.items()) for m in bad).encode("utf-8")).hexdigest()
    session = str((payload or {}).get("session_id") or "nosession").replace("\n", " ")[:120]
    return f"{session}|{digest}"


def handler(payload):
    """Stop hook (C31 handler result). Fail open: an unreadable project, git or configuration allows the stop, and says why."""
    allow = {"contract_version": "1.0", "exit_code": 0, "output": None}
    try:
        root = _project_root((payload or {}).get("cwd") or os.getcwd())
        if root is None:
            return allow
        dirty = gate_model.GIT.dirty(root)
        if not dirty:
            return allow
        resolved = config.load(project_root=root)
        cfg = resolved.config
        today = datetime.date.today().isoformat()
        failing = {}
        for feature in _units_in_scope(root, dirty, cfg):
            found = gate_model.check_feature(root, feature, cfg, today=today, project_config=_from_project(resolved))
            bad = [i["message"] for i in found if i["tag"] == "FAIL"]
            if bad:
                failing[feature] = bad
        if not failing:
            return allow
        key = _failure_key(payload, failing)
        if (payload or {}).get("stop_hook_active") is True or _held_before(root, cfg, key):
            for feature, bad in failing.items():
                _append_unverified(root, feature, today, bad[0])
            return allow
        _remember_hold(root, cfg, key)
        parts = [f"{feature}: " + " | ".join(bad[:3]) for feature, bad in failing.items()]
        reason = ("Gate check fails for a unit you changed: " + "; ".join(parts) + ". Fix it and stop again; if you stop again "
                  "without fixing it, an UNVERIFIED line is written to the unit's status file and the stop is allowed.")
        return {"contract_version": "1.0", "exit_code": 0, "output": {"decision": "block", "reason": reason}}
    except Exception as exc:   # noqa: BLE001 (a quality hook never blocks on its own error, and says why)
        return {**allow, "message": f"gate-stop: allowed the stop after an internal error: {exc!r}"}

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
    p.add_argument("--against", metavar="REV", help="the base revision thresholds and routing are read from (default: the merge-base with the target branch)")
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

    p = subparsers.add_parser("tests-record", help="write the contract-tests record (C34)")
    p.add_argument("--root", help="the project folder (default: the current folder)")
    p.add_argument("--output", help=f"the record file (default {gate_model.RECORD_PATH})")
    p.add_argument("--commit", help="the commit the tests ran at (default: HEAD)")
    p.add_argument("--result", action="append", metavar="TEST=RESULT", help="a result: <test path>[::name]=pass|fail|skip; repeatable")
    p.add_argument("--run", action="store_true", help="run the python test files the catalog names and record each")
    p.add_argument("--catalog", help="the contract catalog for --run (default: docs/contracts/catalog.md)")
    p.add_argument("--timeout", type=int, default=600, help="seconds allowed per test file with --run (default 600)")
    p.add_argument("--allow-dirty", action="store_true", help="record at HEAD although the working tree has uncommitted changes")
    p.add_argument("--apply", action="store_true", help="write the record (default: dry run)")
    p.add_argument("--today", help="today's date YYYY-MM-DD (tests)")
    p.set_defaults(func=_tests_record)
    p = subparsers.add_parser("hook-stop", help="the Stop hook as a command: reads the payload on stdin")
    p.set_defaults(func=_hook_stop)
