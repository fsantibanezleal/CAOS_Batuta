"""tech lint: exact versions, primary source URL, verified date age, and the spike rule of an evaluation."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import CONTRACTS, TECH, TODAY, make_project, messages, run_json, write  # noqa: E402


class TechLint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_project(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def lint(self, *extra):
        return run_json("tech", "lint", "--root", self.root, "--today", TODAY, *extra)

    def sizing(self, old, new):
        p = self.root / ".batuta/sizing.md"
        write(self.root, ".batuta/sizing.md", p.read_text(encoding="utf-8").replace(old, new))

    def tech_file(self, doc):
        write(self.root, "docs/design/tech/fastapi.json", json.dumps(doc, indent=2) + "\n")

    def test_valid_matrix_passes(self):
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_range_versions_fail(self):
        for bad in (">=3.13", "^3.13.1", "3.*", "3", "~3.13", "3.13 - 3.14"):
            with self.subTest(version=bad):
                self.sizing("| 3.13.1 |", f"| {bad} |")
                code, doc, _ = self.lint()
                self.assertEqual(code, 1)
                self.assertTrue(any("Python" in m and "version" in m.lower() for m in messages(doc, "FAIL")), messages(doc))
                self.sizing(f"| {bad} |", "| 3.13.1 |")

    def test_missing_source_url_fails(self):
        self.sizing("https://docs.python.org/3.13/", "-")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("Python" in m for m in messages(doc, "FAIL")))

    def test_date_not_on_the_calendar_fails(self):
        self.sizing("| https://docs.python.org/3.13/ | 2026-10-12 |", "| https://docs.python.org/3.13/ | 2026-02-30 |")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_stale_verified_date_warns_beyond_the_window(self):
        code, doc, _ = run_json("tech", "lint", "--root", self.root, "--today", "2027-02-01")
        self.assertEqual(code, 2)
        self.assertTrue(any("older than 90 days" in m for m in messages(doc, "WARN")), messages(doc))

    def test_window_is_configurable(self):
        code, doc, _ = run_json("tech", "lint", "--root", self.root, "--today", "2027-02-01", "--max-age-days", "400")
        self.assertEqual(code, 0, messages(doc))
        code, doc, _ = run_json("tech", "lint", "--root", self.root, "--today", "2026-10-14", "--max-age-days", "1")
        self.assertEqual(code, 2)

    def test_risky_chosen_candidate_needs_a_passed_spike(self):
        d = copy.deepcopy(TECH)
        d["evaluation"]["candidates"][0]["risky"] = True
        d["evaluation"]["candidates"][0]["spike"] = {"command": "python spike.py", "result": "fail", "evidence": "docs/design/spike.md"}
        self.tech_file(d)
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("spike" in m for m in messages(doc, "FAIL")), messages(doc))

    def test_risky_chosen_candidate_without_any_spike_fails(self):
        d = copy.deepcopy(TECH)
        d["evaluation"]["candidates"][0]["risky"] = True
        self.tech_file(d)
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_risky_chosen_candidate_with_a_passed_spike_passes(self):
        d = copy.deepcopy(TECH)
        d["evaluation"]["candidates"][0]["risky"] = True
        d["evaluation"]["candidates"][0]["spike"] = {"command": "python spike.py", "result": "pass", "evidence": "docs/design/spike.md"}
        self.tech_file(d)
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_decision_that_is_not_a_matrix_row_fails(self):
        d = copy.deepcopy(TECH)
        d["version"] = "0.116.0"
        d["evaluation"]["candidates"][0]["version"] = "0.116.0"
        self.tech_file(d)
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("matrix" in m for m in messages(doc, "FAIL")))

    def test_missing_sizing_fails(self):
        (self.root / ".batuta/sizing.md").unlink()
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_invalid_c25_fixtures_are_rejected_for_their_stated_reason(self):
        for fx in sorted((CONTRACTS / "fixtures" / "C25").glob("invalid-*.json")):
            with self.subTest(fixture=fx.name):
                meta = json.loads(fx.read_text(encoding="utf-8"))
                write(self.root, "docs/design/tech/fastapi.json", fx.read_text(encoding="utf-8"))
                code, doc, _ = self.lint()
                self.assertEqual(code, 1)
                self.assertIn(meta["_expect"].lower(), " ".join(messages(doc, "FAIL")).lower())


if __name__ == "__main__":
    unittest.main()
