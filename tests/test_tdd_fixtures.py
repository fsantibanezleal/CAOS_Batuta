"""Scratch git repositories and CLI calls shared by the tdd tests, plus a check of the helpers themselves."""
import atexit
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPTS, load_batuta

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib import config  # noqa: E402

TEST_CALC = """# REQ: REQ-CALC-001
import unittest

import calc


class CalcTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(calc.add(2, 3), 5)

    def test_add_negative(self):
        self.assertEqual(calc.add(-1, 1), 0)
"""
CALC = "def add(a, b):\n    return a + b\n"
CALC_REFACTORED = "def add(a, b):\n    \"\"\"Sum of two numbers.\"\"\"\n    return a + b\n"
SPEC = "# Spec: calc\n\nREQ-CALC-001 adds two numbers.\n"
LOCK = ".batuta/test-locks.json"

_BATUTA = None


def batuta():
    global _BATUTA
    if _BATUTA is None:
        _BATUTA = load_batuta()
    return _BATUTA


def run_cli(*argv):
    """Run `batuta.py <argv>` in this process; returns (exit code, stdout text)."""
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = batuta().main([str(a) for a in argv])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return code, out.getvalue() + err.getvalue()


def write_config(folder, temp_root, **tdd):
    """A batuta.json with the temp root set and a `tdd` block; returns its path."""
    cfg = config.default_config({})
    cfg["roots"] = {"temp": str(temp_root), "data": str(Path(folder) / "data"), "worktrees": str(Path(folder) / "wt")}
    if tdd:
        cfg["tdd"] = tdd
    path = Path(folder) / "batuta.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


class Repo:
    """A scratch git repository with helpers to write files and commit them."""

    def __init__(self, root):
        self.root = Path(root)

    @classmethod
    def create(cls, root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        repo = cls(root)
        repo.git("init", "-q", "-b", "main")
        # one process start is far dearer than a file append: write the local config directly
        with open(root / ".git" / "config", "a", encoding="utf-8", newline="\n") as handle:
            handle.write("[user]\n\tname = Scratch\n\temail = scratch@example.invalid\n[commit]\n\tgpgsign = false\n"
                         "[core]\n\tautocrlf = false\n")
        return repo

    def clone_to(self, dest):
        shutil.copytree(self.root, dest)
        return Repo(dest)

    def git(self, *args, input=None, check=True):
        proc = subprocess.run(["git", *args], cwd=self.root, input=input, capture_output=True, text=True,
                              encoding="utf-8", check=False)
        if check and proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout

    def write(self, rel, text=None, data=None):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            path.write_bytes(data)
        else:
            path.write_bytes(text.encode("utf-8"))
        return path

    def remove(self, rel):
        (self.root / rel).unlink()

    def commit(self, message, *paths):
        present = [p for p in paths if (self.root / p).exists()]
        gone = [p for p in paths if p not in present]
        if present:
            self.git("add", "-A", "--", *present)
        if gone:
            self.git("rm", "-q", "--cached", "--ignore-unmatch", "--", *gone)
        self.git("commit", "-q", "--allow-empty", "-F", "-", input=message)

    def head(self):
        return self.git("rev-parse", "HEAD").strip()

    def show(self, rev, path):
        return self.git("show", f"{rev}:{path}")


def message(kind, task, title, trailer=None):
    text = f"[{kind}] {task} {title}\n"
    if trailer:
        text += f"\nTest-Change-Approved: {trailer}\n"
    return text


def build_compliant(repo, cfg):
    """init, red, green, refactor for T-001 (the red and the lock through the helpers). Returns the commit hashes."""
    shas = {}
    repo.write("README.md", "# scratch\n")
    repo.commit("init", "README.md")
    repo.write("tests/test_calc.py", TEST_CALC)
    code, out = run_cli("--config", cfg, "tdd", "lock", "--repo", repo.root, "--task", "T-001", "tests/test_calc.py", "--apply")
    assert code == 0, out
    code, out = run_cli("--config", cfg, "tdd", "commit", "--repo", repo.root, "--red", "T-001", "-m", "calc adds numbers",
                        "tests/test_calc.py", "--apply")
    assert code == 0, out
    shas["red"] = repo.head()
    repo.write("calc.py", CALC)
    code, out = run_cli("--config", cfg, "tdd", "commit", "--repo", repo.root, "--green", "T-001", "-m", "implement add",
                        "calc.py", "--apply")
    assert code == 0, out
    repo.write("calc.py", CALC_REFACTORED)
    code, out = run_cli("--config", cfg, "tdd", "commit", "--repo", repo.root, "--refactor", "T-001", "-m", "document add",
                        "calc.py", "--apply")
    assert code == 0, out
    return shas


_SHARED = {}


def shared_base():
    """The compliant history, built once per test process (every process start costs seconds on a loaded machine)."""
    if not _SHARED:
        holder = tempfile.TemporaryDirectory()
        atexit.register(holder.cleanup)
        folder = Path(holder.name)
        temp = folder / "temp"
        temp.mkdir()
        cfg = write_config(folder, temp)
        repo = Repo.create(folder / "base")
        _SHARED.update(repo=repo, shas=build_compliant(repo, cfg), cfg=cfg)
    return _SHARED


class TddCase(unittest.TestCase):
    """Base class: a temp folder per test class (`self.tmp`) and the batuta.json in it."""

    tdd_settings = {}

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.temp_root = cls.tmp / "temp"
        cls.temp_root.mkdir()
        cls.cfg = write_config(cls.tmp, cls.temp_root, **cls.tdd_settings)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def fresh(self, name):
        return Repo.create(self.tmp / name)

    def check(self, repo, *extra, cfg=None):
        return run_cli("--config", cfg or self.cfg, "tdd", "check", "--repo", repo.root, *extra)

    def lock(self, repo, task, *paths, extra=(), cfg=None):
        return run_cli("--config", cfg or self.cfg, "tdd", "lock", "--repo", repo.root, "--task", task, *paths, "--apply", *extra)


class SupportTests(unittest.TestCase):
    def test_a_scratch_repo_commits_and_reads_back(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Repo.create(Path(d) / "r")
            repo.write("a.txt", "one\n")
            repo.commit("first", "a.txt")
            self.assertEqual(repo.show(repo.head(), "a.txt"), "one\n")


if __name__ == "__main__":
    unittest.main()
