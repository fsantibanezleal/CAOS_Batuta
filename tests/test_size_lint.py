"""size lint: C23 through the contract area, then the cross-checks against the catalog, units, components and totals."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import CATALOG_HEAD, CONTRACTS, catalog_row, make_project, messages, run_json, write  # noqa: E402
from batuta_lib import contract as core  # noqa: E402


def expect_text(path):
    for line in path.read_text(encoding="utf-8").splitlines()[:4]:
        m = re.match(r"<!--\s*expect:\s*(.*?)\s*-->", line)
        if m:
            return m.group(1)
    return ""


class SizeLint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_project(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def lint(self, *extra):
        return run_json("size", "lint", "--root", self.root, *extra)

    def edit(self, old, new):
        p = self.root / ".batuta/sizing.md"
        write(self.root, ".batuta/sizing.md", p.read_text(encoding="utf-8").replace(old, new))

    def test_valid_project_passes_and_prints_totals_per_unit_and_repository(self):
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))
        text = "\n".join(messages(doc, "OK"))
        self.assertIn("u-pipeline: 9 functions", text)
        self.assertIn("u-api: 8 functions", text)
        self.assertIn("repository alert-triage: 17 functions", text)

    def test_output_satisfies_c20(self):
        _, doc, _ = self.lint()
        schema = core.load_schema(core.find_schema(CONTRACTS, "C20"))
        self.assertEqual(core.validate_instance("C20", doc, schema), [])

    def test_boundary_contract_missing_from_the_catalog_fails(self):
        write(self.root, "docs/contracts/catalog.md", CATALOG_HEAD + catalog_row("alert-event"))
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("alert-list" in m and "catalog" in m for m in messages(doc, "FAIL")), messages(doc))

    def test_unit_depending_on_an_unknown_contract_fails(self):
        self.edit("| u-pipeline | pipeline/, tests/pipeline/ | alert-event |", "| u-pipeline | pipeline/, tests/pipeline/ | ghost-contract |")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("ghost-contract" in m for m in messages(doc, "FAIL")))

    def test_no_catalog_reports_unresolved_rows_with_the_expected_path(self):
        (self.root / "docs/contracts/catalog.md").unlink()
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        fails = messages(doc, "FAIL")
        self.assertTrue(any("docs/contracts/catalog.md" in m and "alert-event" in m for m in fails), fails)

    def test_overlapping_write_scopes_fail(self):
        self.edit("| u-api | api/, tests/api/ |", "| u-api | pipeline/, tests/api/ |")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("overlap" in m.lower() or "scope" in m.lower() for m in messages(doc, "FAIL")), messages(doc))

    def test_component_without_a_unit_warns_and_never_fails(self):
        self.edit(" (unit: u-api)", "")
        code, doc, _ = self.lint()
        self.assertEqual(code, 2)
        self.assertEqual(messages(doc, "FAIL"), [])
        self.assertTrue(any("alerts-api" in m and "unit" in m for m in messages(doc, "WARN")), messages(doc))

    def test_every_valid_c23_fixture_passes_with_no_fail_line(self):
        from batuta_lib import spec_model as sm
        for fx in sorted((CONTRACTS / "fixtures" / "C23").glob("valid-*.md")):
            with self.subTest(fixture=fx.name):
                text = fx.read_text(encoding="utf-8")
                ids = {r["Contract ID"] for r in sm.read_rows("C23", "Boundaries", text, True)}
                for u in sm.read_rows("C23", "Parallel units", text, True):
                    ids.update(u["Depends on contract ids"])
                write(self.root, "docs/contracts/catalog.md", CATALOG_HEAD + "".join(catalog_row(i) for i in sorted(ids)))
                code, doc, _ = run_json("size", "lint", "--sizing", fx, "--root", self.root)
                self.assertIn(code, (0, 2))
                self.assertEqual(messages(doc, "FAIL"), [])

    def test_component_naming_a_unit_that_does_not_exist_fails(self):
        self.edit("(unit: u-api)", "(unit: u-nowhere)")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("u-nowhere" in m for m in messages(doc, "FAIL")))

    def test_component_named_in_a_module_row_has_a_unit(self):
        self.edit(" (unit: u-api)", "")
        self.edit("| api/routes.py | serve alerts |", "| api/routes.py | the alerts-api routes |")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_range_version_fails_through_c23(self):
        self.edit("| 3.13.1 |", "| >=3.13 |")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_explicit_paths_are_accepted(self):
        code, doc, _ = run_json("size", "lint", "--sizing", self.root / ".batuta/sizing.md",
                                "--catalog", self.root / "docs/contracts/catalog.md")
        self.assertEqual(code, 0, messages(doc))

    def test_missing_sizing_fails_naming_the_expected_places(self):
        (self.root / ".batuta/sizing.md").unlink()
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("sizing.md" in m for m in messages(doc, "FAIL")))

    def test_invalid_c23_fixtures_are_rejected_for_their_stated_reason(self):
        for fx in sorted((CONTRACTS / "fixtures" / "C23").glob("invalid-*.md")):
            with self.subTest(fixture=fx.name):
                code, doc, _ = run_json("size", "lint", "--sizing", fx, "--catalog", self.root / "docs/contracts/catalog.md")
                self.assertEqual(code, 1)
                self.assertIn(expect_text(fx).lower(), " ".join(messages(doc, "FAIL")).lower())


if __name__ == "__main__":
    unittest.main()
