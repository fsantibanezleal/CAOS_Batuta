"""The adversary re-check of U5 at d1bfeb6 (N-1 to N-6): every reproduction as a test, written before the fixes."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_adversary_fixes import CONFIG, THRESH, Check, project_config, thresholds_doc  # noqa: E402
from test_gate_fixtures import FEATURE, GATES, TODAY, Case, run  # noqa: E402

NO_BASE = "no base revision: thresholds and routing were not compared"


def lowered(proj):
    proj.write(THRESH, thresholds_doc({"coverage": 70}))
    return proj.commit("lower it")


class N1NoBaseRevision(Check):
    def trunk_project(self, name):
        """The target branch has a name outside the usual list; the lowering sits on a task branch."""
        proj = self.full_project()
        proj.write(THRESH, thresholds_doc({"coverage": 80}))
        base = proj.commit("thresholds at the base")
        proj.fake.branches.pop("origin/develop", None)
        proj.fake.branches[name] = base
        proj.fake.checkout("task/x", create=True)
        proj.fake.branches.pop("develop", None)
        proj.write("docs/work.md", "work\n")
        proj.commit("work")
        return proj

    def test_without_a_target_branch_the_check_says_so(self):
        proj = self.trunk_project("trunk")
        lowered(proj)
        code, out = self.check(proj)
        self.assertIn(NO_BASE, out)
        self.assertRegex(out, r"WARN[^\n]*no base revision")
        self.assertEqual(2, code, out)

    def test_the_remote_head_names_the_target_branch(self):
        proj = self.trunk_project("origin/trunk")
        proj.fake.remote_head_ref = "origin/trunk"
        lowered(proj)
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("lowered", out)
        self.assertNotIn(NO_BASE, out)

    def test_master_is_a_target_candidate(self):
        proj = self.trunk_project("master")
        lowered(proj)
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("lowered", out)

    def test_origin_master_is_a_target_candidate(self):
        proj = self.trunk_project("origin/master")
        lowered(proj)
        self.assertEqual(1, self.check(proj)[0])

    def test_an_orphan_branch_has_no_common_ancestor_and_says_so(self):
        proj = self.full_project()
        orphan = proj.orphan_commit()
        proj.fake.branches["task/x"] = orphan
        proj.fake.current = "task/x"
        code, out = self.check(proj)
        self.assertIn(NO_BASE, out)

    def test_routing_weakened_with_no_target_branch_is_not_a_silent_pass(self):
        proj = self.trunk_project("trunk")
        proj.write(CONFIG, project_config(critical=[]))
        proj.commit("routing weakened")
        for g in ("L2-decide", "L5-freeze", "L9-promote"):
            proj.evidence(g, role="adversary", model="sonnet", commit=proj.first())
        proj.commit("evidence")
        code, out = self.check(proj)
        self.assertIn(NO_BASE, out)
        self.assertNotEqual(0, code)

    def test_a_project_that_is_not_a_repository_also_says_it(self):
        proj = self.project(git=False)
        proj.status({})
        code, out = self.check(proj, "--no-commit-check")
        self.assertIn(NO_BASE, out)


class N2EachPhaseAtItsOwnGate(Check):
    def stage(self, proj, rel, text):
        proj.write(rel, text)
        proj.write("data/derived/readiness.json", (proj.root / "data/derived/readiness.json").read_text(encoding="utf-8") + "\n")
        return proj.commit(f"stage {rel}")

    def lifecycle(self, extra_commit=False, l7_at=2, tail_at=3):
        """c1 skeleton, c2 build, c3 a real provider (optionally c4 more code); evidence for each phase at its own commit."""
        proj = self.full_project()
        commits = [self.stage(proj, "src/skeleton.py", "s = 1\n"), self.stage(proj, "src/a.py", "a = 1\n"),
                   self.stage(proj, "src/c.py", "c = 1\n")]
        if extra_commit:
            commits.append(self.stage(proj, "src/d.py", "d = 1\n"))
        proj.evidence("L6-skeleton", commit=commits[0])
        proj.evidence("L7-build", commit=commits[l7_at - 1])
        tail = commits[tail_at - 1]
        for g in ("L8-integrate", "L9-promote", "L10-lessons"):
            proj.evidence(g, commit=tail)
        proj.tests_record(tail)
        proj.commit("evidence at each gate")
        return proj

    def test_an_honest_lifecycle_passes(self):
        proj = self.lifecycle()
        code, out = self.check(proj)
        self.assertEqual(0, code, out)
        self.assertNotIn("predates", out)

    def test_a_judged_path_changed_before_the_next_gate_fails_the_earlier_gate(self):
        proj = self.lifecycle(extra_commit=True, l7_at=2, tail_at=4)       # c3 changed src/c.py between L7 and L8
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertRegex(out, r"FAIL[^\n]*L7-build[^\n]*predates the change")
        self.assertNotRegex(out, r"FAIL[^\n]*L6-skeleton[^\n]*predates")

    def test_the_spec_edited_before_the_next_gate_fails_the_spec_gate(self):
        proj = self.full_project()
        proj.write(f"specs/{FEATURE}/tasks.md", "tasks\n")
        proj.commit("tasks edited")
        proj.write("docs/filler.md", "f\n")
        later = proj.commit("filler")
        for g in GATES[1:]:
            proj.evidence(g, commit=later)
        proj.commit("evidence")
        code, out = self.check(proj)
        self.assertRegex(out, r"FAIL[^\n]*L0-understand[^\n]*predates the change")

    def test_the_last_passed_gate_is_not_held_against_work_in_progress(self):
        proj = self.full_project()
        proj.status({g: "passed" for g in GATES[:8]})
        proj.commit("the build passed, L8 pending")
        proj.write("src/provider.py", "p = 1\n")
        proj.commit("integration work in progress")
        code, out = self.check(proj)
        self.assertNotIn("predates", out)

    def test_evidence_that_is_one_commit_after_the_next_is_still_caught_by_monotony(self):
        proj = self.full_project()
        later = self.stage(proj, "src/a.py", "a = 1\n")
        proj.evidence("L6-skeleton", commit=later)
        proj.commit("L6 evidence after L7")
        code, out = self.check(proj)
        self.assertIn("never go backwards", out)


class N3BaseEqualsHead(Check):
    def test_a_change_committed_on_the_target_branch_itself_is_a_warning(self):
        proj = self.full_project()
        proj.fake.branches["origin/develop"] = proj.head()
        code, out = self.check(proj)
        self.assertEqual(2, code, out)
        self.assertRegex(out, r"WARN[^\n]*base revision is HEAD")

    def test_against_must_be_an_ancestor_of_head(self):
        proj = self.full_project()
        orphan = proj.orphan_commit()
        code, out = self.check(proj, "--against", orphan)
        self.assertEqual(1, code, out)
        self.assertIn("not an ancestor of HEAD", out)

    def test_against_an_ancestor_is_accepted(self):
        proj = self.full_project()
        code, out = self.check(proj, "--against", proj.first())
        self.assertEqual(0, code, out)

    def test_ci_passing_the_pull_request_base_is_documented(self):
        root = Path(__file__).resolve().parents[1]
        text = " ".join((root / "changes/u5-plugin-readme.md").read_text(encoding="utf-8").split())
        self.assertIn("CI passes the pull-request base explicitly with --against", text)


class N4CoordinationFolder(Case):
    def setUp(self):
        super().setUp()
        from batuta_lib.areas import gate
        self.gate = gate

    def test_the_coordination_folder_does_not_age_the_release_evidence(self):
        proj = self.full_project()
        proj.status({g: "passed" for g in GATES[:10]})
        proj.commit("L10 pending")
        proj.write(".batuta/gate-stop.state", "key\n")
        code, out = run("gate", "check", FEATURE, "--root", str(proj.root), "--today", TODAY)
        self.assertEqual(0, code, out)
        self.assertNotIn("changed since", out)

    def test_the_second_stop_without_the_flag_is_allowed_although_the_state_file_is_now_untracked(self):
        proj = self.full_project()
        proj.status({g: "passed" for g in GATES[:10]})
        proj.commit("L10 pending")
        proj.remove(f"specs/{FEATURE}/evidence/L7-build.md")
        payload = {"hook_event_name": "Stop", "cwd": str(proj.root), "session_id": "s9"}
        first = self.gate.HOOKS["gate-stop"](payload)
        self.assertEqual("block", first["output"]["decision"])
        proj.fake.pending.add(".batuta/gate-stop.state")           # what git status shows after the first call
        second = self.gate.HOOKS["gate-stop"](payload)
        self.assertIsNone(second["output"])

    def test_a_missing_git_allows_the_stop_and_says_why(self):
        proj = self.project(git=False)
        proj.status({})
        result = self.gate.HOOKS["gate-stop"]({"hook_event_name": "Stop", "cwd": str(proj.root)})
        self.assertIsNone(result["output"])
        self.assertEqual(0, result["exit_code"])
        self.assertIn("git", result["message"])


class N5RecordedByHand(Case):
    def command(self, proj, *extra):
        return run("gate", "tests-record", "--root", str(proj.root), "--today", TODAY, *extra)

    def clean(self):
        proj = self.project()
        proj.catalog()
        proj.commit("catalog")
        return proj

    def test_a_pass_cannot_be_typed_in(self):
        proj = self.clean()
        code, out = self.command(proj, "--result", "tests/test_widget_producer.py=pass", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("--run", out)
        self.assertFalse((proj.root / "docs/design/contract-tests.json").exists())

    def test_a_fail_or_a_skip_can_be_recorded_by_hand(self):
        proj = self.clean()
        code, out = self.command(proj, "--result", "tests/test_widget_producer.py=fail", "--result", "tests/test_widget_consumer.py=skip", "--apply")
        self.assertEqual(0, code, out)
        doc = json.loads((proj.root / "docs/design/contract-tests.json").read_text(encoding="utf-8"))
        self.assertEqual({"tests/test_widget_producer.py": "fail", "tests/test_widget_consumer.py": "skip"}, doc["results"])

    def test_run_still_records_a_pass(self):
        proj = self.clean()
        proj.write("tests/test_widget_producer.py", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
        proj.commit("a real test")
        code, out = self.command(proj, "--run", "--apply")
        self.assertEqual(0, code, out)
        doc = json.loads((proj.root / "docs/design/contract-tests.json").read_text(encoding="utf-8"))
        self.assertEqual("pass", doc["results"]["tests/test_widget_producer.py"])

    def test_a_hand_result_does_not_override_a_run_pass(self):
        proj = self.clean()
        proj.write("tests/test_widget_producer.py", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
        proj.commit("a real test")
        code, out = self.command(proj, "--run", "--result", "tests/test_widget_producer.py=fail", "--apply")
        self.assertEqual(0, code, out)
        doc = json.loads((proj.root / "docs/design/contract-tests.json").read_text(encoding="utf-8"))
        self.assertEqual("fail", doc["results"]["tests/test_widget_producer.py"])      # a failure may always be recorded


class N6WaivedLoweringInTwoSteps(Check):
    def entries(self, *pairs):
        return [{"date": TODAY, "name": "coverage", "from": a, "to": b, "reason": "calibrated"} for a, b in pairs]

    def lowered_project(self, history, final, waiver=True):
        proj = self.full_project()
        proj.write(THRESH, thresholds_doc({"coverage": 80}))
        base = proj.commit("thresholds at the base")
        self.on_branch(proj, base)
        proj.write(THRESH, thresholds_doc({"coverage": 90}, history[:1]))
        proj.commit("raise")
        proj.write(THRESH, thresholds_doc({"coverage": final}, history))
        if waiver:
            proj.status({g: "passed" for g in GATES},
                        waivers=[{"gate": "L9-promote", "reason": "calibration was wrong", "by": "alex", "date": TODAY}])
        proj.commit("lower")
        return proj

    def test_a_chain_from_the_base_value_with_a_waiver_passes(self):
        proj = self.lowered_project(self.entries((80, 90), (90, 60)), 60)
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_the_same_chain_without_a_waiver_fails(self):
        proj = self.lowered_project(self.entries((80, 90), (90, 60)), 60, waiver=False)
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("waiver", out)

    def test_a_chain_that_does_not_reach_the_final_value_fails(self):
        proj = self.lowered_project(self.entries((80, 90), (85, 60)), 60)
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("lowered", out)

    def test_a_chain_that_does_not_start_at_the_base_value_fails(self):
        proj = self.lowered_project(self.entries((50, 90), (90, 60)), 60)
        self.assertEqual(1, self.check(proj)[0])


if __name__ == "__main__":
    unittest.main()
