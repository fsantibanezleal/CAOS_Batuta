"""Shared helpers for the init, template, doctor, update and uninstall tests (no tests here): the fixture variable set of
the project template, a scratch git repository, a snapshot of a folder, and the isolated worlds (home, deploy root,
project) every test builds in a temporary folder. Never touches the real home folder or a real project."""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
from test_device_support import run  # noqa: E402,F401  (re-exported: the in-process CLI runner)

TEMPLATE_DIR = ROOT / "plugins" / "batuta" / "templates" / "project"
WORKFLOW = ".github/workflows/batuta-gates.yml"
FIXTURE_VARS = {
    "project_name": "Demo Project",
    "python_version": "3.12",
    "test_command": "python -m unittest discover -s tests -t . -v",
    "default_branch": "main",
    "batuta_ref": "v0.01.000",
}
VAR_ARGS = [a for k, v in FIXTURE_VARS.items() for a in ("--var", f"{k}={v}")]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(folder):
    """{relative posix path: bytes} of every file under `folder`, and the folders as {path: None}."""
    folder = Path(folder)
    out = {}
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if ".git/" in rel + "/" or rel == ".git":
            continue
        out[rel] = p.read_bytes() if p.is_file() else None
    return out


def git(root, *args, check=True):
    """Run git in `root` with a fixed identity and no signing; returns stdout stripped."""
    base = ["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false",
            "-c", "core.autocrlf=false", "-c", "gc.auto=0", "-c", "maintenance.auto=false"]   # no detached maintenance after a commit
    done = subprocess.run([*base, *args], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr}")
    return done.stdout.strip()


def make_repo(path):
    """An empty git repository with the branch `main` at `path`."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "gc.auto", "0")                  # `git commit` would start a detached `git maintenance run --auto` that
    git(path, "config", "maintenance.auto", "false")     # can still write into .git/objects while the folder is being removed
    return path


def commit_all(path, message="work"):
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD")


def bash_path():
    """A usable bash, or None (the workflow's shell logic is tested only where one exists)."""
    import shutil
    for candidate in (shutil.which("bash"),):
        if not candidate:
            continue
        done = subprocess.run([candidate, "-c", "echo ok"], capture_output=True, text=True, timeout=30)
        if done.returncode == 0 and done.stdout.strip() == "ok":
            return candidate
    return None


def workflow_text():
    return (TEMPLATE_DIR / WORKFLOW).read_text(encoding="utf-8")


def step_block(text, step_id):
    """The lines of the workflow step that carries `id: <step_id>` (from its `- ` line to the next step)."""
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if re.match(r"^      - ", ln)]
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[start:end]
        if any(re.match(rf"^\s+(- )?id: {re.escape(step_id)}\s*$", ln) for ln in block):
            return block
    raise AssertionError(f"no step with id {step_id}")


def run_block(block):
    """The text of the `run: |` block of a step, dedented."""
    for i, ln in enumerate(block):
        if re.match(r"^\s+run: \|\s*$", ln):
            body = []
            for line in block[i + 1:]:
                if line.strip() == "":
                    body.append("")
                    continue
                if not line.startswith("          "):
                    break
                body.append(line[10:])
            return "\n".join(body).rstrip() + "\n"
    raise AssertionError("no run block")


class World(unittest.TestCase):
    """A temp world: `home` (with .claude), `bh` (BATUTA_HOME), a `project` folder with a space in its name."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.bh = self.root / "bh"
        self.project = self.root / "my project"
        self.env = {"BATUTA_HOME": str(self.bh)}

    def cli(self, *argv, env=None):
        return run(*argv, env={**self.env, **(env or {})})

    def init_project(self, *extra, apply=True, target=None):
        args = ["init", "project", "--target", str(target or self.project), *VAR_ARGS, *extra]
        return self.cli(*args, *(["--apply"] if apply else []))

    def init_user(self, *extra, apply=True):
        args = ["init", "user", "--home", str(self.home), *extra]
        return self.cli(*args, *(["--apply"] if apply else []))
