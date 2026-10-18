"""Drift test: the generated reference pages equal what scripts/gen_reference.py writes now from the code and the contracts."""
import tempfile
import unittest
from pathlib import Path

from _support import ROOT, load_module

GEN = load_module("gen_reference_under_test", ROOT / "scripts" / "gen_reference.py")
REFERENCE = ROOT / "docs" / "reference"


class GeneratedReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        GEN.write_pages(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_each_page_equals_the_regenerated_one(self):
        for name in GEN.PAGES:
            committed = (REFERENCE / name).read_bytes()
            fresh = (Path(self.tmp.name) / name).read_bytes()
            self.assertEqual(committed, fresh, f"docs/reference/{name} is out of date: run `python scripts/gen_reference.py`")

    def test_pages_are_lf_utf8_without_machine_paths(self):
        for name in GEN.PAGES:
            raw = (Path(self.tmp.name) / name).read_bytes()
            self.assertNotIn(b"\r", raw)
            text = raw.decode("utf-8")
            self.assertNotRegex(text, r"[A-Za-z]:[\/]Users[\/]|/home/[A-Za-z0-9_.-]+/")

    def test_cli_page_names_every_area_and_the_contracts_page_every_contract(self):
        batuta = load_module("batuta_for_docs", ROOT / "plugins" / "batuta" / "scripts" / "batuta.py")
        areas, _ = batuta.load_areas()
        cli = (REFERENCE / "cli.md").read_text(encoding="utf-8")
        for module in areas:
            self.assertIn(f"## Area `{module.AREA}`", cli)
        contracts = (REFERENCE / "contracts.md").read_text(encoding="utf-8")
        for n in range(1, 35):
            self.assertIn(f"`C{n:02d}`", contracts)

    def test_check_mode_agrees(self):
        self.assertEqual(GEN.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
