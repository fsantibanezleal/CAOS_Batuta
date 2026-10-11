"""The contract area: lint, validate, graph through main(argv); module layout contract; C20 output."""
import argparse
import contextlib
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "harness" / "scripts"))

from harness_lib import contract  # noqa: E402
from harness_lib.areas import contract as area  # noqa: E402

G = ROOT / "tests" / "contracts" / "graph"


def call(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = area.main(list(argv))
    return code, buf.getvalue()


class ModuleLayout(unittest.TestCase):
    def test_area_module_contract(self):
        self.assertEqual(area.AREA, "contract")
        self.assertIsInstance(area.HELP, str)
        self.assertTrue(area.HELP)
        self.assertTrue(callable(area.register))

    def test_register_adds_the_three_verbs(self):
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers(dest="verb")
        area.register(subs)
        self.assertEqual(set(subs.choices), {"lint", "validate", "graph"})
        args = parser.parse_args(["graph", "--tasks", "t.md", "--interfaces", "s.md"])
        self.assertTrue(callable(args.func))


class Lint(unittest.TestCase):
    def test_lint_of_this_repository_is_clean(self):
        code, out = call("lint", "--root", str(ROOT))
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)
        self.assertIn("OK", out)

    def test_lint_json_is_a_valid_c20_object(self):
        code, out = call("lint", "--root", str(ROOT), "--json")
        obj = json.loads(out)
        c20 = contract.load_schema(ROOT / "contracts" / "C20-cli-output.schema.json")
        self.assertEqual(contract.validate(obj, c20), [])
        self.assertEqual((obj["area"], obj["verb"], obj["exit_code"]), ("contract", "lint", code))

    def test_lint_reports_a_fixture_that_does_not_behave_as_labeled(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(ROOT / "contracts", root / "contracts")
            bad = root / "contracts" / "fixtures" / "C01" / "valid-minimal.json"
            doc = json.loads(bad.read_text(encoding="utf-8"))
            del doc["roots"]
            bad.write_text(json.dumps(doc), encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("FAIL", out)
            self.assertIn("C01/valid-minimal.json", out)

    def test_lint_reports_an_invalid_fixture_that_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(ROOT / "contracts", root / "contracts")
            src = root / "contracts" / "fixtures" / "C01" / "valid-full.json"
            shutil.copy(src, root / "contracts" / "fixtures" / "C01" / "invalid-actually-fine.json")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("invalid-actually-fine.json", out)

    def test_lint_reports_an_invalid_fixture_without_a_stated_reason(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(ROOT / "contracts", root / "contracts")
            p = root / "contracts" / "fixtures" / "C01" / "invalid-missing-root-temp.json"
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc.pop("_why")
            p.write_text(json.dumps(doc), encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("states no reason", out)

    def test_lint_reports_an_unsupported_keyword_in_a_schema(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(ROOT / "contracts", root / "contracts")
            p = root / "contracts" / "C14-context-budget.schema.json"
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc["oneOf"] = []
            p.write_text(json.dumps(doc), encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("unsupported keyword", out)

    def test_lint_requires_catalog_entries(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(ROOT / "contracts", root / "contracts")
            readme = root / "contracts" / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8").replace("C07", "CXX"), encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("C07", out)
            self.assertIn("catalog", out)

    def test_lint_checks_the_c01_budgets_block_equals_c14(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(ROOT / "contracts", root / "contracts")
            p = root / "contracts" / "C14-context-budget.schema.json"
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc["required"] = doc["required"][:-1]
            p.write_text(json.dumps(doc), encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("C14", out)
            self.assertIn("C01", out)

    def _spec_root(self, d, row):
        root = pathlib.Path(d)
        shutil.copytree(ROOT / "contracts", root / "contracts")
        spec = root / "specs" / "001-x"
        spec.mkdir(parents=True)
        (spec / "spec.md").write_text(
            "---\nid: 001-x\n---\n\n## Interfaces\n\n| Interface | Contract file | Producer | Consumers | Version |\n|---|---|---|---|---|\n"
            + row + "\n", encoding="utf-8")
        return root

    def test_lint_resolves_c22_rows_in_specs(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._spec_root(d, "| config | contracts/C01-harness-config.schema.json | init | all | 1.0 |")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 0, out)
            self.assertIn("001-x", out)

    def test_lint_fails_on_a_c22_row_whose_contract_file_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._spec_root(d, "| config | contracts/NOPE.schema.json | init | all | 1.0 |")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("NOPE.schema.json", out)

    def test_lint_fails_on_an_invalid_c22_row(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._spec_root(d, "| config | contracts/C01-harness-config.schema.json | init | all | v1 |")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("/Version", out)

    def test_lint_without_contracts_folder_fails(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = call("lint", "--root", d)
            self.assertEqual(code, 1)
            self.assertIn("contracts", out)


class Validate(unittest.TestCase):
    def test_validate_ok_and_fail(self):
        good = ROOT / "contracts" / "fixtures" / "C01" / "valid-full.json"
        bad = ROOT / "contracts" / "fixtures" / "C01" / "invalid-missing-root-temp.json"
        code, out = call("validate", "C01", str(good), "--root", str(ROOT))
        self.assertEqual(code, 0, out)
        self.assertIn("OK", out)
        code, out = call("validate", "C01", str(bad), "--root", str(ROOT))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertIn("'temp'", out)

    def test_validate_markdown_and_jsonl(self):
        code, _ = call("validate", "C02", str(ROOT / "contracts" / "fixtures" / "C02" / "valid-implement.md"), "--root", str(ROOT))
        self.assertEqual(code, 0)
        code, _ = call("validate", "C04", str(ROOT / "contracts" / "fixtures" / "C04" / "valid-two-rows.jsonl"), "--root", str(ROOT))
        self.assertEqual(code, 0)

    def test_validate_unknown_contract_or_file_fails(self):
        f = ROOT / "contracts" / "fixtures" / "C01" / "valid-full.json"
        self.assertEqual(call("validate", "C99", str(f), "--root", str(ROOT))[0], 1)
        self.assertEqual(call("validate", "C01", str(f) + ".nope", "--root", str(ROOT))[0], 1)

    def test_validate_json_output(self):
        f = ROOT / "contracts" / "fixtures" / "C01" / "valid-full.json"
        code, out = call("validate", "C01", str(f), "--root", str(ROOT), "--json")
        obj = json.loads(out)
        self.assertEqual((obj["verb"], obj["exit_code"]), ("validate", 0))


class Graph(unittest.TestCase):
    def test_graph_exit_codes(self):
        base = ["graph", "--interfaces", str(G / "interfaces-frozen.md"), "--root", str(G)]
        self.assertEqual(call(*base, "--tasks", str(G / "tasks-parallel.md"))[0], 0)
        self.assertEqual(call(*base, "--tasks", str(G / "tasks-coupling.md"))[0], 2)
        code, out = call(*base, "--tasks", str(G / "tasks-cycle.md"))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_graph_output_lists_waves(self):
        code, out = call("graph", "--tasks", str(G / "tasks-ordered.md"), "--interfaces", str(G / "interfaces-frozen.md"), "--root", str(G))
        self.assertIn("OK wave 1: T-001", out)
        self.assertIn("OK wave 3: T-003", out)

    def test_graph_json_output_validates_as_c20(self):
        code, out = call("graph", "--tasks", str(G / "tasks-coupling.md"), "--interfaces", str(G / "interfaces-frozen.md"),
                         "--root", str(G), "--json")
        obj = json.loads(out)
        c20 = contract.load_schema(ROOT / "contracts" / "C20-cli-output.schema.json")
        self.assertEqual(contract.validate(obj, c20), [])
        self.assertEqual(obj["exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
