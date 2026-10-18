"""`doctor`: the device check plus probes (Python, Git Bash on Windows, Node, the `claude` CLI, the plugin's `python`
option, configuration, roots, and in a project the test step of the `batuta-gates` workflow against `tdd.test_command`).
Each result is OK, WARN or FAIL with the exact fix; under five seconds; no network."""
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import FIXTURE_VARS, World, make_repo  # noqa: E402

from batuta_lib.areas import init  # noqa: E402


def lines(out, tag):
    return [ln for ln in out.splitlines() if ln.startswith(tag + " ")]


class DoctorBase(World):
    def doctor(self, *extra, which=None, platform=None, python_version=None, env=None):
        """Run `init doctor` in-process with the probes controlled: `which` maps a command to a path or None."""
        table = {"node": "/fake/node", "claude": "/fake/claude", "bash": "/fake/bash", "git": "/fake/git", "python3": "/fake/python3"}
        table.update(which or {})
        patches = [mock.patch.object(init, "_which", lambda name: table.get(name)),
                   mock.patch.object(init, "_node_version", lambda path: "v22.1.0" if path else None)]
        if platform:
            patches.append(mock.patch.object(init, "_platform", lambda: platform))
        if python_version:
            patches.append(mock.patch.object(init, "_python_version", lambda: python_version))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return self.cli("init", "doctor", "--home", str(self.home), *extra, env=env)


class DeviceDoctor(DoctorBase):
    def test_a_fresh_device_fails_with_the_exact_fix(self):
        code, out, _ = self.doctor("--channel", "device")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL .*device copy")
        self.assertIn("init user --apply", out)

    def test_after_init_user_the_device_channel_is_ok(self):
        self.init_user()
        code, out, err = self.doctor("--channel", "device")
        self.assertEqual(code, 0, out + err)
        self.assertRegex(out, r"OK .*Python 3\.\d+")
        self.assertFalse(lines(out, "FAIL"))

    def test_python_below_3_10_fails_and_names_the_fix(self):
        code, out, _ = self.doctor("--channel", "device", python_version=(3, 9, 7))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL .*Python 3\.9\.7.*3\.10")
        self.assertIn("BATUTA_PYTHON", out)

    def test_node_absent_is_a_warning_that_says_only_the_npx_channel_needs_it(self):
        self.init_user()
        code, out, _ = self.doctor("--channel", "device", which={"node": None})
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"WARN .*Node.*only the npx channel")

    def test_claude_cli_absent_leaves_the_plugin_channel_unchecked_as_a_warning(self):
        self.init_user()
        code, out, _ = self.doctor("--channel", "device", which={"claude": None})
        self.assertRegex(out, r"WARN .*claude.*plugin channel.*unchecked")
        self.assertFalse(lines(out, "FAIL"))

    def test_git_bash_absent_on_windows_fails_the_plugin_channel_and_passes_the_device_channel(self):
        self.init_user()
        env = {"ProgramFiles": str(self.root / "nowhere"), "ProgramFiles(x86)": str(self.root / "nowhere"),
               "LOCALAPPDATA": str(self.root / "nowhere")}
        code, out, _ = self.doctor("--channel", "plugin", which={"bash": None}, platform="win32", env=env)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL .*Git Bash.*https://git-scm\.com")
        code, out, _ = self.doctor("--channel", "device", which={"bash": None}, platform="win32", env=env)
        self.assertFalse([ln for ln in lines(out, "FAIL") if "Git Bash" in ln], out)

    def test_git_bash_found_in_a_standard_folder_passes(self):
        self.init_user()
        base = self.root / "pf"
        (base / "Git" / "bin").mkdir(parents=True)
        (base / "Git" / "bin" / "bash.exe").write_text("x", encoding="utf-8")
        env = {"ProgramFiles": str(base), "ProgramFiles(x86)": str(self.root / "nowhere"),
               "LOCALAPPDATA": str(self.root / "nowhere")}
        code, out, _ = self.doctor("--channel", "plugin", which={"bash": None}, platform="win32", env=env)
        self.assertRegex(out, r"OK .*Git Bash")

    def test_the_plugin_python_option_from_the_environment_must_be_python_3_10_or_newer(self):
        self.init_user()
        code, out, _ = self.doctor("--channel", "plugin", env={"CLAUDE_PLUGIN_OPTION_PYTHON": sys.executable})
        self.assertRegex(out, r"OK .*plugin option python")
        code, out, _ = self.doctor("--channel", "plugin", env={"CLAUDE_PLUGIN_OPTION_PYTHON": str(self.root / "no-python")})
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL .*plugin option python.*no-python")

    def test_the_plugin_python_option_is_read_from_the_users_settings(self):
        self.init_user()
        path = self.home / ".claude" / "settings.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["pluginConfigs"] = {"batuta@batuta": {"options": {"python": str(self.root / "gone")}}}
        path.write_text(json.dumps(doc), encoding="utf-8")
        code, out, _ = self.doctor("--channel", "plugin")
        self.assertRegex(out, r"FAIL .*plugin option python.*gone")

    def test_an_unset_plugin_option_is_reported_as_not_set(self):
        self.init_user()
        code, out, _ = self.doctor("--channel", "plugin")
        self.assertRegex(out, r"(OK|SKIP) .*plugin option python.*not set")

    def test_an_unset_plugin_option_on_windows_warns_with_the_exact_fix(self):
        self.init_user()
        code, out, _ = self.doctor("--channel", "plugin", platform="win32")
        self.assertRegex(out, r"WARN .*plugin option python.*not set.*default interpreter.*fix: set the plugin option python")
        self.assertIn("py", out.split("fix:", 1)[1])
        self.assertNotRegex(out, r"OK .*plugin option python")

    def test_a_plugin_option_below_python_3_10_fails(self):
        self.init_user()
        with mock.patch.object(init, "_python_command_version", lambda value: "3.9"):
            code, out, _ = self.doctor("--channel", "plugin", env={"CLAUDE_PLUGIN_OPTION_PYTHON": "py -3.9"})
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL .*plugin option python.*3\.9.*older than 3\.10")

    def test_an_invalid_configuration_fails(self):
        self.init_user()
        (self.bh / "batuta.json").write_text('{"contract_version": "1.0"}', encoding="utf-8")
        code, out, _ = self.doctor("--channel", "device")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL .*configuration")

    def test_a_root_that_is_a_file_is_not_writable(self):
        self.init_user()
        blocker = self.root / "data-is-a-file"
        blocker.write_text("x", encoding="utf-8")
        code, out, _ = self.doctor("--channel", "device", env={"BATUTA_DATA": str(blocker)})
        self.assertRegex(out, r"FAIL .*root 'data'")

    def test_roots_that_do_not_exist_yet_but_can_be_created_are_ok(self):
        self.init_user()
        code, out, _ = self.doctor("--channel", "device")
        self.assertRegex(out, r"OK .*roots")

    def test_doctor_is_read_only_and_fast(self):
        self.init_user()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        start = time.monotonic()
        self.doctor("--channel", "device")
        self.assertLess(time.monotonic() - start, 5.0)
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_json_output_is_the_c20_object(self):
        code, out, _ = self.cli("init", "doctor", "--home", str(self.home), "--channel", "device", "--json")
        doc = json.loads(out)
        self.assertEqual((doc["area"], doc["verb"]), ("init", "doctor"))


class ProjectDoctor(DoctorBase):
    def setUp(self):
        super().setUp()
        make_repo(self.project)
        self.init_user()
        self.init_project()

    def workflow(self):
        return self.project / ".github" / "workflows" / "batuta-gates.yml"

    def test_a_fresh_project_passes_the_workflow_check(self):
        code, out, err = self.doctor("--channel", "device", "--project", str(self.project))
        self.assertEqual(code, 0, out + err)
        self.assertRegex(out, r"OK .*batuta-gates.*test step.*tdd\.test_command")

    def test_a_different_test_step_fails_naming_both_commands(self):
        text = self.workflow().read_text(encoding="utf-8")
        self.workflow().write_text(text.replace(FIXTURE_VARS["test_command"], "pytest -q"), encoding="utf-8")
        code, out, _ = self.doctor("--channel", "device", "--project", str(self.project))
        self.assertEqual(code, 1)
        fail = " ".join(lines(out, "FAIL"))
        self.assertIn("pytest -q", fail)
        self.assertIn(FIXTURE_VARS["test_command"], fail)

    def test_a_missing_test_step_fails(self):
        text = self.workflow().read_text(encoding="utf-8").replace("id: tests", "id: other")
        self.workflow().write_text(text, encoding="utf-8")
        code, out, _ = self.doctor("--channel", "device", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL .*no test step")

    def test_a_missing_workflow_fails(self):
        self.workflow().unlink()
        code, out, _ = self.doctor("--channel", "device", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL .*batuta-gates\.yml.*not found")

    def test_a_changed_configured_command_fails_the_comparison(self):
        path = self.project / ".batuta" / "batuta.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["tdd"]["test_command"] = "python -m unittest -v"
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        code, out, _ = self.doctor("--channel", "device", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("python -m unittest -v", " ".join(lines(out, "FAIL")))

    def test_a_project_without_a_configured_command_is_compared_with_the_default(self):
        path = self.project / ".batuta" / "batuta.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        del doc["tdd"]
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        code, out, _ = self.doctor("--channel", "device", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("-v", " ".join(lines(out, "FAIL")))

    def test_a_folder_that_is_not_a_batuta_project_is_skipped(self):
        other = self.root / "plain"
        other.mkdir()
        code, out, _ = self.doctor("--channel", "device", "--project", str(other))
        self.assertRegex(out, r"SKIP .*not a Batuta project")


if __name__ == "__main__":
    unittest.main()
