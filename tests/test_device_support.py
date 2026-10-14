"""Shared helpers for the device and preflight tests (no tests here): a CLI runner with an isolated environment and a
device fixture (temp home, temp deploy root). Never touches the real home folder."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
from _support import load_batuta  # noqa: E402

def make_link(link, target):
    """A directory symlink, or a junction on Windows when symlinks need a privilege; SkipTest when neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if done.returncode == 0:
            return
    raise unittest.SkipTest("cannot create a symlink or a junction here")


def make_file_link(link, target):
    """A file symlink; SkipTest when the account may not create one (a junction cannot point at a file)."""
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        raise unittest.SkipTest("cannot create a file symlink here")


def run(*argv, env=None):
    """Run the dispatcher in-process; returns (exit code, stdout, stderr)."""
    batuta = load_batuta()
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"BATUTA_CONFIG": "", **(env or {})}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = batuta.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def tree_digest(folder):
    """{relative posix path: sha256} of every file under `folder`."""
    folder = Path(folder)
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class DeviceCase(unittest.TestCase):
    """A temp world: `home` (with .claude), `deploy` (the device copy folder) and `bh` (BATUTA_HOME for the roots)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.deploy_dir = self.root / "device copy"          # a space on purpose
        self.bh = self.root / "bh"
        self.env = {"BATUTA_HOME": str(self.bh)}
        self.settings = self.home / ".claude" / "settings.json"

    def cli(self, *argv, env=None):
        return run(*argv, env={**self.env, **(env or {})})

    def deploy(self, *extra, apply=True):
        args = ["device", "deploy", "--deploy-root", str(self.deploy_dir), "--home", str(self.home), *extra]
        return self.cli(*args, *(["--apply"] if apply else []))

    def restore(self, *extra, apply=True, env=None):
        args = ["device", "restore", "--deploy-root", str(self.deploy_dir), "--home", str(self.home), *extra]
        return self.cli(*args, *(["--apply"] if apply else []), env=env)

    def add_launcher(self):
        """The launcher of the hooks unit (U8) is not in this branch; a stand-in lets the session-check preset render."""
        path = self.deploy_dir / "scripts" / "hook.py"
        path.write_text("# launcher stand-in for the tests\n", encoding="utf-8")
        return path

    def settings_doc(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))
