"""The scratch world of the end-to-end self-test (unit U11), and the scenario steps shared by its three test files.

Everything here goes through the public command line (`batuta.py`, `hook.py`, `bin/batuta.mjs`) in subprocesses, never
through an import of an area: the test is the newcomer's view of the product.

A `World` is one scratch directory holding a temporary home (`HOME`, `USERPROFILE`), a device copy (`BATUTA_HOME`), the
temp, data and worktree roots, a local bare remote and a project repository. Nothing leaves it: no real home, no
network. `close()` removes it, including git's read-only object files.

Run the package from the repository root:
    python -m unittest discover -s tests/e2e -p "test_*.py" -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
import _home_guard  # noqa: E402,F401  (installs the real-home guard for every test of the package)

REPO = TESTS.parent
PLUGIN = REPO / "plugins" / "batuta"
CLI = PLUGIN / "scripts" / "batuta.py"
HOOK = PLUGIN / "scripts" / "hook.py"
NPX = REPO / "bin" / "batuta.mjs"
GIT_MINIMUM = (2, 30)
FEATURE = "002-greeting"
TASK = "T-001"
TASK_BRANCH = "task/greeting"
TEST_PATH = "tests/test_greeter.py"
TAGS = ("OK", "NEW", "CHANGED", "SAME", "MERGED", "REMOVED", "MISSING", "DIFFERENT", "REFUSED", "WARN", "FAIL", "SKIP")


def git_version():
    """(major, minor) of the git on PATH, or None when git is missing."""
    try:
        done = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"(\d+)\.(\d+)", done.stdout)
    return (int(found.group(1)), int(found.group(2))) if found else None


def require_git():
    """git is required: a missing or too old git fails the suite (it is never a skip)."""
    version = git_version()
    if version is None:
        raise AssertionError("git is required by the end-to-end self-test and was not found on PATH")
    if version < GIT_MINIMUM:
        raise AssertionError("git %d.%d or newer is required, found %d.%d" % (GIT_MINIMUM + version))


def skip_unless_tool(test_case, name, version_probe=None):
    """Skip a channel test whose tool is missing, naming the tool and saying why (never a silent pass)."""
    path = shutil.which(name)
    if path is None:
        reason = "%s is not on PATH: the %s channel is not exercised on this machine" % (name, name)
        sys.stderr.write("SKIPPED: %s\n" % reason)
        test_case.skipTest(reason)
    if version_probe is not None:
        reason = version_probe(path)
        if reason:
            sys.stderr.write("SKIPPED: %s\n" % reason)
            test_case.skipTest(reason)
    return path


def _on_rm_error(func, path, _info):
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except OSError:
        pass


def remove_tree(path):
    """Delete a folder tree, read-only git object files included."""
    if not Path(path).exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=lambda f, p, e: _on_rm_error(f, p, e))
    else:
        shutil.rmtree(path, onerror=_on_rm_error)


class Result:
    """The outcome of one command: exit code, both streams, and helpers to read the tag lines."""

    def __init__(self, argv, rc, out, err):
        self.argv, self.rc, self.out, self.err = argv, rc, out, err

    @property
    def text(self):
        return self.out + self.err

    def lines(self, tag=None):
        found = [line for line in self.out.splitlines() if line.split(" ", 1)[0] in TAGS]
        return [line for line in found if line.startswith(tag + " ")] if tag else found

    def json(self):
        return json.loads(self.out)

    def describe(self):
        return "command: %s\nexit code: %s\nstdout:\n%s\nstderr:\n%s" % (" ".join(map(str, self.argv)), self.rc, self.out, self.err)


class World:
    """One scratch world; create with `World()` and always `close()` (a test uses addCleanup)."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="batuta-e2e-")).resolve()
        self.home = self.root / "home"
        self.deploy = self.root / "device"
        self.temp = self.root / "temp"
        self.data = self.root / "data"
        self.worktrees = self.root / "worktrees"
        self.remote = self.root / "remote.git"
        self.project = self.root / "project"
        self.payloads = self.root / "payloads"
        self.files = self.root / "files"
        for folder in (self.home, self.deploy, self.temp, self.data, self.worktrees, self.payloads, self.files, self.project):
            folder.mkdir(parents=True, exist_ok=True)
        self._payload_count = 0
        self.env = self._environment()
        self.git("init", "--bare", "-q", str(self.remote), cwd=self.root)

    # ------------------------------------------------------------------ plumbing
    def _environment(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("BATUTA_", "CLAUDE", "GIT_", "XDG_", "PYTHON", "COPIER"))}
        interpreter = Path(sys.executable).resolve().parent
        env["PATH"] = os.pathsep.join([str(interpreter), str(interpreter / "Scripts"), env.get("PATH", "")])
        env.update({
            "HOME": str(self.home), "USERPROFILE": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "BATUTA_HOME": str(self.deploy), "BATUTA_TEMP": str(self.temp), "BATUTA_DATA": str(self.data),
            "BATUTA_WORKTREES": str(self.worktrees),
            "BATUTA_PYTHON": sys.executable,
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
            "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "Scratch Author", "GIT_AUTHOR_EMAIL": "author@example.org",
            "GIT_COMMITTER_NAME": "Scratch Author", "GIT_COMMITTER_EMAIL": "author@example.org",
        })
        return env

    def close(self):
        remove_tree(self.root)

    def run(self, argv, cwd=None, stdin_path=None, timeout=180, env=None):
        argv = [str(a) for a in argv]
        stdin = open(str(stdin_path), "rb") if stdin_path is not None else subprocess.DEVNULL
        try:
            done = subprocess.run(argv, cwd=str(cwd or self.project), env=env or self.env, stdin=stdin,
                                  capture_output=True, timeout=timeout)
        finally:
            if stdin_path is not None:
                stdin.close()
        return Result(argv, done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace"))

    def batuta(self, *args, cwd=None):
        """`python batuta.py <args>` from the project root (or `cwd`)."""
        return self.run([sys.executable, CLI, *args], cwd=cwd)

    def git(self, *args, cwd=None):
        return self.run(["git", *args], cwd=cwd)

    def payload(self, doc):
        """Write a C16 payload file and return its path."""
        self._payload_count += 1
        path = self.payloads / ("payload-%03d.json" % self._payload_count)
        path.write_text(json.dumps(doc), encoding="utf-8", newline="\n")
        return path

    def hook(self, hook_id, doc, cwd=None):
        """Pipe a C16 payload file into `hook.py <id>`; returns the Result (stdout is the decision JSON, or empty)."""
        return self.run([sys.executable, "-I", HOOK, hook_id], cwd=cwd, stdin_path=self.payload(doc))

    # payload builders (C16): `cwd` is always the project folder
    def prompt_payload(self, prompt):
        return {"session_id": "e2e", "cwd": str(self.project), "hook_event_name": "UserPromptSubmit", "prompt": prompt}

    def pretool_payload(self, tool, tool_input):
        return {"session_id": "e2e", "cwd": str(self.project), "hook_event_name": "PreToolUse",
                "tool_name": tool, "tool_input": tool_input}

    def stop_payload(self):
        return {"session_id": "e2e", "cwd": str(self.project), "hook_event_name": "Stop", "stop_hook_active": False}

    # files of the project
    def path(self, rel):
        return self.project / rel

    def write(self, rel, text, root=None):
        target = Path(root or self.project) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        return target

    def read(self, rel):
        return (self.project / rel).read_text(encoding="utf-8")

    def head(self):
        return self.git("rev-parse", "HEAD").out.strip()

    def commit_all(self, message):
        self.git("add", "-A")
        done = self.git("commit", "-q", "-m", message)
        return done

    def commit_paths(self, message, *paths):
        """Commit only the named paths (the test file stays out of the spec commit: the red commit adds it)."""
        paths = [p for p in paths if (self.project / p).exists()]
        self.git("add", "--", *paths)
        return self.git("commit", "-q", "-m", message, "--", *paths)

    def clone(self):
        """A new world whose project (with its .git) and bare remote are copies of this one's; `origin` follows the copy."""
        other = World()
        remove_tree(other.project)
        remove_tree(other.remote)
        shutil.copytree(str(self.project), str(other.project))
        shutil.copytree(str(self.remote), str(other.remote))
        done = other.git("remote", "set-url", "origin", str(other.remote))
        if done.rc != 0:
            raise AssertionError(done.describe())
        return other


class WorldCase(unittest.TestCase):
    """A test case with helpers that fail with the whole command output."""

    @classmethod
    def setUpClass(cls):
        require_git()

    def new_world(self):
        world = World()
        self.addCleanup(world.close)
        return world

    def ok(self, result, *needles, rc=0):
        self.assertEqual(result.rc, rc, result.describe())
        for needle in needles:
            self.assertIn(needle, result.text, "expected %r in\n%s" % (needle, result.describe()))
        return result

    def refused(self, result, *needles, rc=1):
        """A command that must refuse: the exit code and the reason are both asserted."""
        return self.ok(result, *needles, rc=rc)

    def validate(self, world, contract_id, path, root=None):
        """`contract validate <id> <file>` exits 0 and says so (the contract test on this side of every artifact)."""
        args = ["contract", "validate", contract_id, str(path)]
        if root is not None:
            args += ["--root", str(root)]
        return self.ok(world.batuta(*args, cwd=world.root), "validate %s: ok" % contract_id)

    def decision(self, result):
        """The hook decision object printed on stdout, or None when the hook printed nothing."""
        text = result.out.strip()
        return json.loads(text) if text else None

    def assertDenied(self, result):
        self.assertEqual(result.rc, 0, result.describe())
        doc = self.decision(result)
        self.assertIsNotNone(doc, "the guard printed no decision\n" + result.describe())
        out = doc.get("hookSpecificOutput", {})
        self.assertEqual(out.get("permissionDecision"), "deny", result.describe())
        self.assertIn("BLOCKED by", out.get("permissionDecisionReason", ""), result.describe())
        return out["permissionDecisionReason"]

    def assertAllowed(self, result):
        self.assertEqual(result.rc, 0, result.describe())
        doc = self.decision(result)
        if doc is not None:
            self.assertNotEqual(doc.get("hookSpecificOutput", {}).get("permissionDecision"), "deny", result.describe())
            self.assertNotEqual(doc.get("decision"), "block", result.describe())


class RefusalCase(WorldCase):
    """A case whose tests refuse things in a project that is already green: built once, cloned per test (a clone is cheap,
    the build is about a dozen commands of the lifecycle)."""

    template = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = World()
        try:
            build_green_project(WorldCase("assertTrue"), cls.template)
        except BaseException:
            cls.template.close()
            raise

    @classmethod
    def tearDownClass(cls):
        if cls.template is not None:
            cls.template.close()

    def fresh(self):
        world = self.template.clone()
        self.addCleanup(world.close)
        return world


# ---------------------------------------------------------------------------------------------------- scenario steps

SPEC = """---
id: 002-greeting
title: Greeting
status: Review
tier: S
owner: scratch-owner
created: 2026-10-18
---

## Problem

A greeter returns a greeting for a name. Done: the two requirements below pass their gates.

## Scope and out of scope

In: the greet function. Out: everything else.

## Requirements

| Id | Kind | EARS text | Gate | Verification | Status |
|---|---|---|---|---|---|
| REQ-GREET-001 | event | When `greet` is called with a non-blank name, the system shall return `Hello, <name>!`. | `python -m unittest tests/test_greeter.py` | unit test | active |
| REQ-GREET-002 | unwanted | If `greet` is called with a blank name, then the system shall raise `ValueError`. | `python -m unittest tests/test_greeter.py` | unit test | active |

## Interfaces

none

## Edge cases

A blank name raises; surrounding blanks are trimmed.

## Open questions

None.
"""

TASKS = """# Tasks

| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |
|---|---|---|---|---|---|---|---|
| T-001 | Greet by name | REQ-GREET-001, REQ-GREET-002 | - | - | | implementer | - |
"""

GREETER_TEST = """import unittest

from greeter import greet


# REQ: REQ-GREET-001, REQ-GREET-002
class GreetTests(unittest.TestCase):
    def test_greets_by_name(self):
        self.assertEqual(greet("Ada"), "Hello, Ada!")

    def test_trims_the_name(self):
        self.assertEqual(greet("  Ada "), "Hello, Ada!")

    def test_blank_name_is_refused(self):
        with self.assertRaises(ValueError):
            greet("   ")
"""

GREETER = '''def greet(name):
    """Return the greeting for a name; a blank name is refused."""
    name = name.strip()
    if not name:
        raise ValueError("name must not be blank")
    return "Hello, %s!" % name
'''

EVIDENCE = """---
gate: L0-understand
feature: 002-greeting
verdict: PASS
role: adversary
model: sonnet
commit: "{commit}"
date: 2026-10-18
---

## Definition of done restated

Both requirements of the spec are understood and each names a gate that can fail.

## Commands and output

`spec lint --spec 002-greeting` exited 0 at the reviewed commit.

## Findings

| Id | Severity | Claim | Reproduction | Status |
|---|---|---|---|---|

## Waivers requested

None.
"""

GITIGNORE = "__pycache__/\n.batuta/gate-stop.state\n"


def init_repository(world):
    """A git repository with an identity, an `origin` that is the local bare remote and branch `main`."""
    for args in (("init", "-q", "-b", "main"), ("config", "core.autocrlf", "false"), ("config", "user.name", "Scratch Author"),
                 ("config", "user.email", "author@example.org"), ("remote", "add", "origin", str(world.remote))):
        done = world.git(*args)
        if done.rc != 0:
            raise AssertionError(done.describe())


def adopt_project(case, world):
    """init project (dry run, then apply), commit on main, push to the local remote, branch `task/greeting`."""
    init_repository(world)
    dry = case.ok(world.batuta("init", "project", "--target", ".", "--var", "project_name=greeter"), "dry run")
    case.assertEqual(world.git("status", "--short").out.strip(), "", "a dry run must write nothing\n" + dry.describe())
    case.ok(world.batuta("init", "project", "--target", ".", "--var", "project_name=greeter", "--apply"), "written in")
    world.write(".gitignore", world.read(".gitignore") + GITIGNORE)
    case.ok(world.commit_all("chore: adopt Batuta"), rc=0)
    case.ok(world.git("push", "-q", "origin", "main"))
    case.ok(world.git("checkout", "-q", "-b", TASK_BRANCH))


def write_spec(case, world):
    """spec new (dry run, then apply), then the spec and tasks content."""
    dry = case.ok(world.batuta("spec", "new", "--title", "Greeting", "--tier", "S"), "dry run")
    case.assertFalse(world.path("specs/%s" % FEATURE).exists(), dry.describe())
    case.ok(world.batuta("spec", "new", "--title", "Greeting", "--tier", "S", "--apply"), "spec new")
    world.write("specs/%s/spec.md" % FEATURE, SPEC)
    world.write("specs/%s/tasks.md" % FEATURE, TASKS)


def approval_phrase(case, world):
    """The phrase `spec show` tells a person to type."""
    shown = case.ok(world.batuta("spec", "show", FEATURE))
    found = re.search(r"approval phrase to type: (approve \S+ [0-9a-f]{12})", shown.out)
    case.assertIsNotNone(found, shown.describe())
    return found.group(1)


def approve(case, world):
    """The typed approval, delivered through the `spec-approval` hook payload."""
    phrase = approval_phrase(case, world)
    done = world.hook("spec-approval", world.prompt_payload(phrase))
    case.assertEqual(done.rc, 0, done.describe())
    case.assertIn("approval recorded", done.out, done.describe())
    return phrase


def build_green_project(case, world):
    """The scenario up to the green commit: adopt, spec, approval, lock, red commit, implementation, green commit."""
    adopt_project(case, world)
    write_spec(case, world)
    world.write(TEST_PATH, GREETER_TEST)
    case.ok(world.batuta("spec", "lint", "--spec", FEATURE), "satisfies C05")
    case.ok(world.batuta("spec", "trace", FEATURE, "--apply"), "ok=true")
    approve(case, world)
    case.ok(world.commit_paths("docs(spec): 002-greeting spec, tasks and typed approval", "specs", "docs"))
    case.ok(world.batuta("tdd", "lock", "--task", TASK, TEST_PATH, "--apply"), "locked")
    case.ok(world.batuta("tdd", "commit", "--red", TASK, "-m", "Greet by name", TEST_PATH, "--apply"), "[red] T-001")
    world.write("greeter.py", GREETER)
    case.ok(world.batuta("tdd", "commit", "--green", TASK, "-m", "Greet by name", "greeter.py", "--apply"), "[green] T-001")


def write_status(world):
    """The feature's status file: a copy of the example feature's, for this feature."""
    text = world.read("specs/001-example-feature/status.md").replace("feature: 001-example-feature", "feature: " + FEATURE)
    world.write("specs/%s/status.md" % FEATURE, text)


def pass_l0(case, world):
    """Write the L0 evidence for the head, lint it and set the gate; returns nothing, asserts every step."""
    write_status(world)
    world.write("specs/%s/evidence/L0-understand.md" % FEATURE, EVIDENCE.format(commit=world.head()))
    case.ok(world.batuta("gate", "evidence-lint", "specs/%s/evidence/L0-understand.md" % FEATURE), "valid evidence")
    case.ok(world.batuta("gate", "status", FEATURE, "--set", "L0-understand=passed", "--apply"), "CHANGED L0-understand")


def run_project_tests(world):
    """The project's own test command, as CI runs it; returns the Result (stderr holds unittest's report)."""
    return world.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"])


def write_sizing_and_catalog(case, world):
    """Size and catalog from the shipped contract fixtures (data files): the sizing lives outside the repository, the
    catalog at its default place; both are validated and the sizing is cross-checked against the catalog."""
    fixtures = PLUGIN / "contracts" / "fixtures"
    sizing = (fixtures / "C23" / "valid-product-sizing.md").read_text(encoding="utf-8")
    for name, unit in (("ingest-pipeline", "u-pipeline"), ("alerts-api", "u-api"), ("ops-ui", "u-ui"), ("severity-model", "u-model")):
        sizing = re.sub(r"^- %s \(alert-triage\): " % name, "- %s (alert-triage) (unit: %s): " % (name, unit), sizing, flags=re.M)
    sizing_path = world.write("sizing.md", sizing, root=world.files)
    catalog = (fixtures / "C22" / "valid-three-rows-with-a-model-slot.md").read_text(encoding="utf-8")
    world.write("docs/contracts/catalog.md", catalog)
    return sizing_path
