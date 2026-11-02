"""The gate templates pass the lint of their own contracts (a template that fails its own lint is a defect)."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from batuta_lib import config, contract as core, evidence, gate_model, readiness, thresholds  # noqa: E402

GATES_DIR = ROOT / "plugins" / "batuta" / "templates" / "gates"


class Templates(unittest.TestCase):
    def test_the_status_template_is_a_valid_c10_file_with_every_gate_pending(self):
        text = (GATES_DIR / "status.md").read_text(encoding="utf-8")
        self.assertEqual([], gate_model.status_errors(text))
        for gate in gate_model.GATES:
            self.assertRegex(text, rf"{gate}: pending")

    def test_the_evidence_template_is_valid_c09_and_is_not_a_pass(self):
        text = (GATES_DIR / "evidence.md").read_text(encoding="utf-8")
        items, meta = evidence.lint_text(text, config.default_config(), today="2026-12-31")
        self.assertEqual([], [i for i in items if i["tag"] == "FAIL"], items)
        self.assertEqual("FAIL", meta["verdict"])

    def test_the_thresholds_template_is_valid_c11(self):
        doc = json.loads((GATES_DIR / "thresholds.json").read_text(encoding="utf-8"))
        self.assertEqual([], thresholds.schema_errors(doc))

    def test_the_readiness_template_is_valid_c27(self):
        doc = json.loads((GATES_DIR / "readiness.json").read_text(encoding="utf-8"))
        self.assertEqual([], readiness.readiness_errors(doc))

    def test_no_template_names_a_machine_path(self):
        for path in GATES_DIR.rglob("*"):
            if path.is_file():
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"[A-Za-z]:[\\/]|/home/|/Users/", path.name)


if __name__ == "__main__":
    unittest.main()
