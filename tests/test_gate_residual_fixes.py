"""The minor residuals of the adversary re-check at bcfdefe (M-1 to M-3), as tests written before the fixes."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_adversary_fixes import Check  # noqa: E402
from test_gate_fixtures import FEATURE, GATES, run  # noqa: E402

from batuta_lib import gate_model  # noqa: E402


class M1CoordinationFolderDoesNotAgeReadiness(Check):
    def test_a_commit_that_touches_only_the_coordination_folder_keeps_the_readiness_current(self):
        proj = self.project()
        proj.catalog()
        proj.readiness()
        head = proj.commit("skeleton")
        record = proj.tests_record(head)
        proj.write(".batuta/note.md", "coordination\n")
        proj.commit("coordination only")
        code, out = run("skeleton", "check", "--root", str(proj.root), "--tests-record", str(record))
        self.assertEqual(0, code, out)
        self.assertNotIn("behind", out)

    def test_a_code_commit_still_ages_it(self):
        proj = self.project()
        proj.catalog()
        proj.readiness()
        head = proj.commit("skeleton")
        record = proj.tests_record(head)
        proj.write(".batuta/note.md", "coordination\n")
        proj.write("src/a.py", "x = 1\n")
        proj.commit("code and coordination")
        code, out = run("skeleton", "check", "--root", str(proj.root), "--tests-record", str(record))
        self.assertEqual(1, code, out)
        self.assertIn("behind", out)


class M2LastPassedGate(Check):
    def stopped_at_l7(self):
        proj = self.full_project()
        proj.status({g: "passed" for g in GATES[:8]})
        proj.commit("the build passed, L8 pending")
        return proj

    def test_unreviewed_code_after_the_last_passed_gate_is_a_warning(self):
        proj = self.stopped_at_l7()
        proj.write("src/provider.py", "p = 1\n")
        sha = proj.commit("integration work after the L7 evidence")
        code, out = self.check(proj)
        self.assertEqual(2, code, out)
        self.assertRegex(out, r"WARN[^\n]*L7-build[^\n]*has not been reviewed")
        self.assertIn(sha[:12], out)
        self.assertNotIn("predates", out)

    def test_no_change_after_the_last_passed_gate_stays_green(self):
        code, out = self.check(self.stopped_at_l7())
        self.assertEqual(0, code, out)

    def test_a_change_to_a_path_the_gate_does_not_judge_stays_green(self):
        proj = self.stopped_at_l7()
        proj.write("docs/notes.md", "notes\n")
        proj.commit("documentation")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_the_stop_handler_does_not_block_on_the_warning(self):
        from batuta_lib.areas import gate
        proj = self.stopped_at_l7()
        proj.write("src/provider.py", "p = 1\n")
        proj.commit("integration work")
        proj.write(f"specs/{FEATURE}/notes.md", "uncommitted\n")
        result = gate.HOOKS["gate-stop"]({"hook_event_name": "Stop", "cwd": str(proj.root)})
        self.assertIsNone(result["output"])


class M3LogLimit(Check):
    def long_history(self):
        proj = self.full_project()
        for i in range(4):
            proj.write(f"docs/filler{i}.md", "f\n")
            proj.commit(f"filler {i}")
        tip = proj.head()
        for g in ("L9-promote", "L10-lessons"):
            proj.evidence(g, commit=tip)
        proj.commit("late evidence")
        return proj

    def test_a_history_longer_than_the_limit_is_said_not_silently_missed(self):
        proj = self.long_history()
        with mock.patch.object(gate_model, "LOG_LIMIT", 2):
            code, out = self.check(proj)
        self.assertRegex(out, r"WARN[^\n]*not compared[^\n]*limit of 2")
        self.assertEqual(1 if "FAIL" in out else 2, code, out)

    def test_within_the_limit_nothing_is_said(self):
        proj = self.long_history()
        code, out = self.check(proj)
        self.assertNotIn("not compared", out)

    def test_the_warning_is_given_once(self):
        proj = self.long_history()
        with mock.patch.object(gate_model, "LOG_LIMIT", 2):
            code, out = self.check(proj)
        self.assertEqual(1, out.count("not compared"), out)


if __name__ == "__main__":
    unittest.main()
