"""Gate cells: runnable text, and every file or folder a Gate names is hashed by the freeze (review findings F-03, F-04, F-05, F-12)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import SPEC, SPEC_ID, make_project, messages, prefix_of, run_json, write  # noqa: E402
from batuta_lib import spec_model as sm  # noqa: E402
from batuta_lib.areas import spec as spec_area  # noqa: E402

GATE1 = "`pytest tests/test_alerts.py`"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_project(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def gate(self, text):
        write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace(GATE1, text))

    def lint(self):
        return run_json("spec", "lint", "--root", self.root)

    def approve(self):
        phrase = f"approve {SPEC_ID} {prefix_of(self.root / 'specs' / SPEC_ID / 'spec.md')}\n"
        with mock.patch.object(spec_area, "_read_console", return_value=phrase):
            return run_json("spec", "approve", SPEC_ID, "--root", self.root)

    def check(self):
        return run_json("spec", "freeze", "--check", SPEC_ID, "--root", self.root)

    def fails(self, doc):
        return " | ".join(messages(doc, "FAIL"))


class Escapes(Base):
    def test_a_dotdot_that_stays_inside_the_root_is_normalized_and_hashed(self):
        self.gate("`pytest tests/../tests/test_alerts.py`")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))
        self.assertEqual(self.approve()[0], 0)
        write(self.root, "tests/test_alerts.py", "# REQ: REQ-ALR-001, REQ-ALR-002\ndef test_listing():\n    assert False\n")
        self.assertEqual(self.check()[0], 1)

    def test_a_dotdot_that_leaves_the_root_is_a_lint_fail_and_an_approval_refusal_never_a_silent_drop(self):
        for gate in ("`pytest ../outside/test_x.py`", "`pytest tests/../../x/test_y.py`"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1)
                self.assertIn("REQ-ALR-001", self.fails(doc))
                self.assertIn("outside", self.fails(doc))
                self.assertEqual(self.approve()[0], 1)
                self.assertEqual(list((self.root / f"specs/{SPEC_ID}/approvals").glob("*.json")), [])

    def test_backslashes_are_normalized_to_the_same_file(self):
        self.gate("`pytest tests\\test_alerts.py`")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))
        self.assertEqual(self.approve()[0], 0)
        write(self.root, "tests/test_alerts.py", "# REQ: REQ-ALR-001, REQ-ALR-002\ndef test_listing():\n    assert False\n")
        self.assertEqual(self.check()[0], 1)

    def test_a_symlink_or_junction_out_of_the_root_is_refused_with_a_reason(self):
        outside = Path(tempfile.mkdtemp())
        try:
            (outside / "test_far.py").write_text("# REQ: REQ-ALR-001\n", encoding="utf-8")
            link = self.root / "tests" / "linked"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("this account cannot create symbolic links")
            self.gate("`pytest tests/linked/test_far.py`")
            code, doc, _ = self.approve()
            self.assertEqual(code, 1)
            self.assertTrue(any("outside" in m for m in messages(doc, "REFUSED")), messages(doc))
        finally:
            for f in outside.iterdir():
                f.unlink()
            outside.rmdir()

    def test_expand_tests_reports_the_paths_that_leave_the_root(self):
        files, missing, outside = sm.expand_tests(self.root, ["tests/../../x/test_a.py"])
        self.assertEqual((files, missing), ([], []))
        self.assertEqual(outside, ["tests/../../x/test_a.py"])


class Hashable(Base):
    def test_gates_that_run_tests_name_what_they_hash(self):
        for gate, hashed in (("`python -m pytest tests`", "tests/test_alerts.py"),
                             ("`python -m unittest discover -s tests`", "tests/api.test.js"),
                             ("`python checks/verify_alerts.py`", "checks/verify_alerts.py"),
                             ("`pytest tests\\test_alerts.py`", "tests/test_alerts.py")):
            with self.subTest(gate=gate):
                write(self.root, "checks/verify_alerts.py", "print('ok')\n")
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 0, messages(doc))
                self.assertEqual(self.approve()[0], 0)
                rec = json.loads(sorted((self.root / f"specs/{SPEC_ID}/approvals").glob("*.json"))[-1].read_text(encoding="utf-8"))
                self.assertIn(hashed, rec["named_tests_sha256"])

    def test_a_gate_that_yields_no_hashable_file_or_folder_fails_at_review(self):
        for gate in ("`python -m pytest -k test_emit`", "`pytest`", "`ruff check`"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1)
                self.assertIn("hash", self.fails(doc))
                self.assertEqual(self.approve()[0], 1)

    def test_a_k_filter_counts_only_with_a_path(self):
        self.gate("`python -m pytest tests/test_alerts.py -k test_emit`")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_a_draft_spec_is_not_required_to_hash_anything(self):
        write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace(GATE1, "`ruff check`").replace("status: Review", "status: Draft"))
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_editing_a_test_named_through_a_folder_gate_voids(self):
        self.gate("`python -m pytest tests`")
        self.assertEqual(self.approve()[0], 0)
        write(self.root, "tests/test_alerts.py", "# REQ: REQ-ALR-001, REQ-ALR-002\ndef test_listing():\n    assert False\n")
        self.assertEqual(self.check()[0], 1)


class Runnable(Base):
    def test_prose_around_a_span_and_bare_names_are_not_gates(self):
        for gate in ("Reviewed by `QA`", "See `docs`", "`tbd.`", "`todo: write the test`", "README.md", "`TBD`; later",
                     "tests/../test_alerts.py", "docs/notes.md::x"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1, gate)
                self.assertIn("gate", self.fails(doc))

    def test_commands_that_cannot_fail_are_not_gates(self):
        for gate in ("`true`", "`false`", "`exit 0`", "`echo ok`", "`:`"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1, gate)
                self.assertIn("REQ-ALR-001", self.fails(doc))

    def test_several_spans_separated_by_semicolons_and_test_ids_are_gates(self):
        for gate in ("`pytest tests/test_alerts.py`; `node --test tests/api.test.js`", "`pytest tests/test_alerts.py` `ruff check`",
                     "tests/test_alerts.py::test_emit", "tests/api.test.js"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 0, messages(doc))

    def test_check_gate_unit(self):
        self.assertIsNone(sm.check_gate("`pytest tests/test_x.py`"))
        self.assertIsNotNone(sm.check_gate("Reviewed by `QA`"))
        self.assertIsNotNone(sm.check_gate("TBD:"))
        self.assertIsNotNone(sm.check_gate("tests/../x/test_a.py"))


if __name__ == "__main__":
    unittest.main()
