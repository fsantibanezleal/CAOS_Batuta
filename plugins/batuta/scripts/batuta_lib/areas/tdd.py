"""Area `tdd`: test-first enforced on artifacts and history (lock, commit grammar, red-before-green replay).

Verbs: `lock` writes the append-only test lock (C07); `change-request new` appends an `open` row to a C33 request file;
`commit` is a thin helper that stages the right files and writes a C32 message for a `[red]`, `[green]` or `[refactor]`
commit; `check` proves from git history that every green came after a red, that no locked test changed, that no skip
or focus marker crept in and that assertions never decreased, with `--replay` to prove each red test fails at its commit.

Optional `tdd` block of batuta.json (C01 allows extra keys): `test_command` (default unittest discovery),
`replay_timeout_seconds` (default 300), `lock_file` (default `.batuta/test-locks.json`), `markers`
(`{"python": [...], "javascript": [...]}` replacing the default marker list of a language).

Writes are dry runs unless `--apply` is given. Exit codes: 0 ok, 1 failure or refusal, 2 warnings.
"""
import os
import re
import tempfile
import threading
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


class Refusal(Exception):
    """The request breaks a rule; carried as a REFUSED line."""


def _setup(args):
    """(repo root, Settings, config resolved). Raises hist.GitError or config.ConfigError."""
    hist.ensure_supported()
    root = hist.toplevel(getattr(args, "repo", None) or ".")
    return root, *_settings(args, root)


def _resolved_config(args, root, base_sha):
    """The configuration a verb works with. `check` passes the base commit of its range: the project file is then read from
    that commit and never from the checked-out tree, which a commit in the range can change. `--config` or BATUTA_CONFIG (CI may
    pass one from outside the repository) wins, as everywhere."""
    explicit = getattr(args, "config", None) or os.environ.get(config.ENV_CONFIG)
    if base_sha is None or explicit:
        return config.load(getattr(args, "config", None), project_root=root)
    data = hist.show(root, base_sha, hist.CONFIG_PATH)
    if data is None:   # no project file at the base commit: the user file or the defaults
        return config.load(None, project_root=None)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / config.FILE_NAME
        path.write_bytes(data)
        return config.load(str(path))


def _settings(args, root, base_sha=None):
    resolved = _resolved_config(args, root, base_sha)
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
    if not lk.FEATURE.match(args.feature):
        problems.append(f"feature {args.feature!r} must be a folder name such as 001-auth")
    for name in ("reason", "proposed"):
        if not str(getattr(args, name)).strip():
            problems.append(f"--{name} must not be empty")
    if problems:
        for p in problems:
            items.append(item("REFUSED", p))
        return emit(AREA, "change-request new", items, "tdd change-request new: refused, nothing written", as_json)

    rel = f"specs/{args.feature}/{lk.REQUEST_FILE}"
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


# ------------------------------------------------------------------ change-request decide


class ConsoleUnavailable(Exception):
    """There is no interactive console to ask a person on, or nobody answered in time."""


CONSOLE_TIMEOUT = 300.0


def _console_interactive():
    """(ok, why): an interactive console is attached to standard input. On Windows `GetConsoleMode` must succeed on the stdin
    handle (NUL, a pipe or a file fail it); elsewhere standard input is a terminal and /dev/tty opens."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.windll.kernel32
            kernel.GetStdHandle.restype = wintypes.HANDLE
            handle = kernel.GetStdHandle(-10)
            mode = wintypes.DWORD()
            if handle in (None, 0, ctypes.c_void_p(-1).value) or not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                return False, "standard input is not a console (it is NUL, a pipe or a file)"
        except (OSError, AttributeError) as exc:
            return False, f"the console cannot be queried ({exc})"
        return True, ""
    try:
        if not os.isatty(0):
            return False, "standard input is not a terminal"
        os.close(os.open("/dev/tty", os.O_RDWR))
    except OSError as exc:
        return False, f"/dev/tty cannot be opened ({exc})"
    return True, ""


def _ask_on_console(prompt):
    names = ("CONIN$", "CONOUT$") if os.name == "nt" else ("/dev/tty", "/dev/tty")
    with open(names[1], "w", encoding="utf-8") as out, open(names[0], "r", encoding="utf-8") as source:
        out.write(prompt)
        out.flush()
        return source.readline().strip()


def read_console(prompt, timeout=None):
    """Ask a person on the console device itself, never on standard input, which an agent can feed. Refuses (ConsoleUnavailable)
    unless an interactive console is attached, and gives up after `timeout` seconds (default 300) with nothing decided. A
    process attached to the same console can type into it: that is waived here and closed by denying agents the command."""
    ok, why = _console_interactive()
    if not ok:
        raise ConsoleUnavailable(why)
    box = {}

    def work():
        try:
            box["answer"] = _ask_on_console(prompt)
        except BaseException as exc:   # noqa: BLE001 (reported to the caller)
            box["error"] = exc

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(CONSOLE_TIMEOUT if timeout is None else timeout)
    if thread.is_alive():
        raise ConsoleUnavailable(f"timed out waiting for an answer on the console; nothing was decided")
    if "error" in box:
        raise ConsoleUnavailable(f"no console device to ask on ({box['error']})") from box["error"]
    return box["answer"]


def account_name():
    """The account the process runs as, from the operating system, never from an environment variable a caller can set."""
    try:
        if os.name == "nt":
            import ctypes
            size = ctypes.c_ulong(256)
            buf = ctypes.create_unicode_buffer(256)
            if ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(size)):
                return buf.value
        else:
            import pwd
            return pwd.getpwuid(os.getuid()).pw_name
    except Exception:   # noqa: BLE001
        pass
    return "console"


def _find_request(root, request_id):
    """(file, text, row) of a request in the working tree, or None; files that break C33 are not read."""
    for rel in lk.request_paths(root):
        text = (root / rel).read_text(encoding="utf-8-sig")
        rows, errors = lk.parse_requests(text)
        if errors:
            continue
        for row in rows:
            if row["Id"] == request_id:
                return rel, text, row
    return None


def _write_decision(root, rel, text, request_id, status, by):
    """The request file with one decision recorded, validated against C33 before it is written. Returns None or the problem."""
    try:
        new_text = lk.decide_text(text, request_id, status, by)
    except ValueError as exc:
        return f"{rel}: {exc}"
    _rows, errors = lk.parse_requests(new_text)
    if errors:
        return f"{rel} would not satisfy C33: {'; '.join(errors[:3])}"
    lk.atomic_write(root / rel, new_text)
    return None


def _hook_result(message=None):
    out = None
    if message:
        out = {"systemMessage": message, "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": message}}
    return {"contract_version": "1.0", "exit_code": 0, "output": out}


_TYPED = re.compile(r"\s*(approve|reject) ([A-Za-z0-9][A-Za-z0-9._-]{0,63}) ([0-9a-f]{12})(?![0-9a-f])")


def typed_decision(payload):
    """UserPromptSubmit handler `tdd-change-request` (C31): when the prompt the person typed starts with the phrase that
    `change-request show` printed (`approve CR-001 <12 hex>`), record the decision of a request that is still open with that
    row hash. Never blocks and never raises: anything else gives an empty result."""
    try:
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        match = _TYPED.match(prompt) if isinstance(prompt, str) else None
        if match is None:
            return _hook_result()
        decision, request_id, digest = match.groups()
        cwd = payload.get("cwd")
        folder = Path(cwd) if isinstance(cwd, str) and cwd else Path(".")
        if not folder.is_dir():
            return _hook_result()
        try:
            root = hist.toplevel(folder)
        except hist.GitError:
            root = folder.resolve()
        found = _find_request(root, request_id)
        if found is None:
            return _hook_result(f"No request {request_id} was found; nothing was decided.")
        rel, text, row = found
        if row["Status"] != "open":
            return _hook_result(f"Request {request_id} is already {row['Status']}; a decision is final.")
        if lk.row_hash(row)[:12] != digest:
            return _hook_result(f"The hash does not match request {request_id} as it is now (it changed, or the hash is wrong); "
                                f"run 'tdd change-request show {request_id}' and type the phrase it prints.")
        status = "approved" if decision == "approve" else "rejected"
        problem = _write_decision(root, rel, text, request_id, status, "typed prompt")
        if problem:
            return _hook_result(f"Request {request_id} was not decided: {problem}")
        return _hook_result(f"Request {request_id} is {status} (decided by typed prompt) in {rel}.")
    except Exception:   # noqa: BLE001 (a hook never breaks the prompt)
        return _hook_result()


HOOKS = {"tdd-change-request": typed_decision}


def _change_request_show(args):
    as_json, items = getattr(args, "json", False), []
    try:
        hist.ensure_supported()
        try:
            root = hist.toplevel(getattr(args, "repo", None) or ".")
        except hist.GitError:
            root = Path(getattr(args, "repo", None) or ".").resolve()
    except hist.GitError as exc:
        return _fail("change-request show", items, as_json, str(exc))
    found = _find_request(root, args.request_id)
    if found is None:
        items.append(item("REFUSED", f"no request {args.request_id} in specs/**/{lk.REQUEST_FILE}"))
        return emit(AREA, "change-request show", items, "tdd change-request show: refused", as_json)
    rel, _text, row = found
    items.append(item("OK", f"request {args.request_id} ({row['Status']}) for {row['Test path']} in {rel}: {row['Reason']}; "
                            f"proposed: {row['Proposed change']}", rel))
    if row["Status"] != "open":
        items.append(item("REFUSED", f"request {args.request_id} is already {row['Status']}; a decision is final"))
        return emit(AREA, "change-request show", items, "tdd change-request show: nothing to decide", as_json)
    digest = lk.row_hash(row)[:12]
    items.append(item("OK", f"to approve, type this as your prompt: approve {args.request_id} {digest}"))
    items.append(item("OK", f"to reject, type this as your prompt: reject {args.request_id} {digest}"))
    return emit(AREA, "change-request show", items, "tdd change-request show: done", as_json)


def _change_request_decide(args):
    as_json, items = getattr(args, "json", False), []
    try:
        hist.ensure_supported()
        try:
            root = hist.toplevel(getattr(args, "repo", None) or ".")
        except hist.GitError:
            root = Path(getattr(args, "repo", None) or ".").resolve()
    except hist.GitError as exc:
        return _fail("change-request decide", items, as_json, str(exc))

    def refused(message):
        items.append(item("REFUSED", message))
        return emit(AREA, "change-request decide", items, "tdd change-request decide: refused, nothing written", as_json)

    status = "approved" if args.decision == "approve" else "rejected"
    found = _find_request(root, args.request_id)
    if found is None:
        return refused(f"no request {args.request_id} in specs/**/{lk.REQUEST_FILE}")
    rel, text, row = found
    if row["Status"] != "open":
        return refused(f"request {args.request_id} is already {row['Status']}; a decision is final")
    phrase = f"{args.decision} {args.request_id}"
    if not args.apply:
        items.append(item("CHANGED", f"would set request {args.request_id} to {status} in {rel} after the person types '{phrase}' "
                                     f"on the console", rel))
        return emit(AREA, "change-request decide", items, "tdd change-request decide: dry run, nothing asked or written (use --apply)",
                    as_json)
    try:
        typed = read_console(f"{row['Test path']}: {row['Reason']}\nType '{phrase}' to {args.decision} request {args.request_id}: ")
    except ConsoleUnavailable as exc:
        return refused(f"{exc}: a request is decided by a person at a console, never by a script or an agent")
    if typed != phrase:
        return refused(f"the console answer is not '{phrase}': the request stays open")
    by = account_name()
    problem = _write_decision(root, rel, text, args.request_id, status, by)
    if problem:
        return _fail("change-request decide", items, as_json, problem)
    items.append(item("CHANGED", f"request {args.request_id} is {status} (decided by {by}) in {rel}", rel))
    return emit(AREA, "change-request decide", items, "tdd change-request decide: done", as_json)


# ------------------------------------------------------------------ commit


def _is_test_support(rel):
    return tm.is_test_support(rel)


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
        hist.ensure_supported()
        root = hist.toplevel(getattr(args, "repo", None) or ".")
        rng = args.range or "HEAD"
        base = hist.range_base(root, rng)   # also refuses a range that git would read as an option
        settings, _ = _settings(args, root, base)
        items = hist.Checker(root, settings, rng, base).run(replay=args.replay)
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
    n.add_argument("--feature", required=True, metavar="NAME", help="the feature the request belongs to: "
                                                                     "specs/<NAME>/test-change-requests.md")
    n.add_argument("--apply", action="store_true", help="write the file (default: dry run)")
    n.set_defaults(func=_change_request_new)
    d = crs.add_parser("decide", help="Approve or reject an open request: the person confirms on the console, never an agent.")
    d.add_argument("--repo", metavar="DIR", default=None, help="the repository (default: the current directory)")
    d.add_argument("request_id", metavar="CR-ID", help="the request to decide")
    d.add_argument("decision", choices=("approve", "reject"), help="the decision; the person types '<decision> <CR-ID>' on the console")
    d.add_argument("--apply", action="store_true", help="ask on the console and write the decision (default: dry run)")
    d.set_defaults(func=_change_request_decide)
    sh = crs.add_parser("show", help="Print the phrase that approves or rejects an open request when typed as a prompt.")
    sh.add_argument("--repo", metavar="DIR", default=None, help="the repository (default: the current directory)")
    sh.add_argument("request_id", metavar="CR-ID", help="the request to show")
    sh.set_defaults(func=_change_request_show)

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
