"""Foundation checks every Batuta project starts with: the configuration and the thresholds file are well formed, so the
CI job has real tests to run from the first commit. Replace or extend them with the project's own tests."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FoundationTests(unittest.TestCase):
    def test_batuta_configuration_names_the_test_command(self):
        doc = json.loads((ROOT / ".batuta" / "batuta.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["tdd"]["test_command"].strip())

    def test_thresholds_have_values_and_an_append_only_history(self):
        doc = json.loads((ROOT / "specs" / "000-foundation" / "thresholds.json").read_text(encoding="utf-8"))
        self.assertIsInstance(doc["values"], dict)
        self.assertIsInstance(doc["history"], list)

    def test_the_constitution_is_present(self):
        text = (ROOT / "specs" / "000-foundation" / "constitution.md").read_text(encoding="utf-8")
        self.assertIn("Article 1", text)


if __name__ == "__main__":
    unittest.main()
