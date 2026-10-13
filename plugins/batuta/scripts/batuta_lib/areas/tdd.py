"""Area `tdd`: test-first enforced on artifacts and history (lock, commit grammar, red-before-green replay).

Verbs: `lock` writes the append-only test lock (C07); `change-request new` appends an `open` row to a C33 request file;
`commit` is a thin helper that stages the right files and writes a C32 message for a `[red]`, `[green]` or `[refactor]`
commit; `check` proves from git history that every green came after a red, that no locked test changed, that no skip
or focus marker crept in and that assertions never decreased, with `--replay` to prove each red test fails at its commit.

Optional `tdd` block of batuta.json (C01 allows extra keys): `test_command` (default unittest discovery),
`replay_timeout_seconds` (default 300), `lock_file` (default `.batuta/test-lock.json`), `markers`
(`{"python": [...], "javascript": [...]}` replacing the default marker list of a language).

Writes are dry runs unless `--apply` is given. Exit codes: 0 ok, 1 failure or refusal, 2 warnings.
"""
import os
import uuid
from pathlib import Path

from batuta_lib import config
from batuta_lib import contract as core
from batuta_lib import tdd_history as hist
from batuta_lib import tdd_lock as lk
from batuta_lib import test_markers as tm
from batuta_lib.output import emit, item

AREA = "tdd"
HELP = "Test-first on artifacts and history: test lock, red and green commits, history check and replay."
SUBJECT_MAX = 72
SUPPORT_DIRS = {"tests", "test", "__tests__", "fixtures"}


class Refusal(Exception):
    """The request breaks a rule; carried as a REFUSED line."""


def _setup(args):
    """(repo root, Settings, config resolved). Raises hist.GitError or config.ConfigError."""
    hist.ensure_supported()
    root = hist.toplevel(getattr(args, "repo", None) or ".")
    return root, *_settings(args, root)


def _settings(args, root):
    resolved = config.load(getattr(args, "config", None), project_root=root)
    block = resolved.config.get("tdd", {})
    if not isinstance(block, dict):
        raise config.ConfigError("the 'tdd' block of the configuration must be an object")
    s = hist.Settings(temp_root=Path(resolved.config["roots"]["temp"]))
    if "test_command" in block:
        if not isinstance(block["test_command"], str) or not block["test_command"].strip():
            raise config.ConfigError("tdd.test_command must be a non-empty string")
        s.test_command = block["test_command"]
    if "replay_timeout_seconds" in block:
        t = block["replay_timeout_seconds"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t <= 0:
            raise config.ConfigError("tdd.replay_timeout_seconds must be a positive number")
        s.replay_timeout = float(t)
    if "lock_file" in block:
        why = lk.bad_relpath(block["lock_file"])
        if why:
            raise config.ConfigError(f"tdd.lock_file: {why}")
        s.lock_path = block["lock_file"]
    if "markers" in block:
        m = block["markers"]
        if not (isinstance(m, dict) and all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in m.values())):
            raise config.ConfigError("tdd.markers must map a language to a list of marker names")
        s.markers = m
    if getattr(args, "lock", None):
        why = lk.bad_relpath(args.lock)
        if why:
            raise config.ConfigError(f"--lock: {why}")
        s.lock_path = args.lock
    return s, resolved


def _fail(area_verb, items, as_json, message):
    items.append(item("FAIL", message))
    return emit(AREA, area_verb, items, f"tdd {area_verb}: failed", as_json)


def _relative_file(root, rel):
    """The file for a repository-relative POSIX path, or raise Refusal."""
    why = lk.bad_relpath(rel)
    if why:
        raise Refusal(why)
    path = Path(root) / rel
    try:
        path.resolve().relative_to(Path(root).resolve())
    except ValueError:
        raise Refusal(f"{rel} resolves outside the repository") from None
    return path


# ------------------------------------------------------------------ lock


def _lock(args):
    as_json, items = getattr(args, "json", False), []
    try:
        root, settings, _ = _setup(args)
    except (hist.GitError, config.ConfigError) as exc:
        return _fail("lock", items, as_json, str(exc))
    lock_file = root / settings.lock_path
    summary = "tdd lock: dry run, nothing written (use --apply)" if not args.apply else "tdd lock: done"

    def refuse(message, path=None):
        items.append(item("REFUSED", message, path))

    if not lk.TASK_ID.match(args.task):
        refuse(f"task id {args.task!r} must look like T-001")
    if bool(args.supersedes) != bool(args.change_request):
        refuse("--supersedes and --change-request <id> go together: a changed test is locked again only through an approved request")
    try:
        text = lock_file.read_text(encoding="utf-8-sig") if lock_file.is_file() else None
    except OSError as exc:
        return _fail("lock", items, as_json, f"cannot read {settings.lock_path}: {exc}")
    entries, error = lk.parse_lock(text)
    if error:
        return _fail("lock", items, as_json, f"{settings.lock_path} is unusable: {error}")
    entries = entries or []
    live = lk.live_entries(entries)
    rows_by_id, problem_files = lk.load_requests(root) if args.supersedes else ({}, {})
    try:
        locked_commit = hist.head(root) or "unborn"
    except hist.GitError as exc:
        return _fail("lock", items, as_json, str(exc))
    stamp = lk.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    new_entries, seen = [], set()
    for rel in args.paths:
        if rel in seen:
            continue
        seen.add(rel)
        try:
            file = _relative_file(root, rel)
        except Refusal as exc:
            refuse(str(exc), rel)
            continue
        if not file.is_file():
            refuse(f"{rel} does not exist", rel)
            continue
        data = file.read_bytes()
        digest = tm.normalized_sha256(data)
        current = live.get(rel)
        if current is not None and current["sha256"] == digest:
            items.append(item("SAME", f"{rel} is already locked with this hash (task {current['task_id']})", rel))
            continue
        entry = {"path": rel, "sha256": digest, "task_id": args.task,
                 "req_ids": tm.requirement_ids(data.decode("utf-8", "replace")), "locked_commit": locked_commit, "locked_at": stamp}
        if current is None:
            if args.supersedes:
                refuse(f"{rel} is not locked, so there is nothing to supersede", rel)
                continue
            verb, message = "NEW", f"{'locked' if args.apply else 'would lock'} {rel} for {args.task} ({digest[:12]})"
        else:
            if not args.supersedes:
                refuse(f"{rel} is locked with another hash ({current['sha256'][:12]}); the lock is append-only: change a locked test "
                       f"only through an approved change request and lock again with --supersedes --change-request <id>", rel)
                continue
            row, _file, why = lk.lookup(rows_by_id, problem_files, args.change_request, {rel})
            if why:
                refuse(f"cannot supersede the lock of {rel}: {why}", rel)
                continue
            entry["supersedes"] = current["sha256"]
            entry["change_request"] = args.change_request
            verb = "CHANGED"
            message = (f"{'superseded' if args.apply else 'would supersede'} the lock of {rel} under {args.change_request} "
                       f"({current['sha256'][:12]} replaced by {digest[:12]})")
        items.append(item(verb, message, rel))
        if not entry["req_ids"]:
            items.append(item("WARN", f"{rel} names no requirement: add a '# REQ: REQ-X-001' line so the trace can follow", rel))
        new_entries.append(entry)

    if any(i["tag"] == "REFUSED" for i in items):
        return emit(AREA, "lock", items, "tdd lock: refused, nothing written", as_json)
    if new_entries:
        text_out = lk.dump_lock(entries + new_entries)
        again, problem = lk.parse_lock(text_out)   # the contract test on the producing side
        if problem:
            return _fail("lock", items, as_json, f"the lock to write is not valid: {problem}")
        if args.apply:
            lk.atomic_write(lock_file, text_out)
            items.append(item("OK", f"wrote {len(new_entries)} entr{'y' if len(new_entries) == 1 else 'ies'} to {settings.lock_path}"))
    return emit(AREA, "lock", items, summary, as_json)


# ------------------------------------------------------------------ change-request new


def _change_request_new(args):
    as_json, items = getattr(args, "json", False), []
    try:
        hist.ensure_supported()
        try:
            root = hist.toplevel(getattr(args, "repo", None) or ".")
        except hist.GitError:
            root = Path(getattr(args, "repo", None) or ".").resolve()
    except hist.GitError as exc:
        return _fail("change-request new", items, as_json, str(exc))
    problems = []
    why = lk.bad_relpath(args.test)
    if why:
        problems.append(why)
    if not lk.REQ_ID.match(args.requirement):
        problems.append(f"requirement {args.requirement!r} must look like REQ-AUTH-001")
    if args.feature is not None and not lk.FEATURE.match(args.feature):
        problems.append(f"feature {args.feature!r} must be a folder name such as 001-auth")
    for name in ("reason", "proposed"):
        if not str(getattr(args, name)).strip():
            problems.append(f"--{name} must not be empty")
    if problems:
        for p in problems:
            items.append(item("REFUSED", p))
        return emit(AREA, "change-request new", items, "tdd change-request new: refused, nothing written", as_json)

    rel = f"specs/{args.feature}/{lk.REQUEST_FILE}" if args.feature else f"specs/{lk.REQUEST_FILE}"
    target = root / rel
    existing = target.read_text(encoding="utf-8-sig") if target.is_file() else None
    texts = [(root / p).read_text(encoding="utf-8-sig") for p in lk.request_paths(root)]
    rid = lk.next_request_id(texts)
    date = lk.now_utc().date().isoformat()
    try:
        text = lk.append_request(existing, lk.request_row(rid, args.test, args.requirement, args.reason, args.proposed, date),
                                 args.feature)
    except ValueError as exc:
        return _fail("change-request new", items, as_json, f"{rel}: {exc}")
    _rows, errors = lk.parse_requests(text)   # the contract test on the producing side
    if errors:
        return _fail("change-request new", items, as_json, f"{rel} would not satisfy C33: {'; '.join(errors[:3])}")
    items.append(item("NEW" if existing is None else "CHANGED",
                      f"{'added' if args.apply else 'would add'} request {rid} (open) for {args.test} to {rel}", rel))
    if args.apply:
        lk.atomic_write(target, text)
    summary = "tdd change-request new: done" if args.apply else "tdd change-request new: dry run, nothing written (use --apply)"
    return emit(AREA, "change-request new", items, summary, as_json)


# ------------------------------------------------------------------ commit


def _is_test_support(rel):
    return tm.is_test_path(rel) or bool(set(rel.split("/")[:-1]) & SUPPORT_DIRS)


def _commit(args):
    as_json, items = getattr(args, "json", False), []
    kind, task = next((k, getattr(args, k)) for k in ("red", "green", "refactor") if getattr(args, k))
    try:
        root, settings, _ = _setup(args)
    except (hist.GitError, config.ConfigError) as exc:
        return _fail("commit", items, as_json, str(exc))

    def refused(message):
        items.append(item("REFUSED", message))
        return emit(AREA, "commit", items, "tdd commit: refused, nothing staged or committed", as_json)

    if not lk.TASK_ID.match(task):
        return refused(f"task id {task!r} must look like T-001")
    title = " ".join(args.message.split())
    subject = f"[{kind}] {task} {title}"
    if not title:
        return refused("-m needs a title")
    if len(subject) > SUBJECT_MAX:
        return refused(f"the subject is {len(subject)} characters, C32 allows {SUBJECT_MAX}: {subject!r}")
    text = subject + "\n"
    if args.body and args.body.strip():
        text += "\n" + args.body.strip() + "\n"
    if args.approved:
        text += f"\n{core.RESERVED_TRAILER}: {args.approved}\n"
    problems = core.check_commit_message(text, lk.schema("C32"))
    if problems:
        return refused("the message breaks C32: " + "; ".join(problems))

    paths = list(dict.fromkeys(args.paths))
    for rel in paths:
        why = lk.bad_relpath(rel)
        if why:
            return refused(why)
    lock_rel = settings.lock_path
    try:
        working = lk.parse_lock((root / lock_rel).read_text(encoding="utf-8-sig") if (root / lock_rel).is_file() else None)
        has_commits = hist.head(root) is not None
        committed = lk.parse_lock(hist.show(root, "HEAD", lock_rel) if has_commits else None)
        staged = hist.staged_paths(root)
        red_seen = any(m and m.group(1) == "red" and m.group(2) == task
                       for m in map(hist.SUBJECT.match, hist.subjects(root, "HEAD"))) if has_commits else False
    except hist.GitError as exc:
        return _fail("commit", items, as_json, str(exc))
    for state, where in ((working, "working copy"), (committed, "last commit")):
        if state[1]:
            return refused(f"the lock file in the {where} is unusable: {state[1]}")
    work_live = lk.live_entries(working[0] or [])
    locked = {e["path"] for e in (working[0] or []) + (committed[0] or [])}

    if kind == "red":
        stage_paths = [p for p in paths if p != lock_rel]
        if not any(tm.is_test_path(p) for p in stage_paths):
            return refused("a [red] commit carries at least one test file")
        for rel in stage_paths:
            if not _is_test_support(rel):
                return refused(f"{rel} is not a test file or test support file: a [red] commit holds tests and the lock only")
            if tm.is_test_path(rel):
                entry = work_live.get(rel)
                try:
                    digest = tm.normalized_sha256(_relative_file(root, rel).read_bytes())
                except (Refusal, OSError) as exc:
                    return refused(f"cannot read {rel}: {exc}")
                if entry is None or entry["sha256"] != digest:
                    return refused(f"{rel} is not locked with its current content: run 'tdd lock --task {task} {rel} --apply' first "
                                   f"(lock file {lock_rel})")
        if not (root / lock_rel).is_file():
            return refused(f"there is no lock file {lock_rel}: lock the tests first")
        to_stage = stage_paths + [lock_rel]
    else:
        if lock_rel in paths:
            return refused(f"a [{kind}] commit never touches the lock file {lock_rel}")
        hit = [p for p in paths if p in locked]
        if hit:
            return refused(f"{hit[0]} is a locked test: a [{kind}] commit never changes one (record a change request instead: "
                           f"'tdd change-request new', then wait for its approval)")
        if kind == "green" and not red_seen:
            return refused(f"there is no earlier [red] commit for {task}: write and commit the failing tests first")
        to_stage = paths
    extra = sorted(staged - set(to_stage))
    if extra:
        return refused(f"other files are already staged ({', '.join(extra[:5])}): unstage them so the commit holds only what its kind allows")

    for rel in to_stage:
        items.append(item("OK", f"{'staging' if args.apply else 'would stage'} {rel}", rel))
    items.append(item("OK", f"{'committing' if args.apply else 'would commit'}: {subject}"))
    if not args.apply:
        return emit(AREA, "commit", items, "tdd commit: dry run, nothing staged or committed (use --apply)", as_json)
    message_dir = Path(settings.temp_root)
    message_dir.mkdir(parents=True, exist_ok=True)
    message_file = message_dir / f"tdd-commit-{uuid.uuid4().hex}.txt"
    message_file.write_text(text, encoding="utf-8", newline="\n")
    try:
        hist.stage(root, to_stage)
        sha = hist.commit_with_file(root, message_file)
    except hist.GitError as exc:
        try:
            hist.unstage(root, to_stage)
        except hist.GitError:
            pass
        return _fail("commit", items, as_json, str(exc))
    finally:
        try:
            os.unlink(message_file)
        except OSError:
            pass
    items.append(item("OK", f"committed {(sha or '')[:7]}: {subject}"))
    return emit(AREA, "commit", items, "tdd commit: done", as_json)


# ------------------------------------------------------------------ check


def _check(args):
    as_json, items = getattr(args, "json", False), []
    try:
        root, settings, _ = _setup(args)
        items = hist.Checker(root, settings, args.range or "HEAD").run(replay=args.replay)
    except (hist.GitError, config.ConfigError) as exc:
        return _fail("check", items, as_json, str(exc))
    failed = any(i["tag"] in ("FAIL", "REFUSED") for i in items)
    summary = "tdd check: failed" if failed else ("tdd check: ok with warnings" if any(i["tag"] == "WARN" for i in items) else "tdd check: ok")
    return emit(AREA, "check", items, summary, as_json)


# ------------------------------------------------------------------ registration


def _common(parser):
    parser.add_argument("--repo", metavar="DIR", default=None, help="the repository (default: the current directory)")
    parser.add_argument("--lock", metavar="PATH", default=None,
                        help=f"the lock file, relative to the repository root (default {lk.DEFAULT_LOCK})")


def register(subparsers):
    p = subparsers.add_parser("lock", help="Lock test files by hash (C07, append-only).",
                              description="Append C07 entries for test files: a path already locked with the same hash is SAME; "
                                          "a changed hash needs --supersedes --change-request <id> of an approved request (C33).")
    _common(p)
    p.add_argument("--task", required=True, metavar="T-NNN", help="the task the tests belong to")
    p.add_argument("paths", nargs="+", metavar="TEST", help="test files, POSIX paths relative to the repository root")
    p.add_argument("--supersedes", action="store_true", help="lock a changed test again (needs --change-request)")
    p.add_argument("--change-request", metavar="ID", default=None, help="the approved change request that authorises it (C33)")
    p.add_argument("--apply", action="store_true", help="write the lock file (default: dry run)")
    p.set_defaults(func=_lock)

    cr = subparsers.add_parser("change-request", help="Record a request to change a locked test (C33).")
    crs = cr.add_subparsers(dest="cr_verb", metavar="<action>", required=True)
    n = crs.add_parser("new", help="Append an open request row; an agent never approves one.")
    n.add_argument("--repo", metavar="DIR", default=None, help="the repository (default: the current directory)")
    n.add_argument("--test", required=True, metavar="PATH", help="the locked test, relative to the repository root")
    n.add_argument("--requirement", required=True, metavar="REQ-ID", help="the requirement the test serves")
    n.add_argument("--reason", required=True, help="why the test is wrong")
    n.add_argument("--proposed", required=True, help="the change that is proposed")
    n.add_argument("--feature", default=None, metavar="NAME", help="the feature folder: specs/<NAME>/test-change-requests.md "
                                                                    "(default specs/test-change-requests.md)")
    n.add_argument("--apply", action="store_true", help="write the file (default: dry run)")
    n.set_defaults(func=_change_request_new)

    c = subparsers.add_parser("commit", help="Stage and commit a [red], [green] or [refactor] step with a C32 message.")
    _common(c)
    kind = c.add_mutually_exclusive_group(required=True)
    for name in ("red", "green", "refactor"):
        kind.add_argument(f"--{name}", metavar="T-NNN", default=None, help=f"commit a [{name}] step of this task")
    c.add_argument("-m", "--message", required=True, metavar="TITLE", help="the commit title (the subject is capped at 72 characters)")
    c.add_argument("--body", default=None, help="free text under the subject")
    c.add_argument("--approved", metavar="ID", default=None, help="add the trailer Test-Change-Approved: <change request id>")
    c.add_argument("paths", nargs="+", metavar="PATH", help="the files to stage (never everything at once)")
    c.add_argument("--apply", action="store_true", help="stage and commit (default: dry run)")
    c.set_defaults(func=_commit)

    k = subparsers.add_parser("check", help="Prove the red and green rules from git history.")
    _common(k)
    k.add_argument("--range", default=None, metavar="GIT-RANGE", help="commits to walk (default: all history up to HEAD)")
    k.add_argument("--replay", action="store_true",
                   help="check each [red] commit out in a temporary worktree and require its new tests to fail")
    k.set_defaults(func=_check)
