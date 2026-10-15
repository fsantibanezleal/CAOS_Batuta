"""The adversary check of U5 (F-1 to F-11): every reproduction as a test, written before the fixes.

Main-session decisions behind them: settings that can weaken a gate (the thresholds, `gates.critical` and the model
routing) are read from the base revision of the checked range, never from the change under review; evidence must not
predate the newest change to a path its gate judges; the Stop handler keeps its own once-per-failure state.
"""
import datetime
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import (CONTRACTS, FEATURE, GATES, TODAY, Case, catalog_row, evidence_text, readiness_entry,  # noqa: E402
                                run)

from batuta_lib import config  # noqa: E402
from batuta_lib import contract as core  # noqa: E402

THRESH = "specs/000-foundation/thresholds.json"
CONFIG = ".batuta/batuta.json"


def thresholds_doc(values, history=()):
    return json.dumps({"contract_version": "1.0", "values": values, "history": list(history)}, indent=2) + "\n"


def project_config(**gates):
    design = json.loads((CONTRACTS / "fixtures" / "C01" / "valid-design-example.json").read_text(encoding="utf-8"))
    design = {k: v for k, v in design.items() if not k.startswith("_")}
    design["gates"].update(gates)
    return json.dumps(design, indent=2) + "\n"


class Check(Case):
    def check(self, proj, *extra):
        return run("gate", "check", proj.feature, "--root", str(proj.root), "--today", TODAY, *extra)

    def on_branch(self, proj, target_commit):
        """Leave the target branch at `target_commit` (as origin/develop) and work on a task branch from here."""
        proj.fake.branches["origin/develop"] = target_commit
        proj.fake.checkout("task/x", create=True)


class F1ThresholdsInGateCheck(Check):
    def with_baseline(self, value=80):
        proj = self.full_project()
        proj.write(THRESH, thresholds_doc({"coverage": value}))
        base = proj.commit("thresholds at the base")
        self.on_branch(proj, base)
        return proj

    def test_a_threshold_lowered_in_the_range_without_a_history_entry_fails_gate_check(self):
        proj = self.with_baseline()
        proj.write(THRESH, thresholds_doc({"coverage": 70}))
        proj.commit("lower it, history untouched")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("lowered", out)
        self.assertIn("coverage", out)

    def test_a_lowering_with_the_history_rewritten_to_match_still_fails(self):
        proj = self.with_baseline()
        rewritten = [{"date": TODAY, "name": "coverage", "from": 50, "to": 70, "reason": "x"}]
        proj.write(THRESH, thresholds_doc({"coverage": 70}, rewritten))
        proj.commit("lower it and rewrite the history")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_a_lowering_without_a_human_waiver_fails_and_with_one_passes(self):
        proj = self.with_baseline()
        entry = {"date": TODAY, "name": "coverage", "from": 80, "to": 70, "reason": "the suite changed"}
        proj.write(THRESH, thresholds_doc({"coverage": 70}, [entry]))
        proj.commit("lower it with its history entry")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("waiver", out)
        proj.status({g: "passed" for g in GATES},
                    waivers=[{"gate": "L9-promote", "reason": "calibration was wrong", "by": "alex", "date": TODAY}])
        proj.commit("a human waiver of the same date")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_a_waiver_written_by_an_agent_does_not_cover_a_lowering(self):
        proj = self.with_baseline()
        entry = {"date": TODAY, "name": "coverage", "from": 80, "to": 70, "reason": "x"}
        proj.write(THRESH, thresholds_doc({"coverage": 70}, [entry]))
        proj.status({g: "passed" for g in GATES},
                    waivers=[{"gate": "L9-promote", "reason": "skip", "by": "implementer", "date": TODAY}])
        proj.commit("agent waiver")
        self.assertEqual(1, self.check(proj)[0])

    def test_a_raise_in_the_range_passes(self):
        proj = self.with_baseline()
        entry = {"date": TODAY, "name": "coverage", "from": 80, "to": 85, "reason": "measured 87"}
        proj.write(THRESH, thresholds_doc({"coverage": 85}, [entry]))
        proj.commit("raise it")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_an_uncommitted_lowering_is_found_against_the_head(self):
        proj = self.full_project()
        proj.write(THRESH, thresholds_doc({"coverage": 80}))
        proj.commit("thresholds")
        proj.fake.branches["origin/develop"] = proj.head()     # HEAD is the target: the range is empty
        proj.write(THRESH, thresholds_doc({"coverage": 70}))
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("lowered", out)

    def test_an_explicit_base_revision_is_used(self):
        proj = self.full_project()
        proj.write(THRESH, thresholds_doc({"coverage": 80}))
        base = proj.commit("thresholds")
        proj.write(THRESH, thresholds_doc({"coverage": 70}))
        proj.commit("lowered on the same branch")
        code, out = self.check(proj, "--against", base)
        self.assertEqual(1, code, out)
        self.assertEqual(1, self.check(proj, "--against", "no-such-revision")[0])

    def test_thresholds_new_in_the_range_are_fine(self):
        proj = self.full_project()
        self.on_branch(proj, proj.head())
        proj.write(THRESH, thresholds_doc({"coverage": 70}))
        proj.commit("the first thresholds")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)


class F2EvidencePredatesTheChange(Check):
    """A gate's evidence must not be older than the changes to its judged paths made before the next passed gate's evidence."""

    def rewrite(self, proj, gates, commit):
        for g in gates:
            proj.evidence(g, commit=commit)

    def change_then_review(self, proj, rel, text, later):
        """One commit changes `rel`, a second one follows, and the evidence of `later` gates names the second."""
        proj.write(rel, text)
        proj.commit(f"change {rel}")
        proj.write("docs/filler.md", "filler\n")
        second = proj.commit("filler")
        self.rewrite(proj, later, second)
        proj.commit("evidence after the change")

    def test_build_evidence_naming_the_spec_era_commit_fails_when_the_next_gate_reviews_later_code(self):
        proj = self.full_project()
        proj.write("src/a.py", "x = 1\n")
        proj.commit("the build, first commit")
        proj.write("src/b.py", "y = 1\n")
        head = proj.commit("the build, second commit")
        self.rewrite(proj, ("L9-promote", "L10-lessons"), head)
        proj.tests_record(head)
        proj.commit("evidence at the head")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertRegex(out, r"FAIL[^\n]*L8-integrate[^\n]*predates the change")     # the gate whose next evidence jumps over the code
        self.assertNotRegex(out, r"FAIL[^\n]*L7-build[^\n]*predates")                # L7 and L8 name the same commit: nothing between them

    def test_the_spec_gates_follow_the_spec_folder(self):
        proj = self.full_project()
        self.change_then_review(proj, f"specs/{FEATURE}/tasks.md", "tasks\n", GATES[1:])
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertRegex(out, r"FAIL[^\n]*L0-understand[^\n]*predates the change")

    def test_the_contract_gates_follow_the_contracts(self):
        proj = self.full_project()
        self.change_then_review(proj, "docs/contracts/examples/more.json", "{}\n", GATES[4:])
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertRegex(out, r"FAIL[^\n]*L3-contracts[^\n]*predates the change")

    def test_the_decision_gate_follows_the_decisions(self):
        proj = self.full_project()
        self.change_then_review(proj, "docs/decisions/ADR-0001-x.md", "adr\n", GATES[3:])
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertRegex(out, r"FAIL[^\n]*L2-decide[^\n]*predates the change")

    def test_evidence_naming_the_commit_of_the_change_passes(self):
        proj = self.full_project()
        proj.write("src/a.py", "x = 1\n")
        proj.commit("the build")
        proj.write("data/derived/readiness.json", (proj.root / "data/derived/readiness.json").read_text(encoding="utf-8") + "\n")
        ready = proj.commit("readiness after the build")
        proj.tests_record(ready)
        self.rewrite(proj, ("L6-skeleton", "L7-build", "L8-integrate", "L9-promote", "L10-lessons"), ready)
        proj.commit("evidence at the newest change")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_documentation_and_other_units_do_not_age_the_build_evidence(self):
        proj = self.full_project()
        proj.write("docs/notes.md", "notes\n")
        proj.write("README.md", "readme\n")
        proj.commit("documentation")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_gate_status_refuses_to_pass_a_gate_on_evidence_that_predates_the_code(self):
        proj = self.project()
        proj.spec()
        base = proj.commit("base")
        for g in GATES[:7]:
            proj.evidence(g, commit=base)
        proj.status({g: "passed" for g in GATES[:7]})
        proj.write("src/a.py", "x = 1\n")
        proj.commit("the build")
        proj.evidence("L7-build", commit=base)
        code, out = run("gate", "status", FEATURE, "--root", str(proj.root), "--set", "L7-build=passed", "--apply", "--today", TODAY)
        self.assertEqual(1, code, out)
        self.assertIn("predates the change", out)

class F3RoutingFromTheBase(Check):
    def routed_project(self):
        proj = self.full_project()
        proj.write(CONFIG, project_config())
        base = proj.commit("the configuration at the base")
        self.on_branch(proj, base)
        proj.write("docs/work.md", "work\n")
        proj.commit("work on the branch")
        return proj, base

    def test_weakening_the_critical_gates_in_the_range_does_not_weaken_the_check(self):
        proj, base = self.routed_project()
        proj.write(CONFIG, project_config(critical=[]))
        weakening = proj.commit("critical gates removed")
        for g in ("L2-decide", "L5-freeze", "L9-promote"):
            proj.evidence(g, role="adversary", model="sonnet", commit=base)
        proj.commit("evidence as the routine adversary")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("routes to model 'opus'", out)
        self.assertIn(weakening[:12], out)
        self.assertRegex(out, r"WARN[^\n]*gates")

    def test_a_change_to_the_routing_that_conflicts_with_nothing_is_a_warning_naming_the_commit(self):
        proj, base = self.routed_project()
        proj.write(CONFIG, project_config(critical_units=["other-unit"]))
        change = proj.commit("a critical unit added")
        code, out = self.check(proj)
        self.assertEqual(2, code, out)
        self.assertRegex(out, r"WARN[^\n]*gates")
        self.assertIn(change[:12], out)

    def test_an_unchanged_routing_is_silent(self):
        proj, base = self.routed_project()
        code, out = self.check(proj)
        self.assertEqual(0, code, out)
        self.assertNotIn("WARN", out)

    def test_changes_outside_the_gates_block_are_not_reported(self):
        proj, base = self.routed_project()
        text = json.loads(project_config())
        text["budgets"]["memory_index_lines"] = 61
        proj.write(CONFIG, json.dumps(text, indent=2) + "\n")
        proj.commit("budget changed")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_without_a_base_configuration_the_defaults_route(self):
        proj = self.full_project()
        self.on_branch(proj, proj.head())
        proj.write(CONFIG, project_config(critical=[]))
        proj.commit("routing weakened with no configuration at the base")
        for g in ("L2-decide", "L5-freeze", "L9-promote"):
            proj.evidence(g, role="adversary", model="sonnet", commit=proj.first())
        proj.commit("evidence")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)


class F4AgentToolScope(unittest.TestCase):
    def test_the_agent_definition_says_the_guards_enforce_the_tool_scope(self):
        root = Path(__file__).resolve().parents[1]
        text = " ".join((root / "plugins/batuta/agents/adversary.md").read_text(encoding="utf-8").split())
        self.assertIn("front matter cannot scope Write or Bash to a path", text)
        self.assertIn("enforced by the guards, not by this definition", text)
        readme = (root / "changes/u5-plugin-readme.md").read_text(encoding="utf-8")
        self.assertIn("guards unit", readme)
        self.assertIn("specs/*/evidence/*.md", readme)


class F5StopScope(Case):
    def setUp(self):
        super().setUp()
        from batuta_lib.areas import gate
        self.handler = gate.HOOKS["gate-stop"]

    def payload(self, proj, active=False):
        return {"hook_event_name": "Stop", "cwd": str(proj.root), "session_id": "s", "stop_hook_active": active}

    def failing_unit(self):
        proj = self.full_project()
        proj.remove(f"specs/{FEATURE}/evidence/L7-build.md")
        proj.commit("a failing unit, committed")
        return proj

    def test_the_write_scope_of_the_units_tasks_in_the_sizing_scopes_the_unit(self):
        proj = self.failing_unit()
        proj.write(".batuta/sizing.md", "# Sizing\n\n## Parallel units\n\n| Unit | Write scope | Depends on contract ids |\n|---|---|---|\n"
                                        "| u1 | src/, tests/test_widget_*.py | - |\n| u2 | docs/ | - |\n")
        proj.write(f"specs/{FEATURE}/tasks.md", "| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |\n"
                                                "|---|---|---|---|---|---|---|---|\n| T-001 | t | REQ-A-001 | - | - | 2 | implementer | u1 |\n")
        proj.commit("sizing and tasks")
        self.assertIsNone(self.handler(self.payload(proj))["output"])           # nothing changed yet
        proj.write("src/a.py", "x = 1\n")
        result = self.handler(self.payload(proj))
        self.assertEqual("block", result["output"]["decision"])

    def test_a_path_outside_every_scope_of_the_unit_does_not_block(self):
        proj = self.failing_unit()
        proj.write(".batuta/sizing.md", "# Sizing\n\n## Parallel units\n\n| Unit | Write scope | Depends on contract ids |\n|---|---|---|\n"
                                        "| u1 | src/ | - |\n")
        proj.write(f"specs/{FEATURE}/tasks.md", "| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |\n"
                                                "|---|---|---|---|---|---|---|---|\n| T-001 | t | REQ-A-001 | - | - | 2 | implementer | u1 |\n")
        proj.commit("sizing and tasks")
        proj.write("elsewhere/b.py", "x = 1\n")
        self.assertIsNone(self.handler(self.payload(proj))["output"])

    def test_the_scope_key_is_documented(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn("scope: [paths]", (root / "changes/u5-plugin-readme.md").read_text(encoding="utf-8"))
        self.assertIn("scope:", (root / "plugins/batuta/templates/gates/status.md").read_text(encoding="utf-8"))


class F6ModelMatching(unittest.TestCase):
    def test_the_whole_model_name_is_compared(self):
        from batuta_lib import evidence
        for ok in ("sonnet", "Sonnet", "claude-sonnet-5-5", "claude-sonnet-4-20250514", "sonnet-5.5", "claude-sonnet-5-5[1m]", "Claude Sonnet 5.5"):
            self.assertTrue(evidence.model_matches(ok, "sonnet"), ok)
        for bad in ("haiku-not-sonnet", "not-sonnet", "sonnet-lite", "opus", "sonnetx", "claude-opus-4-7-sonnet", "", "sonnet,opus"):
            self.assertFalse(evidence.model_matches(bad, "sonnet"), bad)

    def test_the_lint_refuses_a_token_in_another_name(self):
        from test_gate_fixtures import Project
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specs" / FEATURE / "evidence" / "L7-build.md"
            path.parent.mkdir(parents=True)
            path.write_text(evidence_text("L7-build", model="haiku-not-sonnet"), encoding="utf-8")
            code, out = run("gate", "evidence-lint", str(path), "--today", TODAY)
            self.assertEqual(1, code, out)
            self.assertIn("routes to model", out)


class F7Lessons(Case):
    def lessons(self, text):
        if not hasattr(self, "proj"):
            self.proj = self.project(git=False)
            self.proj.status({g: "passed" for g in GATES[:8]})
        self.proj.write("LESSONS.md", text)
        return run("lessons", "check", "--root", str(self.proj.root), "--today", TODAY)

    LINE = f"- 2026-10-12 | {FEATURE} | a lesson | an action"

    def test_a_lesson_inside_an_html_comment_does_not_count(self):
        code, out = self.lessons(f"<!--\n{self.LINE}\n-->\n")
        self.assertEqual(1, code, out)
        self.assertIn("MISSING", out)

    def test_a_lesson_inside_a_code_fence_does_not_count(self):
        code, out = self.lessons(f"```\n{self.LINE}\n```\n")
        self.assertEqual(1, code, out)

    def test_a_blank_action_or_lesson_is_refused(self):
        for bad in (f"- 2026-10-12 | {FEATURE} | a lesson |  ", f"- 2026-10-12 | {FEATURE} |   | an action"):
            code, out = self.lessons(bad + "\n")
            self.assertEqual(1, code, (bad, out))

    def test_a_real_line_beside_a_comment_still_counts(self):
        code, out = self.lessons(f"<!-- note -->\n{self.LINE}\n")
        self.assertEqual(0, code, out)


class F8F10TestsRecord(Check):
    """The record is C34; the release gate reads it."""

    def skeleton(self, proj, *extra):
        return run("skeleton", "check", "--root", str(proj.root), *extra)

    def set_up(self):
        proj = self.project()
        proj.catalog()
        proj.readiness()
        proj.commit("skeleton")
        return proj

    def test_a_record_that_is_not_an_object_of_results_is_a_finding_not_a_crash(self):
        proj = self.set_up()
        for body in ('{"results": ["x"]}', '{"contract_version": "1.0", "commit": "abc1234", "generated": "2026-10-12", "results": ["x"]}',
                     "[]", "not json", '{"contract_version": "1.0", "commit": "zz", "generated": "2026-10-12", "results": {}}'):
            rec = proj.write("docs/design/rec.json", body)
            code, out = self.skeleton(proj, "--tests-record", str(rec))
            self.assertEqual(1, code, (body, out))
            self.assertNotIn("Traceback", out)
            self.assertIn("C34", out)

    def test_a_skipped_test_is_not_evidence(self):
        proj = self.set_up()
        rec = proj.tests_record(proj.head(), {"tests/test_widget_producer.py": "pass", "tests/test_widget_consumer.py": "skip"})
        code, out = self.skeleton(proj, "--tests-record", str(rec))
        self.assertEqual(1, code, out)
        self.assertIn("skip", out)

    def test_named_tests_of_a_file_are_read_by_their_file(self):
        proj = self.set_up()
        rec = proj.tests_record(proj.head(), {"tests/test_widget_producer.py::test_a": "pass",
                                              "tests/test_widget_consumer.py::test_b": "pass"})
        code, out = self.skeleton(proj, "--tests-record", str(rec))
        self.assertEqual(0, code, out)

    def test_a_record_is_tied_to_the_head(self):
        proj = self.set_up()
        old = proj.head()
        proj.write("src/a.py", "x = 1\n")
        proj.commit("code after the tests ran")
        rec = proj.tests_record(old)
        code, out = self.skeleton(proj, "--tests-record", str(rec))
        self.assertEqual(1, code, out)
        self.assertIn("record is for", out)

    def test_changes_under_specs_or_to_the_record_itself_keep_it_current(self):
        proj = self.set_up()
        old = proj.head()
        proj.write(f"specs/{FEATURE}/notes.md", "n\n")
        rec = proj.tests_record(old)
        proj.commit("notes and the record")
        self.assertEqual(0, self.skeleton(proj, "--tests-record", str(rec))[0])

    def test_the_default_record_path_is_read_without_the_option(self):
        proj = self.set_up()
        proj.tests_record(proj.head(), {"tests/test_widget_producer.py": "pass", "tests/test_widget_consumer.py": "fail"})
        code, out = self.skeleton(proj)
        self.assertEqual(1, code, out)

    def test_the_release_gate_warns_without_a_record(self):
        proj = self.full_project()
        proj.remove("docs/design/contract-tests.json")
        proj.commit("no record")
        code, out = self.check(proj)
        self.assertEqual(2, code, out)
        self.assertRegex(out, r"WARN[^\n]*contract test")

    def test_the_release_gate_reads_a_failing_record(self):
        proj = self.full_project()
        proj.tests_record(proj.first(), {"tests/test_widget_producer.py": "fail", "tests/test_widget_consumer.py": "pass"})
        proj.commit("a failing record")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("tests/test_widget_producer.py", out)
    def test_a_compliant_release_with_a_current_record_passes(self):
        proj = self.full_project()
        code, out = self.check(proj)
        self.assertEqual(0, code, out)


class TestsRecordCommand(Case):
    def command(self, proj, *extra):
        return run("gate", "tests-record", "--root", str(proj.root), "--today", TODAY, *extra)

    def clean(self):
        proj = self.project()
        proj.catalog()
        proj.commit("catalog")
        return proj

    def written(self, proj):
        return json.loads((proj.root / "docs/design/contract-tests.json").read_text(encoding="utf-8"))

    def test_dry_run_writes_nothing_and_apply_writes_a_valid_c34_record(self):
        proj = self.clean()
        code, out = self.command(proj, "--result", "tests/test_widget_producer.py=skip", "--result", "tests/test_widget_consumer.py=skip")
        self.assertEqual(0, code, out)
        self.assertFalse((proj.root / "docs/design/contract-tests.json").exists())
        code, out = self.command(proj, "--result", "tests/test_widget_producer.py=skip", "--result", "tests/test_widget_consumer.py=skip", "--apply")
        self.assertEqual(0, code, out)
        doc = self.written(proj)
        sp = core.find_schema(config.contracts_dir(), "C34")
        self.assertEqual([], core.validate_instance("C34", doc, core.load_schema(sp)))
        self.assertEqual(proj.head(), doc["commit"])
        self.assertEqual(TODAY, doc["generated"])
        self.assertEqual({"tests/test_widget_producer.py": "skip", "tests/test_widget_consumer.py": "skip"}, doc["results"])

    def test_a_second_apply_changes_nothing(self):
        proj = self.clean()
        args = ("--result", "tests/test_widget_producer.py=skip", "--apply")
        self.command(proj, *args)
        code, out = self.command(proj, *args)
        self.assertEqual(0, code, out)
        self.assertIn("SAME", out)

    def test_bad_results_are_refused_before_writing(self):
        proj = self.clean()
        for bad in ("tests/x.py=maybe", "tests/x.py", "/abs/x.py=skip", "../x.py=skip", "tests\\x.py=skip", "=pass", "tests/x.py::=pass"):
            code, out = self.command(proj, "--result", bad, "--apply")
            self.assertEqual(1, code, (bad, out))
        self.assertFalse((proj.root / "docs/design/contract-tests.json").exists())

    def test_a_dirty_working_tree_is_refused_because_the_tests_did_not_run_at_the_commit(self):
        proj = self.clean()
        proj.write("src/a.py", "x = 1\n")
        code, out = self.command(proj, "--result", "tests/test_widget_producer.py=skip", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("uncommitted", out)
        code, out = self.command(proj, "--result", "tests/test_widget_producer.py=skip", "--apply", "--allow-dirty")
        self.assertEqual(0, code, out)

    def test_changes_under_specs_do_not_count_as_dirty(self):
        proj = self.clean()
        proj.write(f"specs/{FEATURE}/notes.md", "n\n")
        self.assertEqual(0, self.command(proj, "--result", "tests/test_widget_producer.py=skip", "--apply")[0])

    def test_the_commit_can_be_named(self):
        proj = self.clean()
        first = proj.head()
        proj.commit("another")
        code, out = self.command(proj, "--result", "tests/test_widget_producer.py=skip", "--commit", first[:10], "--apply")
        self.assertEqual(0, code, out)
        self.assertEqual(first, self.written(proj)["commit"])
        self.assertEqual(1, self.command(proj, "--result", "tests/test_widget_producer.py=skip", "--commit", "nonexistent", "--apply")[0])

    def test_run_executes_the_python_tests_the_catalog_names(self):
        proj = self.clean()
        proj.write("tests/test_widget_producer.py", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
        proj.write("tests/test_widget_consumer.py", "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.assertTrue(False)\n")
        proj.commit("tests")
        code, out = self.command(proj, "--run", "--apply")
        self.assertEqual(0, code, out)
        self.assertEqual({"tests/test_widget_producer.py": "pass", "tests/test_widget_consumer.py": "fail"}, self.written(proj)["results"])

    def test_a_file_in_which_no_test_ran_is_recorded_as_skip(self):
        proj = self.clean()      # the catalog fixture's files hold plain functions, not unittest cases
        code, out = self.command(proj, "--run", "--apply")
        self.assertEqual(0, code, out)
        self.assertEqual({"skip"}, set(self.written(proj)["results"].values()))

    def test_without_results_or_run_nothing_is_recorded(self):
        proj = self.clean()
        self.assertEqual(1, self.command(proj, "--apply")[0])


class F9PromoteEvidence(unittest.TestCase):
    HEAD = "a" * 40

    def ok(self, body):
        from batuta_lib import promote
        return promote.evidence_ok(f"head {self.HEAD}\n{body}", self.HEAD)

    def test_a_run_of_zero_tests_is_not_evidence(self):
        self.assertFalse(self.ok("Ran 0 tests in 0.0s\n\nOK\n"))
        self.assertFalse(self.ok("0 passed in 0.01s\n"))

    def test_an_all_skipped_run_is_not_evidence(self):
        self.assertFalse(self.ok("Ran 40 tests in 0.1s\n\nOK (skipped=40)\n"))
        self.assertFalse(self.ok("Ran 3 tests in 0.1s\n\nOK (skipped=5)\n"))

    def test_a_failing_line_beside_ok_is_refused(self):
        self.assertFalse(self.ok("1 failing\nRan 3 tests in 0.1s\n\nOK\n"))

    def test_a_real_green_run_is_accepted(self):
        self.assertTrue(self.ok("Ran 5 tests in 0.1s\n\nOK\n"))
        self.assertTrue(self.ok("Ran 5 tests in 0.1s\n\nOK (skipped=2)\n"))
        self.assertTrue(self.ok("5 passed in 0.3s\n"))

    def test_ok_alone_without_a_count_is_not_evidence(self):
        self.assertFalse(self.ok("OK\n"))


class F11StopState(Case):
    def setUp(self):
        super().setUp()
        from batuta_lib.areas import gate
        self.gate = gate
        self.handler = gate.HOOKS["gate-stop"]

    def failing(self):
        proj = self.full_project()
        proj.remove(f"specs/{FEATURE}/evidence/L7-build.md")
        return proj

    def payload(self, proj, **extra):
        p = {"hook_event_name": "Stop", "cwd": str(proj.root)}
        p.update(extra)
        return p

    def status_text(self, proj):
        return (proj.root / "specs" / FEATURE / "status.md").read_text(encoding="utf-8")

    def test_without_the_stop_hook_active_field_it_still_blocks_only_once(self):
        proj = self.failing()
        first = self.handler(self.payload(proj))
        second = self.handler(self.payload(proj))
        self.assertEqual("block", first["output"]["decision"])
        self.assertIsNone(second["output"])
        self.assertIn(f"- {datetime.date.today().isoformat()} UNVERIFIED:", self.status_text(proj))
        third = self.handler(self.payload(proj))
        self.assertIsNone(third["output"])
        self.assertEqual(1, self.status_text(proj).count("UNVERIFIED"))

    def test_a_different_failure_is_held_once_again(self):
        proj = self.failing()
        self.handler(self.payload(proj))
        self.handler(self.payload(proj))
        proj.remove(f"specs/{FEATURE}/evidence/L8-integrate.md")
        again = self.handler(self.payload(proj))
        self.assertEqual("block", again["output"]["decision"])

    def test_the_state_lives_under_the_coordination_root_and_is_bounded(self):
        proj = self.failing()
        self.handler(self.payload(proj))
        state = proj.root / ".batuta" / "gate-stop.state"
        self.assertTrue(state.is_file())
        keys = [f"session-{i}|{i:064x}" for i in range(1105)]
        for k in keys:
            self.gate._remember_hold(proj.root, {"coordination_root": ".batuta"}, k)
        self.assertLessEqual(len([x for x in state.read_text(encoding="utf-8").split("\n") if x]), 1000)
        self.assertEqual([], [p.name for p in state.parent.iterdir() if p.name.startswith(".state-")])

    def test_a_string_flag_is_not_the_boolean(self):
        proj = self.failing()
        first = self.handler(self.payload(proj, stop_hook_active="false"))
        self.assertEqual("block", first["output"]["decision"])

    def test_an_internal_error_allows_the_stop_and_says_why(self):
        proj = self.failing()
        with mock.patch.object(self.gate.gate_model.GIT, "dirty", side_effect=RuntimeError("git exploded")):
            result = self.handler(self.payload(proj))
        self.assertEqual(0, result["exit_code"])
        self.assertIsNone(result["output"])
        self.assertIn("git exploded", result["message"])
        sp = core.find_schema(config.contracts_dir(), "C31")
        self.assertEqual([], core.validate_instance("C31", result, core.load_schema(sp)))


if __name__ == "__main__":
    unittest.main()
