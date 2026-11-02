"""No search for a project root climbs to the user's home or above it; `<home>/.batuta` is never a project marker; a
project made from the template never commits delegation records (fix of 2026-10-17)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _home_guard  # noqa: E402,F401
from _support import ROOT, SCRIPTS  # noqa: E402
from test_brief_support import run, write_config  # noqa: E402
from test_init_support import FIXTURE_VARS  # noqa: E402
from test_report_hook import transcript  # noqa: E402

from batuta_lib import delegation, guards  # noqa: E402
from batuta_lib.areas import gate as gate_area  # noqa: E402
from batuta_lib.areas import init as init_area  # noqa: E402
from batuta_lib.areas import report as report_area  # noqa: E402

TEMPLATE = ROOT / "plugins" / "batuta" / "templates" / "project"


class HomeCase(unittest.TestCase):
    """A temporary home that holds a real-looking `.batuta` folder, `HOME` and `USERPROFILE` pointing to it, and
    `BATUTA_HOME` elsewhere (so the folder no longer counts as the Batuta home)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.home = self.base / "home"
        (self.home / ".batuta" / "temp").mkdir(parents=True)
        self.work = self.home / "tmp" / "scratch" / "deep"
        self.work.mkdir(parents=True)
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "BATUTA_HOME": str(self.base / "elsewhere")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in ("CLAUDE_PROJECT_DIR", "BATUTA_CONFIG"):
            os.environ.pop(var, None)

    def tree(self):
        return sorted(p.relative_to(self.home).as_posix() for p in self.home.rglob("*"))


class SharedHelper(HomeCase):
    def test_ascend_never_reaches_the_home(self):
        from batuta_lib import projectroot
        folders = list(projectroot.ascend(self.work))
        self.assertEqual(folders[0], self.work)
        self.assertNotIn(self.home, folders)
        self.assertEqual(folders[-1], self.home / "tmp")

    def test_every_home_the_environment_names_is_a_boundary(self):
        from batuta_lib import projectroot
        other = self.base / "other-home"
        (other / "p").mkdir(parents=True)
        os.environ["HOME"] = str(other)           # USERPROFILE keeps the first home
        self.assertEqual(list(projectroot.ascend(other / "p")), [other / "p"])
        self.assertEqual(list(projectroot.ascend(self.work))[-1], self.home / "tmp")

    def test_a_start_at_the_home_or_above_it_yields_nothing(self):
        from batuta_lib import projectroot
        self.assertEqual(list(projectroot.ascend(self.home)), [])
        self.assertEqual(list(projectroot.ascend(self.home.parent)), [])

    def test_find_returns_the_first_folder_the_test_accepts_or_none(self):
        from batuta_lib import projectroot
        app = self.home / "repos" / "app"
        (app / ".git").mkdir(parents=True)
        (app / "src").mkdir()
        self.assertEqual(projectroot.find(app / "src", lambda f: (f / ".git").exists()), app)
        self.assertIsNone(projectroot.find(self.work, lambda f: (f / ".batuta").exists()))


class EverySearch(HomeCase):
    def test_guards_root_above_never_takes_the_home_batuta_folder_for_a_marker(self):
        self.assertEqual(guards.root_above(self.work), self.work.resolve())

    def test_guards_root_above_never_takes_a_git_folder_of_the_home(self):
        (self.home / ".git").mkdir()
        self.assertEqual(guards.root_above(self.work), self.work.resolve())

    def test_guards_project_root_from_a_payload_below_the_home(self):
        self.assertEqual(guards.project_root({"cwd": str(self.work)}), self.work.resolve())

    def test_delegation_find_project_root_never_takes_the_home_batuta_folder(self):
        self.assertEqual(delegation.find_project_root(self.work), self.work.resolve())

    def test_delegation_find_project_root_with_a_batuta_config_file_in_the_home(self):
        (self.home / ".batuta" / "batuta.json").write_text("{}", encoding="utf-8")
        self.assertEqual(delegation.find_project_root(self.work), self.work.resolve())

    def test_gate_project_root_never_takes_a_specs_folder_of_the_home(self):
        (self.home / "specs").mkdir()
        self.assertIsNone(gate_area._project_root(self.work))

    def test_a_project_inside_the_home_still_finds_its_own_root(self):
        app = self.home / "repos" / "app"
        (app / ".git").mkdir(parents=True)
        (app / "specs").mkdir()
        deep = app / "src" / "pkg"
        deep.mkdir(parents=True)
        self.assertEqual(guards.root_above(deep), app.resolve())
        self.assertEqual(delegation.find_project_root(deep), app.resolve())
        self.assertEqual(gate_area._project_root(deep), app.resolve())

    def test_a_project_with_its_own_batuta_folder_inside_the_home(self):
        app = self.home / "repos" / "app"
        (app / ".batuta").mkdir(parents=True)
        deep = app / "a"
        deep.mkdir()
        self.assertEqual(guards.root_above(deep), app.resolve())
        self.assertEqual(delegation.find_project_root(deep), app.resolve())

    def test_a_cwd_that_is_the_home_resolves_to_itself_and_never_above(self):
        self.assertEqual(delegation.find_project_root(self.home), self.home.resolve())
        self.assertEqual(guards.root_above(self.home), self.home.resolve())

    def test_a_marker_above_the_home_is_never_reached(self):
        (self.base / ".git").mkdir()
        self.assertEqual(delegation.find_project_root(self.work), self.work.resolve())
        self.assertEqual(guards.root_above(self.work), self.work.resolve())

    def test_no_module_keeps_its_own_upward_search_over_the_parents(self):
        lib = SCRIPTS / "batuta_lib"
        allowed = {"projectroot.py"}
        for rel in ("guards/__init__.py", "delegation.py", "areas/gate.py", "areas/report.py"):
            text = (lib / rel).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\*\w+\.parents", text), rel)
        self.assertTrue((lib / "projectroot.py").is_file() and allowed)


class SubagentStopReproduction(HomeCase):
    """The reproduction: the hook run from a folder below a home that holds `.batuta`."""

    def payload(self, cwd):
        t = transcript(cwd / "agent.jsonl", "Do it.\n\n## Deliverables\n- D1: x\n")
        return {"hook_event_name": "SubagentStop", "agent_type": "implementer", "cwd": str(cwd),
                "last_assistant_message": "no lines", "agent_transcript_path": str(t), "stop_hook_active": True}

    def test_the_log_never_lands_in_the_home(self):
        report_area.handler(self.payload(self.work))
        logs = [p for p in self.tree() if p.endswith("unverified.log")]
        self.assertEqual(logs, ["tmp/scratch/deep/.batuta/delegation/unverified.log"])
        self.assertFalse((self.home / ".batuta" / "delegation").exists())

    def test_the_configuration_order_case_of_the_report_fixes(self):
        write_config(self.base / "cfgs", coordination_root="viaenv")
        os.environ["BATUTA_CONFIG"] = str(self.base / "cfgs" / ".batuta" / "batuta.json")
        report_area.handler(self.payload(self.work))
        self.assertFalse((self.home / "viaenv").exists())
        self.assertTrue((self.work / "viaenv" / "delegation" / "unverified.log").is_file())

    def test_hook_py_from_a_folder_below_the_home_writes_nothing_into_the_home(self):
        before = self.tree()
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "hook.py"), "subagent-stop"],
                              input=json.dumps(self.payload(self.work)), text=True, capture_output=True,
                              cwd=str(self.work), env=dict(os.environ), timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        added = [p for p in self.tree() if p not in before]
        self.assertTrue(all(p.startswith("tmp/scratch/deep/") for p in added), added)
        self.assertEqual(sorted(p for p in self.tree() if p.startswith(".batuta")), [".batuta", ".batuta/temp"])


class Template(unittest.TestCase):
    def git(self, dest, *args):
        return subprocess.run(["git", "-C", str(dest), *args], capture_output=True, text=True, timeout=120)

    def test_the_template_ignores_the_delegation_folder_of_the_coordination_root(self):
        text = (TEMPLATE / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".batuta/delegation/", text.splitlines())

    def test_the_template_files_say_delegation_records_belong_in_a_private_repository(self):
        for name in ("AGENTS.md", "CLAUDE.md"):
            text = " ".join((TEMPLATE / name).read_text(encoding="utf-8").lower().split())
            self.assertRegex(text, r"delegation records.*machine paths.*private", name)

    def test_a_rendered_project_stays_clean_after_a_brief_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp).resolve() / "proj"
            for rel, text in init_area.render_project(dict(FIXTURE_VARS)).items():
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                (dest / rel).write_text(text, encoding="utf-8", newline="\n")
            self.git(dest, "init", "-q")
            code, out, err = run("brief", "new", "--slug", "demo", "--topic", "alpha", "--agent", "implementer",
                                 "--title", "Inventory", "--root", dest, "--date", "2026-10-10")
            self.assertEqual(code, 0, (out, err))
            brief = next(dest.glob(".batuta/delegation/*.brief.md"))
            self.assertEqual(self.git(dest, "check-ignore", "-q", str(brief)).returncode, 0, "the brief is not ignored")
            self.git(dest, "add", "-A")
            tracked = self.git(dest, "ls-files").stdout.split()
            self.assertEqual([t for t in tracked if "delegation" in t], [])
            code, out, err = run("leaks", "scan", "--root", dest)
            self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
