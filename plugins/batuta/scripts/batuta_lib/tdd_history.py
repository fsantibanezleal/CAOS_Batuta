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
import ast
import contextlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from xml.etree import ElementTree
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


def static_test_ids(path, text):
    """[(class or None, name)] of the tests a Python file defines: `test*` methods of its classes and `test*` functions."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    ids = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            ids += [(node.name, sub.name) for sub in node.body
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test")]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            ids.append((None, node.name))
    return ids


def compare_listing(path, base, listing):
    """Problems of the recorded run of the tests against the tests a locked file defined: one for each test that did not run at
    all, one for each that only skipped and one for each that only reported an expected failure. `listing` is [{"id", "outcome"}]
    (or {"id", "skipped"}) with unittest ids (`pkg.module.Class.test`) or pytest ids (`path::Class::test`, `module.Class.test`);
    a parametrized id (`test_x[1]`) is compared by the part before `[`: one case that ran is enough."""
    stem = PurePosixPath(path).stem
    problems = []
    for cls, name in base:
        hits = []
        for entry in listing:
            ident = re.sub(r"\[.*\]$", "", entry["id"])
            if "::" in ident:
                parts = ident.split("::")
                file_ok = PurePosixPath(parts[0]).stem == stem
                names = parts[1:]
                match = file_ok and names[-1] == name and (cls is None or (len(names) >= 2 and names[-2] == cls))
            else:
                parts = ident.split(".")
                match = parts[-1] == name and stem in parts and (cls is None or (len(parts) >= 2 and parts[-2] == cls))
            if match:
                hits.append(entry)
        label = f"{path}::{cls + '.' if cls else ''}{name}"
        states = [h.get("outcome") or ("skipped" if h.get("skipped") else "passed") for h in hits]
        if not hits:
            problems.append(f"locked test {label} disappears from the runtime listing")
        elif not any(s in ("passed", "failed", "error", "unexpected success") for s in states):
            if "expected failure" in states:
                problems.append(f"locked test {label} is reported as an expected failure at runtime")
            else:
                problems.append(f"locked test {label} is skipped at runtime")
    return problems


def parse_pytest_listing(output):
    """The node ids of `pytest --collect-only -q`."""
    return [{"id": line.strip(), "skipped": False} for line in output.splitlines() if "::" in line and not line.startswith((" ", "="))]


def parse_unittest_listing(output):
    for line in reversed(output.splitlines()):
        if line.startswith("["):
            return json.loads(line)
    raise ValueError("no listing in the output")


def parse_junit(text):
    """[{"id", "outcome"}] from a pytest JUnit XML report: passed, failed, error, skipped or expected failure."""
    root = ElementTree.fromstring(text)
    out = []
    for case in root.iter("testcase"):
        ident = f"{case.get('classname')}.{case.get('name')}" if case.get("classname") else case.get("name", "")
        outcome = "passed"
        for child in case:
            if child.tag == "failure":
                outcome = "failed"
            elif child.tag == "error":
                outcome = "error"
            elif child.tag == "skipped":
                outcome = "expected failure" if child.get("type") == "pytest.xfail" else "skipped"
        out.append({"id": ident, "outcome": outcome})
    return out


# Runs the tests unittest discovery finds with the arguments given and prints, as the last line, a JSON list of the outcome of each
# test id: passed, failed, error, skipped, expected failure or unexpected success. Whatever skipped a test, at run time, shows here.
RUN_SCRIPT = (
    "import io, json, os, sys, unittest\n"
    "start, pattern, top = sys.argv[1:4]\n"
    "class Rec(unittest.TextTestResult):\n"
    "    def __init__(self, *a, **k):\n"
    "        super().__init__(*a, **k)\n"
    "        self.rec = []\n"
    "    def addSuccess(self, t):\n"
    "        super().addSuccess(t); self.rec.append((t.id(), 'passed'))\n"
    "    def addFailure(self, t, e):\n"
    "        super().addFailure(t, e); self.rec.append((t.id(), 'failed'))\n"
    "    def addError(self, t, e):\n"
    "        super().addError(t, e); self.rec.append((t.id(), 'error'))\n"
    "    def addSkip(self, t, r):\n"
    "        super().addSkip(t, r); self.rec.append((t.id(), 'skipped'))\n"
    "    def addExpectedFailure(self, t, e):\n"
    "        super().addExpectedFailure(t, e); self.rec.append((t.id(), 'expected failure'))\n"
    "    def addUnexpectedSuccess(self, t):\n"
    "        super().addUnexpectedSuccess(t); self.rec.append((t.id(), 'unexpected success'))\n"
    "out = []\n"
    "if os.path.isdir(start):\n"
    "    suite = unittest.TestLoader().discover(start, pattern=pattern, top_level_dir=top or None)\n"
    "    res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0, resultclass=Rec).run(suite)\n"
    "    out = [{'id': i, 'outcome': o} for i, o in res.rec]\n"
    "sys.stdout.write('\\n' + json.dumps(out) + '\\n')\n"
)


def listing_command(command, tests_is_package, junit_dir=None):
    """(argv, parser) that RUNS the tests the configured test command would run and reads each test's outcome, or None when the
    command is neither pytest nor unittest discovery. unittest: a result class that records the outcome per test id; pytest: a
    JUnit XML report in `junit_dir`. The default command gets `-t .` when `tests` is a package, as the replay gives it."""
    tokens = shlex.split(command)
    if not tokens:
        return None
    if "pytest" in tokens or Path(tokens[0]).stem.lower() in ("pytest", "py.test"):
        report = Path(junit_dir or ".") / f"tdd-junit-{uuid.uuid4().hex}.xml"

        def parse(_output):
            try:
                return parse_junit(report.read_text(encoding="utf-8"))
            except (OSError, ElementTree.ParseError) as exc:
                raise ValueError(f"no JUnit report ({exc})") from exc
            finally:
                report.unlink(missing_ok=True)

        argv = [t for t in tokens if t != "{tests}"] + ["-q", "--junitxml", str(report)]
        argv[0] = _executable(argv[0])
        return argv, parse
    if "unittest" in tokens and "discover" in tokens:
        def option(flag, default):
            return tokens[tokens.index(flag) + 1] if flag in tokens and tokens.index(flag) + 1 < len(tokens) else default
        top = option("-t", "")
        if command.strip() == DEFAULT_TEST_COMMAND and tests_is_package:
            top = "."
        return [sys.executable, "-c", RUN_SCRIPT, option("-s", "."), option("-p", "test*.py"), top], parse_unittest_listing
    return None


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
        self._base_signature = None
        self.task_commits = {}       # task id -> [(commit, kind)] of its tagged commits, oldest first
        self.commit_pos = {}         # sha -> position in the walk
        self.approved_moves = {}     # path -> (position of the commit, "deleted" or "renamed", new path): under an approved request

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
            if self.base_sha:
                self._base_signature = tdd_signature(self.blobs.show(self.base_sha, CONFIG_PATH))
            for commit in commits:
                self._commit(commit, seen_red, reds, approved_removed, approved_renames)
            self._at_end(end_sha, bool(seen_red or reds), approved_removed, approved_renames)
        finally:
            self.blobs.close()
        self._specs_changed()
        if replay:
            self._replay(reds)
            self._runtime_compare(reds)
        if not any(i["tag"] in ("FAIL", "REFUSED") for i in self.items):
            self.ok(f"{len(commits)} commit(s) checked against the red and green rules")
        return self.items

    def _commit(self, c, seen_red, reds, approved_removed, approved_renames):
        short = c.sha[:7]
        self.commit_pos[c.sha] = len(self.commit_pos)
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
        if kind and not merge:
            self.task_commits.setdefault(task, []).append((c, kind))
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
                    self.approved_moves[ch.path] = (self.commit_pos[c.sha], "deleted", None)
                elif ch.status == "R":
                    approved_removed.add(ch.old)
                    approved_renames.append((ch.old, ch.path))
                    self.approved_moves[ch.old] = (self.commit_pos[c.sha], "renamed", ch.path)
            else:
                how = {"D": " (deleted)", "R": f" (renamed to {ch.path})"}.get(ch.status, "")
                self.fail(f"{label} at {short} touches locked test {hit[0]}{how}: {why}", hit[0])

        ever_locked = locked_paths | {e["path"] for e in entries_c}
        for ch in changes:
            self._test_file_rules(c, parent, ch, ever_locked, label, kind)

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
        if c.sha == self.base_sha or not any(CONFIG_PATH in (ch.path, ch.old) for ch in changes):
            return
        if self.base_sha:   # compared with what the check uses, the base commit's settings
            before = self._base_signature
        else:
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
        short = c.sha[:7]
        for rid, found in rows_c.items():
            row = found[0][0]
            status = row.get("Status")
            before = rows_p.get(rid)
            before_row = before[0][0] if before else None
            if before_row is None and status != "open":
                self.fail(f"commit {short}: request {rid} is born {status}; a request is opened first (tdd change-request new) "
                          f"and decided later, in a commit of its own")
            elif before_row is not None and before_row.get("Status") in ("approved", "rejected") and row != before_row:
                self.fail(f"commit {short}: decided request {rid} was edited; a decision is final")
            if status in ("approved", "rejected") and status != (before_row.get("Status") if before_row else None):
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

    def _test_file_rules(self, c, parent, ch, ever_locked, label, kind=None):
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
        if kind in ("green", "refactor") and (tm.is_test_config_file(new_path) or tm.is_test_config_file(old_path)):
            config_before = tm.test_config_text(old_path, before_text) if before_text is not None else None
            config_after = tm.test_config_text(new_path, after_text) if after_text is not None else None
            if (config_before or "") != (config_after or ""):
                problems.append(f"test configuration {new_path} changed by a [{kind}] commit: how tests are collected changes "
                                f"only through an approved change request")
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

    # -- the runtime comparison of the locked tests
    @contextlib.contextmanager
    def _worktree(self, sha):
        temp_root = Path(self.s.temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="tdd-replay-", dir=temp_root))
        tree = work / "tree"
        try:
            worktree_add(self.repo, tree, sha)
            yield tree
        finally:
            self._cleanup(tree, work)

    def _list_tests(self, sha, listing):
        """The outcome of each test the runner runs at a commit, [{"id", "outcome"}], or an error text."""
        argv, parse = listing
        try:
            with self._worktree(sha) as tree:
                proc = subprocess.run(argv, cwd=str(tree), capture_output=True, timeout=self.s.replay_timeout,
                                      env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), check=False)
        except subprocess.TimeoutExpired:
            return None, f"the listing timed out after {self.s.replay_timeout:g} s"
        except (OSError, GitError) as exc:
            return None, f"cannot list the tests: {exc}"
        try:
            return parse(proc.stdout.decode("utf-8", "replace") + "\n" + proc.stderr.decode("utf-8", "replace")), None
        except ValueError as exc:
            return None, f"cannot read the listing of the tests ({exc})"

    def _runtime_compare(self, reds):
        """The locked tests of a task are RUN at each later [green] and [refactor] commit of the task and each must run: not be
        missing, skipped or reported as an expected failure, whatever configuration, hook, patch or import did it. The ids come
        from the test file as the red commit has it; an approved rename maps them to the new file, an approved deletion removes
        them."""
        warned = False
        for c, task, _changes in reds:
            seq = self.task_commits.get(task, [])
            later, after = [], False
            for x, k in seq:
                if x is c:
                    after = True
                elif after and k in ("green", "refactor"):
                    later.append(x)
            entries = self.lock_at(c.sha)[0] or []
            base_live = {p: e for p, e in tdd_lock.live_entries(entries).items() if e["task_id"] == task and tm.language_of(p) == "python"}
            base_ids = {}
            for path in base_live:
                data = self.blobs_for_replay(c.sha, path)
                ids = static_test_ids(path, data.decode("utf-8-sig", "replace")) if data is not None else []
                if ids:
                    base_ids[path] = ids
            if not later or not base_ids:
                continue
            for lc in later:
                with_tree = tdd_lock.live_entries(self.lock_at(lc.sha)[0] or [])
                same = {p: ids for p, ids in base_ids.items() if p in with_tree and with_tree[p]["sha256"] == base_live[p]["sha256"]}
                if not same:
                    continue
                # a tests folder that is a package at this commit is discovered from the root, as the replay does
                listing = self._listing_command(lc)
                if listing is None:
                    if not warned:
                        self.warn("the runtime comparison of the locked tests needs a pytest or unittest discovery test command; "
                                  "it was not run")
                        warned = True
                    break
                found, error = self._list_tests(lc.sha, listing)
                if error:
                    self.fail(f"task {task} at {lc.sha[:7]}: {error}; the locked tests cannot be shown to run")
                    continue
                for path, ids in same.items():
                    target = path
                    move = self.approved_moves.get(path)
                    if move and self.commit_pos.get(lc.sha, -1) >= move[0]:
                        if move[1] == "deleted":
                            continue   # an approved deletion removes the ids
                        target = move[2]   # an approved rename maps the old ids to the new file
                    for problem in compare_listing(target, ids, found):
                        self.fail(f"task {task} at {lc.sha[:7]}: {problem}", target)

    def blobs_for_replay(self, sha, path):
        """A file at a commit (the batch reader is closed by now, so one plain git read)."""
        return show(self.repo, sha, path)

    def _listing_command(self, commit):
        """(argv, parser) that lists the tests at a commit, from the configured test command; None when it is not pytest or
        unittest discovery. Whether `tests` is a package at that commit decides `-t .` for the default command."""
        has_init = show(self.repo, commit.sha, "tests/__init__.py") is not None
        temp_root = Path(self.s.temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
        return listing_command(self.s.test_command, has_init, temp_root)

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
