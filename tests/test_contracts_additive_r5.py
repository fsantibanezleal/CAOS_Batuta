"""Additive revision 5 of the contracts (ADR-0006): C01 1.1 with the `tdd` block, C34 (contract-tests record), C16 1.1
with the UserPromptSubmit output, and the C23 write-scope overlap check made case-insensitive and prefix-aware.

Plan decision 23: after the freeze a contract changes only by a minor version. The first test of each group guards that
every 1.0 document stays valid; the others carry the edge cases of each addition.
"""
import copy
import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib import contract  # noqa: E402

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"
FX = CONTRACTS / "fixtures"
NEW_C01 = {"valid-tdd-full.json", "valid-tdd-partial.json"}
SHA = "0123456789abcdef0123456789abcdef01234567"


def schema_file(cid):
    return sorted(CONTRACTS.glob(f"{cid}-*.schema.json"))[0]


def schema(cid):
    return contract.load_schema(schema_file(cid))


def fx(cid, name):
    return contract.validate_file(FX / cid / name, schema_file(cid))


def c01(**extra):
    doc = json.loads((FX / "C01" / "valid-minimal.json").read_text(encoding="utf-8"))
    doc.update(extra)
    return doc


def errs01(doc):
    return contract.validate_instance("C01", doc, schema("C01"))


def c34(**over):
    doc = {"contract_version": "1.0", "commit": SHA, "generated": "2026-10-13", "results": {"tests/test_a.py": "pass"}}
    doc.update(over)
    return doc


def errs34(doc):
    return contract.validate_instance("C34", doc, schema("C34"))


def errs16(doc):
    return contract.validate_instance("C16", doc, schema("C16"))


class C01TddBlock(unittest.TestCase):
    def test_every_1_0_fixture_is_judged_as_before(self):
        # a regression guard: it passes before the revision too, because the revision must not change any verdict
        for p in sorted((FX / "C01").iterdir()):
            if p.name in NEW_C01 or p.name.startswith("invalid-tdd-"):
                continue
            with self.subTest(fixture=p.name):
                errs = fx("C01", p.name)
                self.assertEqual(not errs, p.name.startswith("valid-"), errs)

    def test_a_1_0_document_without_tdd_is_valid(self):
        self.assertEqual(errs01(c01()), [])

    def test_a_1_1_document_without_tdd_is_valid(self):
        self.assertEqual(errs01(c01(contract_version="1.1")), [])

    def test_the_schema_is_1_1_and_accepts_both_versions(self):
        self.assertEqual(schema("C01")["contract_version"], "1.1")
        self.assertEqual(errs01(c01(contract_version="1.0")), [])
        self.assertTrue(errs01(c01(contract_version="1.2")))
        self.assertTrue(errs01(c01(contract_version="2.0")))

    def test_full_and_partial_fixtures_are_valid(self):
        self.assertEqual(fx("C01", "valid-tdd-full.json"), [])
        self.assertEqual(fx("C01", "valid-tdd-partial.json"), [])

    def test_a_full_block(self):
        tdd = {"test_command": "python -m unittest", "replay_timeout_seconds": 300, "lock_file": ".batuta/test-locks.json",
               "markers": ["skip", "xfail"]}
        self.assertEqual(errs01(c01(contract_version="1.1", tdd=tdd)), [])

    def test_an_empty_block_is_valid(self):
        self.assertEqual(errs01(c01(contract_version="1.1", tdd={})), [])

    def test_an_unknown_key_is_invalid(self):
        self.assertTrue(any("tdd" in e for e in errs01(c01(contract_version="1.1", tdd={"retries": 3}))))

    def test_the_timeout_is_an_integer_of_at_least_one(self):
        for bad in (0, -5, "300", 1.5, True):
            with self.subTest(value=bad):
                self.assertTrue(errs01(c01(contract_version="1.1", tdd={"replay_timeout_seconds": bad})))
        self.assertEqual(errs01(c01(contract_version="1.1", tdd={"replay_timeout_seconds": 1})), [])

    def test_the_lock_file_stays_inside_the_repository(self):
        for bad in ("/abs/locks.json", "../locks.json", "a/../b.json", "C:/locks.json", "a\\b.json", "./locks.json", ""):
            with self.subTest(value=bad):
                self.assertTrue(errs01(c01(contract_version="1.1", tdd={"lock_file": bad})))
        self.assertEqual(errs01(c01(contract_version="1.1", tdd={"lock_file": "locks/t.json"})), [])

    def test_markers_are_non_empty_strings(self):
        for bad in ([""], [1], "skip", ["a", ""]):
            with self.subTest(value=bad):
                self.assertTrue(errs01(c01(contract_version="1.1", tdd={"markers": bad})))
        self.assertEqual(errs01(c01(contract_version="1.1", tdd={"markers": []})), [])

    def test_the_test_command_is_a_string(self):
        self.assertTrue(errs01(c01(contract_version="1.1", tdd={"test_command": ["python"]})))

    def test_invalid_fixtures_exist_and_fail(self):
        for name in ("invalid-tdd-unknown-key.json", "invalid-tdd-timeout-zero.json", "invalid-tdd-timeout-string.json",
                     "invalid-tdd-lock-file-absolute.json", "invalid-tdd-lock-file-parent.json", "invalid-tdd-empty-marker.json"):
            with self.subTest(fixture=name):
                self.assertTrue(fx("C01", name))

    def test_the_budgets_block_is_untouched(self):
        budgets = schema("C01")["properties"]["budgets"]
        self.assertEqual(budgets["required"], ["user_core_bytes", "project_core_bytes", "unscoped_rules_bytes",
                                               "memory_index_bytes", "memory_index_lines"])


class C34Record(unittest.TestCase):
    def test_a_record_is_valid(self):
        self.assertEqual(errs34(c34()), [])

    def test_fixtures(self):
        for name in ("valid-full.json", "valid-empty-results.json", "valid-short-commit.json"):
            with self.subTest(fixture=name):
                self.assertEqual(fx("C34", name), [])
        for name in ("invalid-result-value.json", "invalid-test-path-absolute.json", "invalid-test-path-parent.json",
                     "invalid-bad-commit.json", "invalid-unknown-key.json", "invalid-missing-results.json"):
            with self.subTest(fixture=name):
                self.assertTrue(fx("C34", name))

    def test_empty_results_are_valid(self):
        self.assertEqual(errs34(c34(results={})), [])

    def test_the_three_values_only(self):
        for v in ("pass", "fail", "skip"):
            self.assertEqual(errs34(c34(results={"tests/a.py": v})), [])
        for bad in ("passed", "PASS", "error", "", True, None, 1):
            with self.subTest(value=bad):
                self.assertTrue(errs34(c34(results={"tests/a.py": bad})))

    def test_a_key_is_a_relative_path_with_an_optional_name(self):
        self.assertEqual(errs34(c34(results={"tests/a.py::test_x": "pass", "tests/a.py::Case::test_y": "fail"})), [])
        for bad in ("/abs/a.py", "../a.py", "a/../b.py", "C:/a.py", "a\\b.py", "./a.py", "tests/a.py::", "::x", "", "a//b.py"):
            with self.subTest(key=bad):
                self.assertTrue(errs34(c34(results={bad: "pass"})))

    def test_the_commit_is_7_to_40_lowercase_hex(self):
        for ok in (SHA, SHA[:7], SHA[:12]):
            self.assertEqual(errs34(c34(commit=ok)), [])
        for bad in (SHA[:6], SHA + "0", "ZZZZZZZ", SHA.upper(), "", 7):
            with self.subTest(commit=bad):
                self.assertTrue(errs34(c34(commit=bad)))

    def test_generated_is_a_real_date(self):
        self.assertTrue(errs34(c34(generated="2026-13-40")))
        self.assertTrue(errs34(c34(generated="yesterday")))

    def test_closed_and_complete(self):
        self.assertTrue(errs34(c34(extra=1)))
        for key in ("contract_version", "commit", "generated", "results"):
            doc = c34()
            del doc[key]
            with self.subTest(missing=key):
                self.assertTrue(errs34(doc))
        self.assertTrue(errs34(c34(contract_version="1.1")))

    def test_it_is_in_the_catalog(self):
        readme = (CONTRACTS / "README.md").read_text(encoding="utf-8")
        row = [ln for ln in readme.splitlines() if ln.startswith("| C34 ")]
        self.assertEqual(len(row), 1)
        self.assertIn("gate tests-record", row[0])
        self.assertIn("skeleton check --tests-record", row[0])
        self.assertIn("1.0", row[0])


UPS = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "approval recorded"}}


class C16UserPromptSubmitOutput(unittest.TestCase):
    def test_the_schema_is_1_1(self):
        self.assertEqual(schema("C16")["contract_version"], "1.1")

    def test_context_and_system_message(self):
        doc = copy.deepcopy(UPS)
        doc["systemMessage"] = "NEW approval recorded"
        self.assertEqual(errs16(doc), [])

    def test_context_alone(self):
        self.assertEqual(errs16(UPS), [])

    def test_system_message_alone(self):
        self.assertEqual(errs16({"systemMessage": "REFUSED: the prefix is abc"}), [])

    def test_block_with_reason_and_context(self):
        doc = copy.deepcopy(UPS)
        doc.update({"decision": "block", "reason": "spec not frozen"})
        self.assertEqual(errs16(doc), [])

    def test_universal_fields(self):
        doc = copy.deepcopy(UPS)
        doc.update({"continue": True, "suppressOutput": False, "stopReason": "x"})
        self.assertEqual(errs16(doc), [])

    def test_the_specific_fields_of_the_official_reference(self):
        doc = copy.deepcopy(UPS)
        doc["hookSpecificOutput"].update({"sessionTitle": "t", "suppressOriginalPrompt": True})
        self.assertEqual(errs16(doc), [])

    def test_an_unknown_key_is_invalid(self):
        bad = copy.deepcopy(UPS)
        bad["surprise"] = 1
        self.assertTrue(errs16(bad))
        bad = copy.deepcopy(UPS)
        bad["hookSpecificOutput"]["surprise"] = 1
        self.assertTrue(errs16(bad))

    def test_a_field_of_another_event_is_invalid_here(self):
        bad = copy.deepcopy(UPS)
        bad["hookSpecificOutput"]["permissionDecision"] = "deny"
        self.assertTrue(errs16(bad))

    def test_wrong_types(self):
        self.assertTrue(errs16({"systemMessage": 3}))
        bad = copy.deepcopy(UPS)
        bad["hookSpecificOutput"]["additionalContext"] = ["x"]
        self.assertTrue(errs16(bad))
        self.assertTrue(errs16({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit"}, "decision": "approve", "reason": "x"}))

    def test_the_1_0_outputs_still_validate(self):
        for name in ("valid-output-block.json", "valid-output-pretooluse-deny.json", "valid-output-sessionstart.json"):
            with self.subTest(fixture=name):
                self.assertEqual(fx("C16", name), [])

    def test_every_1_0_fixture_keeps_its_verdict(self):
        for p in sorted((FX / "C16").iterdir()):
            if "userpromptsubmit-" in p.name and "output" in p.name:
                continue
            with self.subTest(fixture=p.name):
                self.assertEqual(not fx("C16", p.name), p.name.startswith("valid-"))

    def test_new_fixtures(self):
        for name in ("valid-output-userpromptsubmit.json", "valid-output-userpromptsubmit-context-only.json"):
            with self.subTest(fixture=name):
                self.assertEqual(fx("C16", name), [])
        for name in ("invalid-output-userpromptsubmit-unknown-key.json", "invalid-output-userpromptsubmit-other-event-field.json"):
            with self.subTest(fixture=name):
                self.assertTrue(fx("C16", name))

    def test_the_launcher_accepts_a_userpromptsubmit_handler_result(self):
        doc = copy.deepcopy(UPS)
        doc["systemMessage"] = "NEW approval recorded"
        result = {"contract_version": "1.0", "exit_code": 0, "output": doc}
        self.assertEqual(contract.validate_instance("C31", result, schema("C31")), [])

    def test_the_launcher_still_refuses_a_bad_output(self):
        bad = copy.deepcopy(UPS)
        bad["surprise"] = 1
        result = {"contract_version": "1.0", "exit_code": 0, "output": bad}
        self.assertTrue(contract.validate_instance("C31", result, schema("C31")))


class C23Overlap(unittest.TestCase):
    def test_case_differences_overlap(self):
        self.assertTrue(contract.scopes_overlap("pipeline/", "PIPELINE/"))
        self.assertTrue(contract.scopes_overlap("pipeline/", "Pipeline/ingest.py"))

    def test_a_bare_name_is_a_prefix_of_what_is_under_it(self):
        self.assertTrue(contract.scopes_overlap("pipeline", "pipeline/x.py"))
        self.assertTrue(contract.scopes_overlap("pipeline/x.py", "pipeline"))
        self.assertTrue(contract.scopes_overlap("pipeline", "pipeline/sub/y.py"))
        self.assertTrue(contract.scopes_overlap("pipeline", "pipeline/*.py"))

    def test_no_false_overlap(self):
        self.assertFalse(contract.scopes_overlap("pipeline/", "pipelines/"))
        self.assertFalse(contract.scopes_overlap("pipeline", "pipelines/x.py"))
        self.assertFalse(contract.scopes_overlap("pipeline/a.py", "pipeline/b.py"))
        self.assertFalse(contract.scopes_overlap("Makefile", "*.md"))
        self.assertFalse(contract.scopes_overlap("api/routes.py", "ui/*.py"))

    def test_the_old_cases_hold(self):
        self.assertTrue(contract.scopes_overlap("api/", "api/routes/"))
        self.assertTrue(contract.scopes_overlap("api/*.py", "api/routes.py"))
        self.assertTrue(contract.scopes_overlap("a.py", "a.py"))

    def test_fixtures(self):
        for name in ("invalid-overlapping-write-scopes-case.md", "invalid-overlapping-write-scopes-bare-name.md"):
            with self.subTest(fixture=name):
                errs = fx("C23", name)
                self.assertTrue(any("write scopes overlap" in e for e in errs), errs)
        self.assertEqual(fx("C23", "valid-similar-scope-names.md"), [])

    def test_every_other_c23_fixture_keeps_its_verdict(self):
        new = {"invalid-overlapping-write-scopes-case.md", "invalid-overlapping-write-scopes-bare-name.md",
               "valid-similar-scope-names.md"}
        for p in sorted((FX / "C23").iterdir()):
            if p.name in new:
                continue
            with self.subTest(fixture=p.name):
                self.assertEqual(not fx("C23", p.name), p.name.startswith("valid-"))


class Lint(unittest.TestCase):
    def test_contract_lint_reports_no_failure(self):
        proc = subprocess.run([sys.executable, "-B", str(ROOT / "plugins" / "batuta" / "scripts" / "batuta.py"), "contract", "lint"],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("C34", proc.stdout)


if __name__ == "__main__":
    unittest.main()
