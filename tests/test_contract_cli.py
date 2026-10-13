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
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib import contract  # noqa: E402
from batuta_lib.areas import contract as area  # noqa: E402

OWN = ROOT / "plugins" / "batuta" / "contracts"
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
        args = parser.parse_args(["graph", "--catalog", "c.md", "--tasks", "t.md"])
        self.assertTrue(callable(args.func))


class Lint(unittest.TestCase):
    def test_lint_of_this_repository_is_clean(self):
        code, out = call("lint")
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)
        self.assertIn("OK", out)

    def test_lint_json_is_a_valid_c20_object(self):
        code, out = call("lint", "--json")
        obj = json.loads(out)
        c20 = contract.load_schema(OWN / "C20-cli-output.schema.json")
        self.assertEqual(contract.validate(obj, c20), [])
        self.assertEqual((obj["area"], obj["verb"], obj["exit_code"]), ("contract", "lint", code))

    def test_lint_reports_a_fixture_that_does_not_behave_as_labeled(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(OWN, root / "contracts")
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
            shutil.copytree(OWN, root / "contracts")
            src = root / "contracts" / "fixtures" / "C01" / "valid-full.json"
            shutil.copy(src, root / "contracts" / "fixtures" / "C01" / "invalid-actually-fine.json")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("invalid-actually-fine.json", out)

    def test_lint_reports_an_invalid_fixture_without_a_stated_reason(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(OWN, root / "contracts")
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
            shutil.copytree(OWN, root / "contracts")
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
            shutil.copytree(OWN, root / "contracts")
            readme = root / "contracts" / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8").replace("C07", "CXX"), encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("C07", out)
            self.assertIn("catalog", out)

    def test_lint_checks_the_c01_budgets_block_equals_c14(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(OWN, root / "contracts")
            p = root / "contracts" / "C14-context-budget.schema.json"
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc["required"] = doc["required"][:-1]
            p.write_text(json.dumps(doc), encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("C14", out)
            self.assertIn("C01", out)

    def _project(self, d, interfaces="- alert-event: produced by the pipeline\n"):
        root = pathlib.Path(d)
        (root / "docs" / "contracts").mkdir(parents=True)
        for rel in ("docs/contracts/alert-event.schema.json", "docs/contracts/alert-event.json", "tests/p.py", "tests/c.py", "tests/s.py",
                    "tests/fixtures/alert-event.json"):
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("{}", encoding="utf-8")
        (root / "docs" / "contracts" / "catalog.md").write_text(
            "| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io | swap test | status |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
            "| alert-event | 1.0.0 | u-api | docs/contracts/alert-event.schema.json | docs/contracts/alert-event.json | tests/p.py | tests/c.py "
            "| available: ok (test: t/a.py); missing: drop it (test: t/a.py) | fixture:tests/fixtures/alert-event.json | - | tests/s.py | active |\n", encoding="utf-8")
        spec = root / "specs" / "001-x"
        spec.mkdir(parents=True)
        (spec / "spec.md").write_text(
            "---\nid: 001-x\ntitle: T\nstatus: Frozen\ntier: S\nowner: me\ncreated: 2026-10-12\n---\n\n## Problem\n\nx\n\n"
            "## Scope and out of scope\n\nx\n\n## Requirements\n\n| Id | Kind | EARS text | Gate | Verification | Status |\n|---|---|---|---|---|---|\n"
            "| REQ-X-001 | ubiquitous | The thing shall work. | pytest | test | active |\n\n## Interfaces\n\n" + interfaces +
            "\n## Edge cases\n\nx\n\n## Open questions\n\nNone.\n", encoding="utf-8")
        return root

    def test_project_lint_resolves_the_catalog_and_the_spec_interfaces(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._project(d)
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 0, out)
            self.assertIn("catalog.md satisfies C22", out)
            self.assertIn("001-x", out)

    def test_project_lint_fails_on_a_catalog_path_that_does_not_exist(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._project(d)
            (root / "tests" / "p.py").unlink()
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("producer test path not found: tests/p.py", out)

    def test_project_lint_fails_on_an_interface_that_is_not_a_catalog_row(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._project(d, "- alert-event\n- alert-list\n")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("interface 'alert-list' is not a row of the catalog", out)

    def test_project_lint_fails_on_an_invalid_catalog_row(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._project(d)
            cat = root / "docs" / "contracts" / "catalog.md"
            cat.write_text(cat.read_text(encoding="utf-8").replace("| 1.0.0 |", "| 1.0 |"), encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("/version", out)

    def test_lint_without_contracts_folder_fails(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = call("lint", "--root", d)
            self.assertEqual(code, 1)
            self.assertIn("contracts", out)


class PluginResolution(unittest.TestCase):
    """Batuta's own contracts resolve inside the plugin, whatever the working directory or install location."""

    def test_own_contracts_dir_is_inside_the_plugin(self):
        self.assertEqual(area._own_contracts_dir().resolve(), OWN.resolve())

    def test_lint_without_root_does_not_depend_on_the_working_directory(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                code, out = call("lint")
            finally:
                os.chdir(old)
        self.assertEqual(code, 0, out)

    def test_lint_without_root_ignores_a_contracts_folder_in_the_working_directory(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "contracts").mkdir()
            old = os.getcwd()
            os.chdir(d)
            try:
                code, out = call("lint")
            finally:
                os.chdir(old)
        self.assertEqual(code, 0, out)
        self.assertIn("C01", out)

    def test_validate_resolves_a_batuta_contract_without_root_from_anywhere(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                code, out = call("validate", "C01", str(OWN / "fixtures" / "C01" / "valid-full.json"))
            finally:
                os.chdir(old)
        self.assertEqual(code, 0, out)

    def test_validate_with_root_prefers_the_project_contract_then_the_plugin(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "contracts").mkdir()
            (root / "contracts" / "C90-thing.schema.json").write_text(json.dumps(
                {"contract_id": "C90", "contract_version": "1.0", "type": "object", "required": ["a"]}), encoding="utf-8")
            doc = root / "thing.json"
            doc.write_text("{}", encoding="utf-8")
            self.assertEqual(call("validate", "C90", str(doc), "--root", str(root))[0], 1)
            doc.write_text('{"a": 1}', encoding="utf-8")
            self.assertEqual(call("validate", "C90", str(doc), "--root", str(root))[0], 0)
            good = OWN / "fixtures" / "C01" / "valid-full.json"
            self.assertEqual(call("validate", "C01", str(good), "--root", str(root))[0], 0)

    def test_the_plugin_folder_alone_lints_clean(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            dst = pathlib.Path(d) / "batuta"
            shutil.copytree(OWN.parent, dst, ignore=shutil.ignore_patterns("__pycache__"))
            r = subprocess.run([sys.executable, str(dst / "scripts" / "batuta.py"), "contract", "lint"],
                               capture_output=True, text=True, cwd=d)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("C27", r.stdout)

    def test_project_lint_checks_a_sizing_found_under_the_coordination_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / ".batuta").mkdir()
            (root / ".batuta" / "sizing.md").write_text("# Sizing\n\n## Problem\nx\n", encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("Reservations", out)
            shutil.copy(OWN / "fixtures" / "C23" / "valid-product-sizing.md", root / ".batuta" / "sizing.md")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 0, out)
            self.assertIn("satisfies C23", out)

    def test_project_lint_checks_the_readiness_document(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "data" / "derived").mkdir(parents=True)
            target = root / "data" / "derived" / "readiness.json"
            shutil.copy(OWN / "fixtures" / "C27" / "valid-template-readiness.json", target)
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 0, out)
            self.assertIn("readiness.json satisfies C27", out)
            doc = json.loads(target.read_text(encoding="utf-8"))
            doc["contracts"][0]["state"] = "synthetic"
            target.write_text(json.dumps(doc), encoding="utf-8")
            self.assertEqual(call("lint", "--root", str(root))[0], 1)

    def test_a_project_configuration_is_checked_as_c01(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / ".batuta").mkdir()
            cfg = root / ".batuta" / "batuta.json"
            shutil.copy(OWN / "fixtures" / "C01" / "valid-full.json", cfg)
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 0, out)
            self.assertIn("batuta.json satisfies C01", out)
            doc = json.loads(cfg.read_text(encoding="utf-8"))
            del doc["roots"]
            cfg.write_text(json.dumps(doc), encoding="utf-8")
            self.assertEqual(call("lint", "--root", str(root))[0], 1)

    def test_a_stale_readiness_document_warns(self):
        with tempfile.TemporaryDirectory() as d:
            root = Lint._project(self, d)
            (root / "data" / "derived").mkdir(parents=True)
            doc = {"schema": "x.readiness/v1", "product_version": "0.01.000", "catalog_sha256": "0" * 64, "contracts": [
                {"id": "alert-event", "version": "1.0.0", "status": "active", "provenance": "fixture", "state": "provider",
                 "reason": {"en": "served by its provider", "es": "lo sirve su proveedor"}, "missing": []}]}
            (root / "data" / "derived" / "readiness.json").write_text(json.dumps(doc), encoding="utf-8")
            code, out = call("lint", "--root", str(root))
            self.assertEqual(code, 2, out)
            self.assertIn("stale", out)


class Validate(unittest.TestCase):
    def test_validate_ok_and_fail(self):
        good = OWN / "fixtures" / "C01" / "valid-full.json"
        bad = OWN / "fixtures" / "C01" / "invalid-missing-root-temp.json"
        code, out = call("validate", "C01", str(good))
        self.assertEqual(code, 0, out)
        self.assertIn("OK", out)
        code, out = call("validate", "C01", str(bad))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertIn("'temp'", out)

    def test_validate_markdown_and_jsonl(self):
        code, _ = call("validate", "C02", str(OWN / "fixtures" / "C02" / "valid-implement-from-delegation-new.md"))
        self.assertEqual(code, 0)
        code, _ = call("validate", "C04", str(OWN / "fixtures" / "C04" / "valid-drafted-pending-complete-accepted.md"))
        self.assertEqual(code, 0)

    def test_validate_unknown_contract_or_file_fails(self):
        f = OWN / "fixtures" / "C01" / "valid-full.json"
        self.assertEqual(call("validate", "C99", str(f))[0], 1)
        self.assertEqual(call("validate", "C01", str(f) + ".nope")[0], 1)

    def test_validate_json_output(self):
        f = OWN / "fixtures" / "C01" / "valid-full.json"
        code, out = call("validate", "C01", str(f), "--json")
        obj = json.loads(out)
        self.assertEqual((obj["verb"], obj["exit_code"]), ("validate", 0))


class Graph(unittest.TestCase):
    CAT = ("| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io "
           "| swap test | status | frozen |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
           "| a-contract | 1.0.0 | u-1 | s.json | e.json | p.py | c.py | available: ok (test: t/a.py); missing: drop it (test: t/a.py) | fixture:f.json | - | s.py | active | yes |\n"
           "| b-contract | 1.0.0 | u-1 | s.json | e.json | p.py | c.py | available: ok (test: t/a.py); missing: drop it (test: t/a.py) | fixture:f.json | - | s.py | active | no |\n")
    TASKS = "| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |\n|---|---|---|---|---|---|---|---|\n"

    def _files(self, d, rows):
        d = pathlib.Path(d)
        (d / "catalog.md").write_text(self.CAT, encoding="utf-8")
        (d / "tasks.md").write_text(self.TASKS + rows, encoding="utf-8")
        return str(d / "catalog.md"), str(d / "tasks.md")

    PARALLEL = ("| T-001 | a | REQ-X-001 | a-contract | - |  | implementer | - |\n"
                "| T-002 | b | REQ-X-001 | a-contract | - |  | implementer | - |\n")
    COUPLING = ("| T-001 | a | REQ-X-001 | a-contract | - |  | implementer | - |\n"
                "| T-002 | b | REQ-X-001 | a-contract | T-001 |  | implementer | - |\n")
    CYCLE = ("| T-001 | a | REQ-X-001 | a-contract | T-002 |  | implementer | - |\n"
             "| T-002 | b | REQ-X-001 | a-contract | T-001 |  | implementer | - |\n")

    def test_graph_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            for rows, expected in ((self.PARALLEL, 0), (self.COUPLING, 2), (self.CYCLE, 1)):
                cat, tasks = self._files(d, rows)
                code, out = call("graph", "--catalog", cat, "--tasks", tasks)
                self.assertEqual(code, expected, out)

    def test_graph_output_lists_waves_from_two(self):
        with tempfile.TemporaryDirectory() as d:
            cat, tasks = self._files(d, self.COUPLING)
            code, out = call("graph", "--catalog", cat, "--tasks", tasks)
            self.assertIn("OK wave 0: a-contract", out)
            self.assertIn("OK wave 1: walking skeleton", out)
            self.assertIn("OK wave 2: T-001", out)
            self.assertIn("OK wave 3: T-002", out)

    def test_graph_json_output_validates_as_c20(self):
        with tempfile.TemporaryDirectory() as d:
            cat, tasks = self._files(d, self.COUPLING)
            code, out = call("graph", "--catalog", cat, "--tasks", tasks, "--json")
        obj = json.loads(out)
        c20 = contract.load_schema(OWN / "C20-cli-output.schema.json")
        self.assertEqual(contract.validate(obj, c20), [])
        self.assertEqual((obj["verb"], obj["exit_code"]), ("graph", 2))

    def test_graph_with_a_sizing_prints_the_unit_waves(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            shutil.copy(OWN / "fixtures" / "C23" / "valid-product-sizing.md", d / "sizing.md")
            rows = "".join(f"| {i} | 1.0.0 | {o} | s.json | e.json | p.py | c.py | available: ok (test: t/a.py); missing: drop it (test: t/a.py) | fixture:f.json | - | s.py | active | no |\n"
                           for i, o in (("alert-event", "u-pipeline"), ("alert-list", "u-api"), ("severity-score", "u-model")))
            (d / "catalog.md").write_text(self.CAT.split("| a-contract")[0] + rows, encoding="utf-8")
            code, out = call("graph", "--catalog", str(d / "catalog.md"), "--sizing", str(d / "sizing.md"))
            self.assertEqual(code, 0, out)
            self.assertIn("OK wave 2: u-model", out)
            self.assertIn("OK wave 5: u-ui", out)

    def test_graph_needs_a_catalog(self):
        code, out = call("graph")
        self.assertEqual(code, 1)
        self.assertIn("--catalog", out)


if __name__ == "__main__":
    unittest.main()
