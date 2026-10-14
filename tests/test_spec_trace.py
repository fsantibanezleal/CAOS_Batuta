"""spec trace: C08 from the spec rows, tasks.md and the REQ markers of the tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import CONTRACTS, SPEC, SPEC_ID, make_project, messages, run, run_json, write  # noqa: E402
from batuta_lib import contract as core  # noqa: E402


class Trace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_project(self._tmp.name)
        self.trace_file = self.root / f"specs/{SPEC_ID}/trace.json"

    def tearDown(self):
        self._tmp.cleanup()

    def trace(self, *extra, apply=True):
        return run_json("spec", "trace", SPEC_ID, "--root", self.root, *extra, *(["--apply"] if apply else []))

    def matrix(self):
        return json.loads(self.trace_file.read_text(encoding="utf-8"))

    def test_matrix_maps_requirements_to_tests_and_tasks_and_satisfies_c08(self):
        code, doc, _ = self.trace()
        self.assertEqual(code, 0, messages(doc))
        m = self.matrix()
        self.assertEqual(core.validate_file(self.trace_file, core.find_schema(CONTRACTS, "C08")), [])
        by = {r["id"]: r for r in m["requirements"]}
        self.assertEqual(by["REQ-ALR-001"]["tests"], ["tests/test_alerts.py"])
        self.assertEqual(by["REQ-ALR-003"]["tests"], ["tests/api.test.js"])
        self.assertEqual(by["REQ-ALR-001"]["tasks"], ["T-001"])
        self.assertEqual(by["REQ-ALR-002"]["tasks"], ["T-002"])
        self.assertEqual(by["REQ-ALR-001"]["status"], "active")
        self.assertTrue(m["ok"])
        self.assertEqual((m["orphans"], m["unknown_ids"], m["untagged_tests"]), ([], [], []))

    def test_output_is_byte_stable_and_a_second_apply_is_same(self):
        self.trace()
        first = self.trace_file.read_bytes()
        code, doc, _ = self.trace()
        self.assertEqual(first, self.trace_file.read_bytes())
        self.assertTrue(any(i["tag"] == "SAME" for i in doc["items"]))
        self.assertNotIn(b"\r", first)
        self.assertTrue(first.endswith(b"\n"))

    def test_dry_run_writes_nothing(self):
        code, doc, _ = self.trace(apply=False)
        self.assertEqual(code, 0)
        self.assertFalse(self.trace_file.exists())

    def test_orphan_requirement_fails(self):
        write(self.root, "tests/test_alerts.py", "# REQ: REQ-ALR-001\ndef test_a():\n    pass\n")
        write(self.root, "tests/api.test.js", "// REQ: REQ-ALR-003\n")
        code, doc, _ = self.trace()
        self.assertEqual(code, 1)
        self.assertEqual(self.matrix()["orphans"], ["REQ-ALR-002"])
        self.assertFalse(self.matrix()["ok"])

    def test_unknown_marker_id_fails(self):
        write(self.root, "tests/test_alerts.py", "# REQ: REQ-ALR-001, REQ-ALR-002, REQ-NOPE-009\n")
        code, doc, _ = self.trace()
        self.assertEqual(code, 1)
        self.assertIn("REQ-NOPE-009", self.matrix()["unknown_ids"])

    def test_retired_id_in_a_marker_fails(self):
        text = SPEC.replace("`node --test tests/api.test.js` | unit test | active", "`node --test tests/api.test.js` | unit test | retired")
        write(self.root, f"specs/{SPEC_ID}/spec.md", text)
        code, doc, _ = self.trace()
        self.assertEqual(code, 1)
        self.assertIn("REQ-ALR-003", self.matrix()["unknown_ids"])
        self.assertTrue(any("retired" in m for m in messages(doc, "FAIL")))

    def test_retired_requirement_is_not_an_orphan(self):
        text = SPEC.replace("`node --test tests/api.test.js` | unit test | active", "`node --test tests/api.test.js` | unit test | retired")
        write(self.root, f"specs/{SPEC_ID}/spec.md", text)
        write(self.root, "tests/api.test.js", "// REQ: REQ-ALR-001\n")
        code, doc, _ = self.trace()
        self.assertEqual(self.matrix()["orphans"], [])
        self.assertEqual(self.matrix()["requirements"][2]["status"], "retired")

    def test_test_file_without_markers_is_untagged(self):
        write(self.root, "tests/api.test.js", "const test = require('node:test');\n")
        code, doc, _ = self.trace()
        self.assertEqual(code, 1)
        self.assertEqual(self.matrix()["untagged_tests"], ["tests/api.test.js"])

    def test_only_comment_lines_in_the_two_forms_count_as_markers(self):
        write(self.root, "tests/test_alerts.py",
              'x = "# REQ: REQ-ALR-001"\n// REQ: REQ-ALR-002\n#REQ REQ-ALR-003\n# req: REQ-ALR-001\n')
        write(self.root, "tests/api.test.js", "# REQ: REQ-ALR-003\nconst s = '// REQ: REQ-ALR-003';\n")
        code, doc, _ = self.trace()
        self.assertEqual(code, 1)
        m = self.matrix()
        self.assertEqual(sorted(m["orphans"]), ["REQ-ALR-001", "REQ-ALR-002", "REQ-ALR-003"])

    def test_indented_and_crlf_markers_count(self):
        write(self.root, "tests/test_alerts.py", "class T:\r\n    # REQ: REQ-ALR-001, REQ-ALR-002\r\n    def test_a(self): pass\r\n")
        code, doc, _ = self.trace()
        self.assertEqual(code, 0, messages(doc))

    def test_task_naming_an_unknown_requirement_fails(self):
        p = self.root / f"specs/{SPEC_ID}/tasks.md"
        write(self.root, f"specs/{SPEC_ID}/tasks.md", p.read_text(encoding="utf-8").replace("REQ-ALR-002 |", "REQ-ALR-002, REQ-ALR-077 |"))
        code, doc, _ = self.trace()
        self.assertEqual(code, 1)
        self.assertIn("REQ-ALR-077", self.matrix()["unknown_ids"])

    def test_draft_specs_are_exempt_from_the_orphan_rules(self):
        text = SPEC.replace("status: Review", "status: Draft")
        write(self.root, f"specs/{SPEC_ID}/spec.md", text)
        write(self.root, "tests/test_alerts.py", "# REQ: REQ-ALR-001\n")
        code, doc, _ = self.trace()
        self.assertEqual(code, 0, messages(doc))
        self.assertEqual(self.matrix()["orphans"], ["REQ-ALR-002"])
        self.assertTrue(any(i["tag"] == "SKIP" for i in doc["items"]))

    def test_draft_still_fails_on_unknown_ids(self):
        write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace("status: Review", "status: Draft"))
        write(self.root, "tests/test_alerts.py", "# REQ: REQ-ZZZ-001\n")
        code, doc, _ = self.trace()
        self.assertEqual(code, 1)

    def test_extra_test_paths_widen_the_feature_scope(self):
        write(self.root, "tests/contracts/test_extra.py", "def test_x():\n    pass\n")
        code, doc, _ = self.trace("--tests", "tests/contracts")
        self.assertEqual(code, 1)
        self.assertIn("tests/contracts/test_extra.py", self.matrix()["untagged_tests"])

    def test_commented_example_rows_are_not_requirements(self):
        text = SPEC.replace("## Edge cases", "<!--\n| REQ-GHO-001 | ubiquitous | example | `x` | x | active |\n-->\n\n## Edge cases")
        write(self.root, f"specs/{SPEC_ID}/spec.md", text)
        code, doc, _ = self.trace()
        self.assertEqual(code, 0, messages(doc))
        self.assertNotIn("REQ-GHO-001", [r["id"] for r in self.matrix()["requirements"]])

    def test_requirement_without_a_task_is_a_warning(self):
        p = self.root / f"specs/{SPEC_ID}/tasks.md"
        write(self.root, f"specs/{SPEC_ID}/tasks.md", p.read_text(encoding="utf-8").replace("REQ-ALR-001, REQ-ALR-003", "REQ-ALR-001"))
        code, doc, _ = self.trace()
        self.assertEqual(code, 2)
        self.assertTrue(any("REQ-ALR-003" in m for m in messages(doc, "WARN")))

    def test_unknown_spec_fails(self):
        code, doc, _ = run_json("spec", "trace", "009-none", "--root", self.root)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()


class MarkerReader(unittest.TestCase):
    """F-11: one reader of the REQ markers (shared with `tdd lock` later); a marker inside a string never counts."""

    def read(self, name, text):
        from batuta_lib import trace
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / name
            p.write_text(text, encoding="utf-8")
            return trace.scan_markers(p)

    def test_python_marker_inside_a_triple_quoted_string_does_not_count(self):
        text = 'DOC = """\n# REQ: REQ-ALR-001\n"""\n'
        self.assertEqual(self.read("test_a.py", text), [])

    def test_python_comment_lines_count_including_indented_and_crlf(self):
        text = "class T:\r\n    # REQ: REQ-ALR-001, REQ-ALR-002\r\n    def test_a(self): pass\r\n"
        self.assertEqual(self.read("test_a.py", text), ["REQ-ALR-001", "REQ-ALR-002"])

    def test_python_trailing_comment_and_other_spellings_do_not_count(self):
        text = "x = 1  # REQ: REQ-ALR-001\n#REQ REQ-ALR-002\n# req: REQ-ALR-003\n"
        self.assertEqual(self.read("test_a.py", text), [])

    def test_python_file_that_cannot_be_tokenized_keeps_the_markers_before_the_error(self):
        text = "# REQ: REQ-ALR-001\nx = (\n"
        self.assertEqual(self.read("test_a.py", text), ["REQ-ALR-001"])

    def test_js_marker_inside_a_template_literal_or_string_does_not_count(self):
        text = "const a = `\n// REQ: REQ-ALR-001\n`;\nconst b = '// REQ: REQ-ALR-002';\nconst c = \"x\\n// REQ: REQ-ALR-003\";\n"
        self.assertEqual(self.read("a.test.js", text), [])

    def test_js_marker_inside_a_block_comment_does_not_count_and_real_ones_do(self):
        text = "/*\n// REQ: REQ-ALR-001\n*/\n  // REQ: REQ-ALR-002\nconst x = 1; // REQ: REQ-ALR-003\n"
        self.assertEqual(self.read("a.test.ts", text), ["REQ-ALR-002"])

    def test_spec_trace_reports_a_requirement_tagged_only_inside_a_string_as_an_orphan(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_project(d)
            write(root, "tests/test_alerts.py", 'DOC = """\n# REQ: REQ-ALR-001\n"""\n# REQ: REQ-ALR-002\n')
            code, doc, _ = run_json("spec", "trace", SPEC_ID, "--root", root)
            self.assertEqual(code, 1)
            self.assertTrue(any("REQ-ALR-001" in m for m in messages(doc, "FAIL")), messages(doc))
