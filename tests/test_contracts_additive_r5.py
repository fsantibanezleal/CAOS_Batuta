"""Additive revision 5 of the contracts (ADR-0006): C01 1.1 with the `tdd` block, C34 (contract-tests record), C16 1.1
with the UserPromptSubmit output, and the C23 write-scope overlap check made case-insensitive and prefix-aware.

Plan decision 23: after the freeze a contract changes only by a minor version. The first test of each group guards that
every 1.0 document stays valid; the others carry the edge cases of each addition.
"""
import copy
import json
import pathlib
import re
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


# the fence rule of contracts 1.0 (develop 57a3506), kept here as the oracle for the backtick cases
OLD_FENCED = re.compile(r"^[ \t]*```.*?^[ \t]*```[^\n]*$", re.MULTILINE | re.DOTALL)


class ProseFences(unittest.TestCase):
    """F-15, F3 and F5: tilde fences are fences too; a backtick fence is stripped exactly as in 1.0 and a tilde fence the same way."""

    def test_tilde_fence(self):
        self.assertNotIn("TODO", contract.prose("before\n~~~\nTODO inside\n~~~\nafter\n"))

    def test_four_tildes(self):
        self.assertNotIn("TODO", contract.prose("a\n~~~~\nTODO\n~~~~\nout\n"))

    def test_any_indent_before_the_marker(self):
        for indent in ("  ", "   ", "    ", "      ", "\t", " \t"):
            with self.subTest(indent=repr(indent)):
                self.assertNotIn("TODO", contract.prose(f"a\n{indent}~~~\n{indent}TODO\n{indent}~~~\nb\n"))
                self.assertNotIn("TODO", contract.prose(f"a\n{indent}```\n{indent}TODO\n{indent}```\nb\n"))

    def test_a_fence_inside_a_nested_list_item(self):
        text = "- a\n  - b\n    ```\n    TODO\n    ```\nafter\n"
        self.assertNotIn("TODO", contract.prose(text))
        self.assertNotIn("TODO", contract.prose(text.replace("```", "~~~")))

    def test_info_string(self):
        self.assertNotIn("TODO", contract.prose("a\n~~~python title\nTODO\n~~~\nb\n"))
        self.assertNotIn("TODO", contract.prose("a\n```json\nTODO\n```\nb\n"))

    def test_an_unclosed_fence_is_not_stripped_as_in_1_0(self):
        self.assertIn("TODO", contract.prose("keep\n~~~\nTODO\nmore\n"))
        self.assertIn("TODO", contract.prose("keep\n```\nTODO\n"))

    def test_a_closing_line_with_text_closes_as_in_1_0(self):
        text = "a\n~~~\nx\n~~~ trailing\nTODO\nb\n"
        self.assertIn("TODO", contract.prose(text))

    def test_a_different_character_does_not_close(self):
        self.assertNotIn("TODO", contract.prose("a\n~~~\nx\n```\nTODO\n~~~\nb\n"))

    def test_text_outside_the_fence_is_still_checked(self):
        out = contract.prose("TODO before\n~~~\nquoted\n~~~\nTODO after\n")
        self.assertEqual(out.count("TODO"), 2)

    def test_every_backtick_input_is_stripped_exactly_as_in_1_0(self):
        corpus = [
            "a\n```\nX\n```\nb\n", "a\n```\nX\n", "```\nX\n```", "a\n  ```py\nX\n  ```  \nb\n", "a\n````\n```\nX\n```\n````\nout\n",
            "a\n```\nX\n``` text\nY\n```\nZ\n", "a\n    ```\nX\n    ```\nb\n", "a\n\t```\nX\n\t```\nb\n", "a ```\nX\n```\n",
            "```\n```\n```\nX\n```\n", "- a\n  - b\n    ```\n    X\n    ```\nafter\n", "a\r\n```\r\nX\r\n```\r\nb\r\n",
            "```x```\nX\n```\n", "a\n```\n\n```\n\n```\nY\n", "",
        ]
        for text in corpus:
            with self.subTest(text=text):
                self.assertEqual(contract.strip_fences(text), OLD_FENCED.sub("", text))

    def test_a_tilde_fence_is_stripped_like_the_backtick_one(self):
        corpus = ["a\n```\nX\n```\nb\n", "a\n```\nX\n", "a\n    ```py\nX\n    ```\nb\n", "a\n```\nX\n``` text\nY\n```\nZ\n",
                  "```\nX\n```\n```\nY\n"]
        for text in corpus:
            with self.subTest(text=text):
                self.assertEqual(contract.strip_fences(text.replace("`", "~")), OLD_FENCED.sub("", text).replace("`", "~"))

    def test_a_report_with_a_placeholder_inside_a_tilde_fence_is_valid(self):
        text = (FX / "C03" / "valid-placeholder-words-inside-code-are-quoted-not-prose.md").read_text(encoding="utf-8")
        spec = contract.load_sections_spec(schema_file("C03"))
        self.assertEqual(contract.validate_markdown(text, schema("C03"), spec), [])
        self.assertEqual(contract.validate_markdown(text.replace("```", "~~~"), schema("C03"), spec), [])

    def test_a_placeholder_outside_any_fence_is_still_refused(self):
        text = (FX / "C03" / "invalid-placeholder-in-prose.md").read_text(encoding="utf-8")
        self.assertTrue(contract.validate_markdown(text, schema("C03"), contract.load_sections_spec(schema_file("C03"))))


class AdversaryFindings(unittest.TestCase):
    """The reproductions of the adversary check of 5abe683 (F1, F2, F4, F6): the binding test is additivity."""

    def test_F1_a_glob_and_a_bare_sibling_file_are_disjoint(self):
        for a, b in (("tests/unit/test_*.py", "tests/unit/conftest.py"), ("docs/*.md", "docs/CHANGELOG.txt"),
                     ("src/*.py", "src/py.typed"), ("src/*.py", "src/b.txt")):
            with self.subTest(a=a, b=b):
                self.assertFalse(contract.scopes_overlap(a, b))
                self.assertFalse(contract.scopes_overlap(b, a))

    def test_F1_a_glob_still_meets_what_it_matches(self):
        self.assertTrue(contract.scopes_overlap("tests/unit/test_*.py", "tests/unit/test_a.py"))
        self.assertTrue(contract.scopes_overlap("DOCS/*.md", "docs/readme.md"))
        self.assertTrue(contract.scopes_overlap("src/*.py", "src/sub/"))
        self.assertTrue(contract.scopes_overlap("src/*", "src/a/*.py"))

    def test_F1_a_bare_name_is_a_prefix_only_below_it(self):
        self.assertFalse(contract.scopes_overlap("a", "ab/"))
        self.assertFalse(contract.scopes_overlap("a", "ab/x.py"))
        self.assertFalse(contract.scopes_overlap("a", "a.txt"))
        self.assertTrue(contract.scopes_overlap("a", "a/b.py"))

    def test_F1_the_sizing_of_the_reproduction(self):
        text = (FX / "C23" / "valid-globs-and-br-separated-scopes.md").read_text(encoding="utf-8")
        self.assertEqual(contract.validate_markdown(text, schema("C23"), contract.load_sections_spec(schema_file("C23"))), [])

    def test_F1_the_two_new_valid_fixtures(self):
        for name in ("valid-glob-and-sibling-file.md", "valid-glob-and-sibling-file-docs.md"):
            with self.subTest(fixture=name):
                self.assertEqual(fx("C23", name), [])

    def test_F6_casefold_not_lower(self):
        self.assertTrue(contract.scopes_overlap("straße/", "STRASSE/"))
        self.assertTrue(contract.scopes_overlap("STRASSE/x.py", "straße"))

    def test_F2_a_1_0_document_with_any_tdd_value_stays_valid(self):
        for value in ({"foo": 1}, "anything", 5, None, [1], {"replay_timeout_seconds": 0}):
            with self.subTest(value=value):
                self.assertEqual(errs01(c01(contract_version="1.0", tdd=value)), [])

    def test_F2_the_closed_block_applies_to_1_1(self):
        for value in ({"foo": 1}, "anything", 5, None, [1], {"replay_timeout_seconds": 0}):
            with self.subTest(value=value):
                self.assertTrue(errs01(c01(contract_version="1.1", tdd=value)))

    def test_F2_the_errors_name_the_tdd_path(self):
        errs = errs01(c01(contract_version="1.1", tdd={"retries": 3, "replay_timeout_seconds": 0}))
        self.assertTrue(any(e.startswith("/tdd/retries") for e in errs), errs)
        self.assertTrue(any(e.startswith("/tdd/replay_timeout_seconds") for e in errs), errs)
        self.assertTrue(any(e.startswith("/tdd:") for e in errs01(c01(contract_version="1.1", tdd="x"))))

    def test_F6_the_lock_file_is_a_json_file_that_is_not_the_configuration(self):
        for bad in ("locks", "locks.txt", "a/", "batuta.json", ".batuta/batuta.json", ".batuta/BATUTA.JSON", "x/.json.bak"):
            with self.subTest(value=bad):
                self.assertTrue(errs01(c01(contract_version="1.1", tdd={"lock_file": bad})))
        for ok in (".batuta/test-locks.json", "locks/t.json", "my-batuta.json", "batuta.json.d/locks.json"):
            with self.subTest(value=ok):
                self.assertEqual(errs01(c01(contract_version="1.1", tdd={"lock_file": ok})), [])

    def test_F4_a_block_without_a_reason_is_valid_and_an_empty_reason_is_not(self):
        doc = copy.deepcopy(UPS)
        doc["decision"] = "block"
        self.assertEqual(errs16(doc), [])
        doc["reason"] = ""
        self.assertTrue(errs16(doc))
        doc["reason"] = "   "
        self.assertTrue(errs16(doc))

    def test_F6_c34_keys_are_files_without_line_breaks(self):
        for bad in ("tests/", "tests/a.py::bad\nname", "tests/a.py::bad\tname", "tests/a.py::x\x00", "tests/a.py\r::x", "tests/a/::x"):
            with self.subTest(key=bad):
                self.assertTrue(errs34(c34(results={bad: "pass"})))
        self.assertEqual(errs34(c34(results={"tests/a.py::Case::test with spaces": "pass"})), [])

    def test_F7_the_readme_sentence_names_the_1_1_exception(self):
        readme = (CONTRACTS / "README.md").read_text(encoding="utf-8")
        line = [ln for ln in readme.splitlines() if ln.startswith("Every JSON artifact carries")]
        self.assertEqual(len(line), 1, line)
        self.assertIn("C01", readme[readme.index(line[0]):readme.index(line[0]) + 400])
        self.assertIn("1.1", readme[readme.index(line[0]):readme.index(line[0]) + 400])


class Lint(unittest.TestCase):
    def test_contract_lint_reports_no_failure(self):
        proc = subprocess.run([sys.executable, "-B", str(ROOT / "plugins" / "batuta" / "scripts" / "batuta.py"), "contract", "lint"],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("C34", proc.stdout)


if __name__ == "__main__":
    unittest.main()
