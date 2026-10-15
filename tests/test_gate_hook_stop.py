"""The Stop handler of the gate area: block once, never loop, never block an unrelated session; and its CLI twin."""
import datetime
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import CONTRACTS, FEATURE, GATES, Case, run  # noqa: E402

from batuta_lib import config  # noqa: E402
from batuta_lib import contract as core  # noqa: E402


def stop_payload(cwd, active=False):
    payload = {"hook_event_name": "Stop", "cwd": str(cwd), "session_id": "s-1", "stop_hook_active": active}
    return payload


def handler_result_errors(result):
    sp = core.find_schema(config.contracts_dir(), "C31")
    return core.validate_instance("C31", result, core.load_schema(sp))


class StopHook(Case):
    def setUp(self):
        super().setUp()
        from batuta_lib.areas import gate
        self.handler = gate.HOOKS["gate-stop"]
        self.gate_area = gate
        self.today = datetime.date.today().isoformat()

    def failing(self):
        """A compliant project whose L7-build evidence was deleted (uncommitted): a failing gate in a changed unit."""
        proj = self.full_project()
        proj.remove(f"specs/{FEATURE}/evidence/L7-build.md")
        return proj

    def status_text(self, proj):
        return (proj.root / "specs" / FEATURE / "status.md").read_text(encoding="utf-8")

    def test_the_payload_fixture_shape_is_a_c16_stop_input(self):
        sp = core.find_schema(CONTRACTS, "C16")
        self.assertEqual([], core.validate_instance("C16", stop_payload(self.tmp), core.load_schema(sp)))

    def test_first_attempt_blocks_with_the_failing_gate(self):
        proj = self.failing()
        result = self.handler(stop_payload(proj.root))
        self.assertEqual([], handler_result_errors(result))
        self.assertEqual(0, result["exit_code"])
        self.assertEqual("block", result["output"]["decision"])
        self.assertIn("L7-build", result["output"]["reason"])
        self.assertIn(FEATURE, result["output"]["reason"])
        self.assertNotIn("UNVERIFIED", self.status_text(proj))

    def test_second_attempt_logs_unverified_and_allows(self):
        proj = self.failing()
        result = self.handler(stop_payload(proj.root, active=True))
        self.assertEqual([], handler_result_errors(result))
        self.assertEqual(0, result["exit_code"])
        self.assertIsNone(result["output"])
        text = self.status_text(proj)
        self.assertIn(f"- {self.today} UNVERIFIED:", text)
        from batuta_lib import gate_model
        self.assertEqual([], gate_model.status_errors(text))
        self.assertIn("Body of the status file.", text)

    def test_the_unverified_line_is_written_once(self):
        proj = self.failing()
        self.handler(stop_payload(proj.root, active=True))
        once = self.status_text(proj)
        self.handler(stop_payload(proj.root, active=True))
        self.assertEqual(once, self.status_text(proj))
        self.assertEqual(1, once.count("UNVERIFIED"))

    def test_block_then_allow_never_loops(self):
        proj = self.failing()
        first = self.handler(stop_payload(proj.root))
        second = self.handler(stop_payload(proj.root, active=True))
        self.assertEqual("block", first["output"]["decision"])
        self.assertIsNone(second["output"])

    def test_a_unit_without_uncommitted_changes_is_never_blocked(self):
        proj = self.failing()
        proj.commit("commit the failing state")
        result = self.handler(stop_payload(proj.root))
        self.assertIsNone(result["output"])
        self.assertEqual(0, result["exit_code"])
        result = self.handler(stop_payload(proj.root, active=True))
        self.assertNotIn("UNVERIFIED", self.status_text(proj))

    def test_a_healthy_unit_with_uncommitted_changes_is_allowed(self):
        proj = self.full_project()
        proj.write(f"specs/{FEATURE}/notes.md", "uncommitted notes\n")
        self.assertIsNone(self.handler(stop_payload(proj.root))["output"])

    def test_a_failing_unit_elsewhere_does_not_block_a_session_changing_another_unit(self):
        proj = self.failing()
        proj.commit("commit the failing unit")
        proj.write("specs/002-other/status.md",
                   "---\nfeature: 002-other\nphase: L0-understand\ngates:\n  L0-understand: pending\n---\n\n## Notes\n\nx\n")
        proj.write("specs/002-other/notes.md", "changed\n")
        self.assertIsNone(self.handler(stop_payload(proj.root))["output"])

    def test_a_folder_without_specs_or_git_is_never_blocked(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertIsNone(self.handler(stop_payload(empty))["output"])
        plain = self.project(git=False)
        plain.evidence("L0-understand")
        plain.status({"L0-understand": "passed"})
        self.assertIsNone(self.handler(stop_payload(plain.root))["output"])

    def test_the_scope_key_ties_source_changes_to_their_unit(self):
        proj = self.failing()
        text = self.status_text(proj).replace("blocked: false", "blocked: false\nscope: [src]")
        proj.write(f"specs/{FEATURE}/status.md", text)
        proj.commit("scope and failing state")
        self.assertIsNone(self.handler(stop_payload(proj.root))["output"])
        proj.write("src/code.py", "x = 1\n")
        result = self.handler(stop_payload(proj.root))
        self.assertEqual("block", result["output"]["decision"])

    def test_a_failed_gate_state_blocks(self):
        proj = self.full_project()
        proj.status({g: "passed" for g in GATES[:7]} | {"L7-build": "failed"})
        result = self.handler(stop_payload(proj.root))
        self.assertEqual("block", result["output"]["decision"])

    def test_the_handler_does_not_raise_on_a_corrupt_status_file(self):
        proj = self.full_project()
        proj.write(f"specs/{FEATURE}/status.md", "not front matter at all\n")
        result = self.handler(stop_payload(proj.root))
        self.assertEqual([], handler_result_errors(result))

    def test_a_missing_payload_cwd_falls_back_to_the_working_folder_and_allows(self):
        result = self.handler({"hook_event_name": "Stop"})
        self.assertEqual(0, result["exit_code"])

    def test_the_handler_is_discoverable_by_the_launcher_rule(self):
        found, problems = core.discover_hook_ids(Path(self.gate_area.__file__).parent)
        self.assertEqual([], problems)
        self.assertEqual(["gate"], found["gate-stop"])


class StopHookCli(Case):
    def test_cli_twin_blocks_once_then_logs_and_allows(self):
        proj = self.full_project()
        proj.remove(f"specs/{FEATURE}/evidence/L7-build.md")
        first = json.dumps({"hook_event_name": "Stop", "cwd": str(proj.root), "stop_hook_active": False})
        code, out = run("gate", "hook-stop", stdin=first)
        self.assertEqual(0, code, out)
        self.assertEqual("block", json.loads(out)["decision"])
        second = json.dumps({"hook_event_name": "Stop", "cwd": str(proj.root), "stop_hook_active": True})
        code, out = run("gate", "hook-stop", stdin=second)
        self.assertEqual(0, code, out)
        self.assertEqual("", out.strip())
        self.assertIn("UNVERIFIED", (proj.root / "specs" / FEATURE / "status.md").read_text(encoding="utf-8"))

    def test_cli_twin_allows_on_unreadable_input(self):
        code, out = run("gate", "hook-stop", stdin="not json")
        self.assertEqual(0, code, out)
        self.assertEqual("", out.strip())
        code, out = run("gate", "hook-stop", stdin="")
        self.assertEqual(0, code, out)


if __name__ == "__main__":
    unittest.main()
