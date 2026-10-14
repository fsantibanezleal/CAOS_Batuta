"""Git access and the history rules of the tdd area.

Every git call of the area goes through `run` here: explicit arguments, no shell, and an honest `GitError` carrying
git's own message. `Checker` walks a range oldest first and proves, from the history alone, that

- every `[green] T-NNN` has an earlier `[red] T-NNN`;
- no commit touches a path locked at its parent;
- the lock file is append-only, every entry validates against C07 and a superseding entry names an approved request;
- at the end of the range every locked file still hashes to its newest entry;
- no commit adds a marker that weakens a test (skip, expected failure, only, todo) or lowers a test file's assertions.

The only exemption is a commit whose message carries `Test-Change-Approved: <id>` (C32) naming a C33 request that is
`approved`, has a decider and is for the changed path, while the request's spec changed in the same range. With
`replay=True` each `[red]` commit is checked out in a temporary worktree (created and removed here) and the tests it
adds must fail there.
"""
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from batuta_lib import contract as core
from batuta_lib import tdd_lock
from batuta_lib import test_markers as tm
from batuta_lib.output import item

MIN_GIT = (2, 30)
DEFAULT_TEST_COMMAND = 'python -m unittest discover -s tests -p "test_*.py"'
DEFAULT_REPLAY_TIMEOUT = 300.0
OVERRIDE_TRAILER = core.RESERVED_TRAILER
TAGGED = re.compile(r"\[(red|green|refactor)\]", re.ASCII)
SUBJECT = re.compile(r"\[(red|green|refactor)\] (T-\d{3}) \S", re.ASCII)


class GitError(RuntimeError):
    """A git call failed; the message carries git's own words."""


# ------------------------------------------------------------------ git calls


def _git_exe():
    exe = shutil.which("git")
    if exe is None:
        raise GitError("git is not on PATH; install git 2.30 or newer")
    return exe


def _exec(cwd, args, input=None, timeout=None):
    return subprocess.run([_git_exe(), *args], cwd=str(cwd), input=input, capture_output=True, timeout=timeout, check=False)


def run(cwd, *args, input=None, ok=(0,)):
    proc = _exec(cwd, args, input=input)
    if proc.returncode not in ok:
        raise GitError(f"git {' '.join(args[:2])} failed (exit {proc.returncode}): "
                       f"{proc.stderr.decode('utf-8', 'replace').strip() or proc.stdout.decode('utf-8', 'replace').strip()}")
    return proc


def git_version():
    out = run(".", "--version").stdout.decode("utf-8", "replace")
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    if not m:
        raise GitError(f"cannot read the git version from {out.strip()!r}")
    return tuple(int(g or 0) for g in m.groups())


def ensure_supported():
    version = git_version()
    if version[:2] < MIN_GIT:
        raise GitError(f"git {'.'.join(map(str, version))} is older than {MIN_GIT[0]}.{MIN_GIT[1]}; "
                       f"the worktree and rename detection this check relies on need git 2.30 or newer")
    return version


def toplevel(path):
    return Path(run(path, "rev-parse", "--show-toplevel").stdout.decode("utf-8", "replace").strip())


def head(cwd):
    proc = run(cwd, "rev-parse", "--verify", "-q", "HEAD", ok=(0, 1))
    return proc.stdout.decode().strip() or None if proc.returncode == 0 else None


def resolve(cwd, rev):
    proc = run(cwd, "rev-parse", "--verify", "-q", "--end-of-options", rev + "^{commit}", ok=(0, 1))
    return proc.stdout.decode().strip() if proc.returncode == 0 else None


def split_range(rng):
    """(start, end) of a git range: `A..B` or `A...B` gives (A, B), a single revision gives ('', rev). A part that starts with a
    dash would be read by git as an option, so it is refused."""
    parts = re.split(r"\.\.\.?", rng)
    if len(parts) > 2:
        raise GitError(f"the range {rng!r} has more than one '..'")
    start, end = (parts[0], parts[-1] or "HEAD") if len(parts) == 2 else ("", parts[0] or "HEAD")
    for part in (start, end):
        if part.startswith("-"):
            raise GitError(f"the range {rng!r} names {part!r}, which starts with a dash and would be read by git as an option")
    return start, end


def range_base(cwd, rng):
    """The commit whose tree holds the settings of a check: the start of `A..B`, or the first root commit of the history of the
    end revision. None when the repository has no commit."""
    start, end = split_range(rng)
    if start:
        sha = resolve(cwd, start)
        if sha is None:
            raise GitError(f"unknown revision {start!r} in the range {rng!r}")
        return sha
    if resolve(cwd, end) is None:
        return None
    roots = run(cwd, "rev-list", "--max-parents=0", "--end-of-options", end).stdout.decode().split()
    return roots[0] if roots else None


def show(cwd, rev, path):
    """The bytes of `path` at `rev`, or None when the revision has no such file."""
    proc = _exec(cwd, ["cat-file", "blob", f"{rev}:{path}"])
    if proc.returncode == 0:
        return proc.stdout
    probe = _exec(cwd, ["rev-parse", "--verify", "-q", f"{rev}:{path}"])
    if probe.returncode == 1:
        return None
    raise GitError(f"git cat-file failed for {rev[:12]}:{path}: {proc.stderr.decode('utf-8', 'replace').strip()}")


@dataclass
class Change:
    status: str            # A, M, D, R or T
    path: str              # the path after the commit (the old path for a deletion)
    old: str = None        # the path before, for a rename


@dataclass
class Commit:
    sha: str
    parents: list
    message: str
    changes: list = field(default_factory=list)   # against the first parent, with rename detection; empty for a merge


def _parse_changes(tokens):
    changes, i = [], 0
    while i < len(tokens):
        status = tokens[i][0]
        if status in "RC":
            changes.append(Change("R" if status == "R" else "A", tokens[i + 2], tokens[i + 1] if status == "R" else None))
            i += 3
        else:
            changes.append(Change(status, tokens[i + 1]))
            i += 2
    return changes


def log(cwd, rng):
    """Commits of `rng` oldest first (topological order) with parents, full message and changes, in one git call."""
    split_range(rng)
    out = run(cwd, "log", "--reverse", "--topo-order", "-M", "--root", "--name-status", "-z",
              "--format=%x1e%H%x1f%P%x1f%B%x1f", "--end-of-options", rng, "--").stdout.decode("utf-8", "replace")
    commits = []
    for record in out.split("\x1e"):
        if not record.strip("\0\n"):
            continue
        sha, parents, message, rest = record.split("\x1f", 3)
        commits.append(Commit(sha, parents.split(), message, _parse_changes([t for t in rest.lstrip("\0\n").split("\0") if t != ""])))
    return commits


def subjects(cwd, rev):
    split_range(rev)
    out = run(cwd, "log", "--format=%s", "--end-of-options", rev, "--").stdout.decode("utf-8", "replace")
    return out.splitlines()


def diff_between(cwd, old, new):
    """The changes from one commit to another, with rename detection."""
    out = run(cwd, "diff-tree", "-r", "-M", "--name-status", "-z", "--no-commit-id", old, new).stdout.decode("utf-8", "replace")
    return _parse_changes([t for t in out.split("\0") if t != ""])


class BatchReader:
    """One long-lived `git cat-file --batch` that answers many `show` questions (a process start costs far more than a read)."""

    def __init__(self, cwd):
        self.proc = subprocess.Popen([_git_exe(), "cat-file", "--batch"], cwd=str(cwd), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def show(self, rev, path):
        """The bytes of `path` at `rev`, or None when the revision has no such file."""
        try:
            self.proc.stdin.write(f"{rev}:{path}\n".encode("utf-8"))
            self.proc.stdin.flush()
            header = self.proc.stdout.readline()
        except OSError as exc:
            raise GitError(f"git cat-file --batch failed: {exc}") from exc
        parts = header.split()
        if not parts:
            raise GitError("git cat-file --batch ended unexpectedly")
        if len(parts) == 2 and parts[1] in (b"missing", b"ambiguous"):
            return None
        data = self.proc.stdout.read(int(parts[2]))
        self.proc.stdout.read(1)
        return data

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


def tree_paths(cwd, rev, prefix):
    out = run(cwd, "ls-tree", "-r", "--name-only", "-z", rev, "--", prefix).stdout.decode("utf-8", "replace")
    return [p for p in out.split("\0") if p]


def staged_paths(cwd):
    out = run(cwd, "diff", "--cached", "--name-only", "-z").stdout.decode("utf-8", "replace")
    return {p for p in out.split("\0") if p}


def stage(cwd, paths):
    run(cwd, "add", "-A", "--", *paths)


def unstage(cwd, paths):
    run(cwd, "reset", "-q", "--", *paths, ok=(0, 1, 128))


def commit_with_file(cwd, message_file):
    run(cwd, "commit", "-q", "-F", str(message_file))
    return head(cwd)


def worktree_add(cwd, path, rev):
    run(cwd, "worktree", "add", "--detach", "--force", "-q", str(path), rev)


def worktree_remove(cwd, path):
    run(cwd, "worktree", "remove", "--force", str(path), ok=(0, 128))


def worktree_prune(cwd):
    run(cwd, "worktree", "prune", ok=(0, 128))


def worktree_list(cwd):
    out = run(cwd, "worktree", "list", "--porcelain").stdout.decode("utf-8", "replace")
    return [line[len("worktree "):] for line in out.splitlines() if line.startswith("worktree ")]


# ------------------------------------------------------------------ settings and the replay command


@dataclass
class Settings:
    lock_path: str = tdd_lock.DEFAULT_LOCK
    test_command: str = DEFAULT_TEST_COMMAND
    replay_timeout: float = DEFAULT_REPLAY_TIMEOUT
    markers: dict = field(default_factory=dict)
    temp_root: Path = None


def _executable(token):
    return sys.executable if token in ("python", "python3") else token


def replay_command(command, paths, tree):
    """(argv, passes_paths) of the one run of a replay, from the checkout root `tree`. The configured command runs as
    written (the token `{tests}` stands for the test files of the red commit); the default command is the project's own
    unittest discovery, with the top-level folder at the checkout root (`-t .`) when `tests` is a package, so that
    package-relative imports resolve as they do in the project. `passes_paths` says the command was given the files; when
    it was not, the whole suite runs and only a failure of the red's own files counts."""
    tokens = shlex.split(command)
    if not tokens:
        raise ValueError("the test command is empty")
    if command.strip() == DEFAULT_TEST_COMMAND and (Path(tree) / "tests" / "__init__.py").is_file():
        tokens += ["-t", "."]
    passes = any("{tests}" in t for t in tokens)
    argv = []
    for t in tokens:
        if t == "{tests}":
            argv.extend(paths)
        else:
            argv.append(t.replace("{tests}", " ".join(paths)))
    argv[0] = _executable(argv[0])
    return argv, passes


_NO_TESTS = re.compile(r"no tests ran|collected 0 items|NO TESTS RAN", re.IGNORECASE)
_FAILED_LINE = re.compile(r"^(?:FAIL|ERROR|FAILED)\b.*$", re.MULTILINE)


def judge_red(rc, output, paths, passes_paths):
    """[(path, ok, reason)] for the test files of a red commit, from one run's exit code and output. A red counts only when
    a test of its own failed or errored: exit 0, exit 5, `Ran 0 tests` and a failure of somebody else's test do not."""
    ran = re.search(r"^Ran (\d+) tests?\b", output, re.MULTILINE)
    if rc == 0:
        return [(p, False, f"tests pass at the red commit (exit 0); a red test must fail before the code exists") for p in paths]
    if rc == 5 or (ran and int(ran.group(1)) == 0) or _NO_TESTS.search(output):
        return [(p, False, f"no test ran (exit {rc}); a red reports a failing test of its own, not an empty run") for p in paths]
    failing = "\n".join(_FAILED_LINE.findall(output))
    out = []
    for p in paths:
        stem = PurePosixPath(p).stem
        if passes_paths or re.search(r"(?<![\w])" + re.escape(stem) + r"(?![\w])", failing):
            out.append((p, True, f"fails at the red commit (exit {rc})"))
        else:
            out.append((p, False, f"tests pass at the red commit: the run failed (exit {rc}) but no failure or error names {stem}"))
    return out


def _force_remove(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


# ------------------------------------------------------------------ the history check


CONFIG_PATH = ".batuta/batuta.json"


def tdd_signature(data):
    """The part of a project configuration that steers a check (the tdd block and roots.temp), or None when unreadable."""
    if data is None:
        return None
    try:
        doc = core.loads_strict(data.decode("utf-8-sig", "replace") if isinstance(data, bytes) else data)
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    roots = doc.get("roots") if isinstance(doc.get("roots"), dict) else {}
    return json.dumps({"tdd": doc.get("tdd"), "temp": roots.get("temp")}, sort_keys=True)


class Checker:
    def __init__(self, repo, settings, rng="HEAD", base_sha=None):
        self.repo = Path(repo)
        self.s = settings
        self.rng = rng
        self.base_sha = base_sha
        self.items = []
        self._locks = {}
        self._requests = {}
        self._c32 = tdd_lock.schema("C32")
        self.changes_seen = []       # (sha, changes) of every commit walked
        self.pending_specs = []      # (sha, request file, request id): the spec must change in the range
        self.failed_locks = set()
        self.blobs = None

    # -- output
    def fail(self, message, path=None):
        self.items.append(item("FAIL", message, path))

    def warn(self, message, path=None):
        self.items.append(item("WARN", message, path))

    def ok(self, message, path=None):
        self.items.append(item("OK", message, path))

    # -- lock and requests at a revision
    def lock_at(self, sha):
        if sha is None:
            return None, None
        if sha not in self._locks:
            self._locks[sha] = tdd_lock.parse_lock(self.blobs.show(sha, self.s.lock_path))
        return self._locks[sha]

    def requests_at(self, sha):
        if sha is None:
            return {}, {}
        if sha not in self._requests:
            texts = {}
            for path in tree_paths(self.repo, sha, "specs"):
                if path.rsplit("/", 1)[-1] == tdd_lock.REQUEST_FILE:
                    data = self.blobs.show(sha, path)
                    if data is not None:
                        texts[path] = data.decode("utf-8-sig", "replace")
            self._requests[sha] = tdd_lock.index_requests(texts)
        return self._requests[sha]

    # -- the override
    def exemption(self, commit, change):
        """(True, '') when the commit's Test-Change-Approved trailer authorises touching this change, else (False, reason)."""
        _subject, _rest, _body, trailers = core.parse_commit_message(commit.message)
        ids = [v for k, v in trailers if k == OVERRIDE_TRAILER]
        if not ids:
            return False, f"no {OVERRIDE_TRAILER} trailer"
        problems = core.check_commit_message(commit.message, self._c32)
        if problems:
            return False, f"the {OVERRIDE_TRAILER} trailer is in a message that breaks C32 ({'; '.join(problems)})"
        # the request must have been decided in an earlier commit: the tree of the parent, never the tree that uses it
        rows_by_id, problem_files = self.requests_at(commit.parents[0] if commit.parents else None)
        paths = {p for p in (change.path, change.old) if p}
        row, request_file, why = tdd_lock.lookup(rows_by_id, problem_files, ids[0], paths)
        if why:
            return False, f"{OVERRIDE_TRAILER}: {ids[0]} does not authorise it ({why}; the request is read at the parent commit)"
        self.pending_specs.append((commit.sha, request_file, ids[0]))
        return True, ""

    # -- the walk
    def run(self, replay=False):
        ensure_supported()
        start_rev, end_rev = split_range(self.rng)
        end_sha = resolve(self.repo, end_rev)
        if end_sha is None:
            if end_rev == "HEAD":
                self.warn("the repository has no commits: nothing to verify")
                return self.items
            raise GitError(f"unknown revision {end_rev!r} in the range {self.rng!r}")
        commits = log(self.repo, self.rng)
        if not commits:
            self.fail(f"the range {self.rng!r} has no commits although {end_rev} has history: nothing was checked")
            return self.items
        seen_red = set()
        if start_rev:
            for subject in subjects(self.repo, start_rev):
                m = SUBJECT.match(subject)
                if m and m.group(1) == "red":
                    seen_red.add(m.group(2))
        reds, approved_removed, approved_renames = [], set(), []
        self.blobs = BatchReader(self.repo)
        try:
            for commit in commits:
                self._commit(commit, seen_red, reds, approved_removed, approved_renames)
            self._at_end(end_sha, bool(seen_red or reds), approved_removed, approved_renames)
        finally:
            self.blobs.close()
        self._specs_changed()
        if replay:
            self._replay(reds)
        if not any(i["tag"] in ("FAIL", "REFUSED") for i in self.items):
            self.ok(f"{len(commits)} commit(s) checked against the red and green rules")
        return self.items

    def _commit(self, c, seen_red, reds, approved_removed, approved_renames):
        short = c.sha[:7]
        merge = len(c.parents) > 1
        parent = c.parents[0] if c.parents else None
        subject = c.message.lstrip().split("\n", 1)[0]
        kind = task = None
        if TAGGED.match(subject):
            problems = core.check_commit_message(c.message, self._c32)
            if problems:
                self.fail(f"commit {short} breaks C32: {'; '.join(problems)}")
            m = SUBJECT.match(subject)
            if m:
                kind, task = m.group(1), m.group(2)
        label = f"[{kind}] {task}" if kind else "commit"
        # a merge is judged on what it changes against every parent: a path that differs from all of them is the merge's own edit
        changes = self._merge_changes(c) if merge else c.changes
        self.changes_seen.append((c.sha, changes))
        if kind == "green" and task not in seen_red:
            self.fail(f"[green] {task} at {short} has no earlier [red] commit for {task}")
        self._settings_rule(c, parent, changes)

        lock_path = self.s.lock_path
        if merge:
            lock_ps = [self.lock_at(p) for p in c.parents]
            entries_p = lock_ps[0][0] or []
            entries_c = self._merge_lock_rules(c, lock_ps)
            locked_paths = {e["path"] for lp in lock_ps for e in (lp[0] or [])}
        else:
            lock_p = self.lock_at(parent)
            if any(lock_path in (ch.path, ch.old) for ch in changes):
                lock_c = self.lock_at(c.sha)
            else:
                lock_c = lock_p
                self._locks[c.sha] = lock_p
            entries_p = lock_p[0] or []
            entries_c = self._lock_rules(c, lock_p, lock_c, entries_p, kind)
            locked_paths = {e["path"] for e in entries_p}
            self._decision_rules(c, parent, changes)

        for ch in changes:
            involved = {p for p in (ch.path, ch.old) if p}
            hit = sorted(involved & locked_paths)
            if not hit:
                continue
            if ch.status == "M" and parent is not None and self._same_content(c, parent, ch.path):
                continue   # only the line endings differ: the normalized hash is the same, so the test is the same
            ok, why = self.exemption(c, ch)
            if ok:
                if ch.status == "D":
                    approved_removed.add(ch.path)
                elif ch.status == "R":
                    approved_removed.add(ch.old)
                    approved_renames.append((ch.old, ch.path))
            else:
                how = {"D": " (deleted)", "R": f" (renamed to {ch.path})"}.get(ch.status, "")
                self.fail(f"{label} at {short} touches locked test {hit[0]}{how}: {why}", hit[0])

        ever_locked = locked_paths | {e["path"] for e in entries_c}
        for ch in changes:
            self._test_file_rules(c, parent, ch, ever_locked, label)

        if kind == "red":
            self._red_rules(c, task, changes, entries_c)
            seen_red.add(task)
            reds.append((c, task, changes))

    def _same_content(self, c, parent, path):
        old, new = self.blobs.show(parent, path), self.blobs.show(c.sha, path)
        return old is not None and new is not None and tm.normalized_sha256(old) == tm.normalized_sha256(new)

    def _merge_changes(self, c):
        """The changes a merge commit makes of its own: paths that differ from every parent (the first parent's view)."""
        diffs = [diff_between(self.repo, p, c.sha) for p in c.parents]
        common = set.intersection(*({ch.path for ch in d} for d in diffs))
        return [ch for ch in diffs[0] if ch.path in common]

    def _settings_rule(self, c, parent, changes):
        """A commit that changes the tdd settings of the project configuration is reported: the check keeps using the
        settings of the base commit, so a commit in the range cannot steer its own check."""
        if not any(CONFIG_PATH in (ch.path, ch.old) for ch in changes):
            return
        before = tdd_signature(self.blobs.show(parent, CONFIG_PATH)) if parent else None
        after = tdd_signature(self.blobs.show(c.sha, CONFIG_PATH))
        if before != after:
            base = f"the base commit {self.base_sha[:7]}" if self.base_sha else "the base commit of the range"
            self.warn(f"commit {c.sha[:7]} changes the tdd settings in {CONFIG_PATH}; the check keeps the settings of {base} "
                      f"(CI may pass --config from outside the repository to set them)", CONFIG_PATH)

    def _red_rules(self, c, task, changes, entries_c):
        """A [red] commit holds failing tests and the lock: at least one test file, each locked with its content here, and
        nothing else but test support files."""
        short = c.sha[:7]
        lock_path = self.s.lock_path
        tests = [ch for ch in changes if ch.status in ("A", "M", "R") and tm.is_test_path(ch.path)]
        if not tests:
            self.fail(f"[red] {task} at {short} adds or changes no test file: a red commit holds the failing tests")
        live = tdd_lock.live_entries(entries_c)
        for ch in tests:
            data = self.blobs.show(c.sha, ch.path)
            entry = live.get(ch.path)
            if data is None or entry is None or entry["sha256"] != tm.normalized_sha256(data):
                self.fail(f"[red] {task} at {short}: {ch.path} is not locked with its content at this commit; lock the tests "
                          f"(tdd lock) in the red commit", ch.path)
        for ch in changes:
            if ch.status != "D" and ch.path != lock_path and not tm.is_test_support(ch.path):
                self.fail(f"[red] {task} at {short} holds {ch.path}: a red commit holds tests and the lock only", ch.path)

    def _decision_rules(self, c, parent, changes):
        """A request is decided (approved or rejected) in a commit of its own, so the commit that uses an approval is never the
        commit that gave it."""
        if not any(p.rsplit("/", 1)[-1] == tdd_lock.REQUEST_FILE for ch in changes for p in (ch.path, ch.old) if p):
            return
        rows_c, _ = self.requests_at(c.sha)
        rows_p, _ = self.requests_at(parent)
        decided = []
        for rid, found in rows_c.items():
            status = found[0][0].get("Status")
            before = rows_p.get(rid)
            if status in ("approved", "rejected") and status != (before[0][0].get("Status") if before else None):
                decided.append(rid)
        if not decided:
            return
        others = sorted({p for ch in changes for p in (ch.path, ch.old) if p and p.rsplit("/", 1)[-1] != tdd_lock.REQUEST_FILE})
        if others:
            self.fail(f"commit {c.sha[:7]} decides request {', '.join(decided)} together with other paths "
                      f"({', '.join(others[:5])}): a decision is a commit of its own, so whoever uses an approval is not the one "
                      f"who gave it")

    def _merge_lock_rules(self, c, lock_ps):
        """The lock of a merge keeps every entry of every parent, unchanged and in order; returns the merge's entries."""
        short = c.sha[:7]
        path = self.s.lock_path
        entries_c, error = self.lock_at(c.sha)
        first = lock_ps[0][0] or []
        if error:
            self.failed_locks.add(c.sha)
            self.fail(f"lock file {path} at merge {short} is unusable: {error}", path)
            return first
        if entries_c is None:
            if any(lp[0] is not None for lp in lock_ps):
                self.failed_locks.add(c.sha)
                self.fail(f"lock file {path} was deleted in merge {short}: the lock is append-only", path)
            return first
        known = []
        for parent_sha, (entries_p, _err) in zip(c.parents, lock_ps):
            index = 0
            for e in entries_p or []:
                try:
                    index = entries_c.index(e, index) + 1
                except ValueError:
                    self.fail(f"the lock file is append-only: the entry of {e['path']} from parent {parent_sha[:7]} is missing or "
                              f"edited in merge {short}", path)
                    break
                known.append(e)
        rows_by_id, problem_files = self.requests_at(c.parents[0])
        for e in entries_c:
            if e not in known and "supersedes" in e:
                row, _file, why = tdd_lock.lookup(rows_by_id, problem_files, e["change_request"], {e["path"]})
                if why:
                    self.fail(f"the lock entry that supersedes {e['path']} in merge {short} names {e['change_request']}: {why}", path)
        return entries_c

    def _approved_rename_targets(self, c):
        """New paths of locked tests renamed in this commit under an approved request: they take a plain new lock entry."""
        return {ch.path for ch in c.changes if ch.status == "R" and self.exemption(c, ch)[0]}

    def _lock_rules(self, c, lock_p, lock_c, entries_p, kind=None):
        """Append-only and approval checks of the lock file in one commit; returns the entries to carry forward."""
        short = c.sha[:7]
        path = self.s.lock_path
        if lock_c is lock_p:   # the commit did not touch the lock file
            return entries_p
        entries_c, error = lock_c
        if error:
            self.failed_locks.add(c.sha)
            self.fail(f"lock file {path} at {short} is unusable: {error}", path)
            return entries_p
        if entries_c is None:
            if lock_p[0] is not None:
                self.failed_locks.add(c.sha)
                self.fail(f"lock file {path} was deleted in {short}: the lock is append-only", path)
            return entries_p
        n = len(entries_p)
        if entries_c[:n] != entries_p:
            bad = next((i for i in range(n) if i >= len(entries_c) or entries_c[i] != entries_p[i]), n)
            self.fail(f"the lock file is append-only: entry {bad} ({entries_p[bad]['path']}) was edited or removed in {short}", path)
            return entries_p
        # an approval counts when it was decided in an earlier commit: read the requests at the parent
        rows_by_id, problem_files = self.requests_at(c.parents[0] if c.parents else None)
        for e in entries_c[n:]:
            if "supersedes" in e:
                row, _file, why = tdd_lock.lookup(rows_by_id, problem_files, e["change_request"], {e["path"]})
                if why:
                    self.fail(f"the lock entry that supersedes {e['path']} in {short} names {e['change_request']}: {why}", path)
            elif kind in ("green", "refactor") and e["path"] not in self._approved_rename_targets(c):
                self.fail(f"a [{kind}] commit never adds entries to the lock file {path}: {e['path']} was locked in {short} without "
                          f"a red commit of its own", path)
        return entries_c

    def _test_file_rules(self, c, parent, ch, ever_locked, label):
        short = c.sha[:7]
        new_path = ch.path
        old_path = ch.old or ch.path
        test_new = ch.status != "D" and (tm.is_test_path(new_path) or new_path in ever_locked)
        test_old = ch.status != "A" and (tm.is_test_path(old_path) or old_path in ever_locked)
        support_new = ch.status != "D" and tm.is_marker_file(new_path)
        support_old = ch.status != "A" and tm.is_marker_file(old_path)
        if not (test_new or test_old or support_new or support_old):
            return
        before = None if ch.status == "A" or parent is None else self.blobs.show(parent, old_path)
        after = None if ch.status == "D" else self.blobs.show(c.sha, new_path)
        before_text = None if before is None else before.decode("utf-8-sig", "replace")
        after_text = None if after is None else after.decode("utf-8-sig", "replace")
        # the assertions of a file count where the file is a test: renaming one to a name no runner discovers drops them
        try:
            count_before = (tm.assertion_count(old_path, before_text) or 0) if (test_old and before_text is not None) else 0
        except tm.UnparsableTestFile:
            count_before = 0
        try:
            count_after = (tm.assertion_count(new_path, after_text) or 0) if (test_new and after_text is not None) else 0
            markers_after = (tm.weakening_markers(new_path, after_text, self.s.markers)
                             if (after_text is not None and (test_new or support_new)) else {})
        except tm.UnparsableTestFile as exc:
            self.fail(f"{label} at {short}: cannot parse {new_path} to count its assertions and markers ({exc})", new_path)
            return
        try:
            markers_before = (tm.weakening_markers(old_path, before_text, self.s.markers)
                              if (before_text is not None and (test_old or support_old)) else {})
        except tm.UnparsableTestFile:
            markers_before = {}
        problems = []
        if count_after < count_before:
            problems.append(f"assertion count dropped in {new_path}: from {count_before} to {count_after}")
        for name, n in sorted(markers_after.items()):
            if n > markers_before.get(name, 0):
                problems.append(f"weakening marker '{name}' added in {new_path}")
        if problems:
            ok, why = self.exemption(c, ch)
            if not ok:
                for problem in problems:
                    self.fail(f"{label} at {short}: {problem} ({why})", new_path)

    def _at_end(self, end_sha, has_red, approved_removed, approved_renames):
        short = end_sha[:7]
        if not has_red:
            self.warn("no [red] commit in the range: nothing to verify about the red and green order")
        entries, error = self.lock_at(end_sha)
        path = self.s.lock_path
        if error:
            if end_sha not in self.failed_locks:
                self.fail(f"lock file {path} at {short} is unusable: {error}", path)
            return
        if entries is None:
            self.warn(f"nothing is locked: no lock file {path} at {short}; markers and assertions were still checked")
            return
        live = tdd_lock.live_entries(entries)
        matching = 0
        for tpath, entry in sorted(live.items()):
            data = self.blobs.show(end_sha, tpath)
            if data is None:
                if tpath not in approved_removed:
                    self.fail(f"locked test {tpath} is deleted at {short}", tpath)
                continue
            digest = tm.normalized_sha256(data)
            if digest != entry["sha256"]:
                self.fail(f"{tpath} does not match the lock at {short}: it hashes to {digest[:12]} and the newest entry "
                          f"says {entry['sha256'][:12]}", tpath)
            else:
                matching += 1
        for old, new in approved_renames:
            if new not in live:
                self.fail(f"{new} was renamed from locked {old} under an approved change request but is not locked", new)
        if matching:
            self.ok(f"{matching} of {len(live)} locked test file(s) match the lock at {short}")

    def _specs_changed(self):
        done = set()
        for sha, request_file, rid in self.pending_specs:
            if (sha, rid) in done:
                continue
            done.add((sha, rid))
            folder = str(PurePosixPath(request_file).parent)
            prefix = "" if folder == "." else folder + "/"
            changed = any(
                (p.startswith(prefix) and p.rsplit("/", 1)[-1] != tdd_lock.REQUEST_FILE)
                for _s, chs in self.changes_seen for ch in chs for p in (ch.path, ch.old) if p)
            if not changed:
                self.fail(f"commit {sha[:7]} uses {OVERRIDE_TRAILER}: {rid}, but no spec file under {prefix or './'} changed in "
                          f"this range; an approved test change comes with a spec change")

    # -- the replay
    def _replay(self, reds):
        for c, task, changes in reds:
            tests = [ch.path for ch in changes if ch.status in ("A", "M", "R") and tm.is_test_path(ch.path)]
            if tests:   # a red without a test file is already a failure of the static rules
                self._replay_one(c, task, tests)

    def _replay_one(self, c, task, tests):
        short = c.sha[:7]
        temp_root = Path(self.s.temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="tdd-replay-", dir=temp_root))
        tree = work / "tree"
        try:
            worktree_add(self.repo, tree, c.sha)
            try:
                argv, passes = replay_command(self.s.test_command, tests, tree)
            except ValueError as exc:
                self.fail(f"red commit {short} ({task}): {exc}")
                return
            label = ", ".join(tests)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            try:
                proc = subprocess.run(argv, cwd=str(tree), capture_output=True, timeout=self.s.replay_timeout, env=env, check=False)
            except subprocess.TimeoutExpired:
                self.fail(f"red commit {short} ({task}): {label} timed out after {self.s.replay_timeout:g} s; "
                          f"a red test fails fast", label)
                return
            except OSError as exc:
                self.fail(f"red commit {short} ({task}): cannot run the test command {argv[0]!r}: {exc}", label)
                return
            output = proc.stdout.decode("utf-8", "replace") + "\n" + proc.stderr.decode("utf-8", "replace")
            for path, ok, why in judge_red(proc.returncode, output, tests, passes):
                if ok:
                    self.ok(f"red commit {short} ({task}): {path} {why}", path)
                else:
                    self.fail(f"red commit {short} ({task}): {path} {why}", path)
        except GitError as exc:
            self.fail(f"red commit {short} ({task}): cannot replay in a temporary worktree: {exc}")
        finally:
            self._cleanup(tree, work)

    def _cleanup(self, tree, work):
        try:
            worktree_remove(self.repo, tree)
        except GitError:
            pass
        if work.exists():
            if sys.version_info >= (3, 12):
                shutil.rmtree(work, onexc=_force_remove)
            else:
                shutil.rmtree(work, onerror=_force_remove)
        try:
            worktree_prune(self.repo)
        except GitError:
            pass
        if work.exists():
            self.warn(f"the temporary worktree folder {work.as_posix()} could not be removed")
