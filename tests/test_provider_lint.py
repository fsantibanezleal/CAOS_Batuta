"""provider lint: every component that can be absent declares its availability states, each with a test."""
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import CONTRACTS, Case, catalog_row, run  # noqa: E402

HEAD = ("| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | "
        "provider | swap test | model io | status |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n")


def model_row(cid, behavior, io="docs/contracts/examples/widget.json", provider="baseline:docs/contracts/examples/widget.json"):
    cells = [cid, "1.0.0", "core", "contracts/C01-widget.schema.json", "docs/contracts/examples/widget.json",
             "tests/test_widget_producer.py", "tests/test_widget_consumer.py", behavior, provider,
             "tests/test_widget_swap.py", io, "active"]
    return "| " + " | ".join(cells) + " |"


STATES = ("available: ok (test: tests/test_widget_consumer.py::test_available); "
          "provider(fixture): degraded (test: tests/test_widget_consumer.py::test_provider); "
          "missing: reason shown (test: tests/test_widget_consumer.py::test_missing)")


class ProviderLint(Case):
    def setUp(self):
        super().setUp()
        self.proj = self.project(git=False)
        self.proj.catalog()

    def lint(self, *extra):
        return run("provider", "lint", "--root", str(self.proj.root), *extra)

    def write_catalog(self, rows, head=None):
        self.proj.catalog([r for r in rows])   # writes the test files too
        if head:
            self.proj.write("docs/contracts/catalog.md", "# Catalog\n\n" + head + "".join(r + "\n" for r in rows))

    def test_a_compliant_catalog_passes(self):
        code, out = self.lint()
        self.assertEqual(0, code, out)
        self.assertIn("widget-event", out)

    def test_every_state_names_a_test_that_exists(self):
        row = catalog_row("widget-event", behavior=STATES.replace("tests/test_widget_consumer.py::test_missing", "tests/test_nowhere.py::test_missing"))
        self.write_catalog([row])
        code, out = self.lint()
        self.assertEqual(1, code, out)
        self.assertIn("tests/test_nowhere.py", out)

    def test_a_named_test_must_exist_in_its_file(self):
        row = catalog_row("widget-event", behavior=STATES.replace("::test_missing", "::test_not_written"))
        self.write_catalog([row])
        code, out = self.lint()
        self.assertEqual(1, code, out)
        self.assertIn("test_not_written", out)

    def test_two_states_may_not_share_one_test(self):
        row = catalog_row("widget-event", behavior=STATES.replace("::test_missing", "::test_provider"))
        self.write_catalog([row])
        code, out = self.lint()
        self.assertEqual(1, code, out)
        self.assertIn("test_provider", out)

    def test_a_row_with_only_the_available_state_is_refused_by_the_catalog_contract(self):
        row = catalog_row("widget-event", behavior="available: ok (test: tests/test_widget_consumer.py::test_available)")
        self.write_catalog([row])
        code, out = self.lint()
        self.assertEqual(1, code, out)
        self.assertIn("at least one state other than 'available'", out)

    def test_a_state_without_a_test_is_refused_by_the_catalog_contract(self):
        row = catalog_row("widget-event", behavior="available: ok; missing: reason shown")
        self.write_catalog([row])
        self.assertEqual(1, self.lint()[0])

    def test_a_declared_provider_needs_its_provider_state(self):
        row = catalog_row("widget-event", behavior=("available: ok (test: tests/test_widget_consumer.py::test_available); "
                                                    "missing: reason shown (test: tests/test_widget_consumer.py::test_missing)"))
        self.write_catalog([row])
        code, out = self.lint()
        self.assertEqual(1, code, out)
        self.assertIn("provider(fixture)", out)

    def test_the_provider_state_names_the_kind_of_the_provider_column(self):
        row = catalog_row("widget-event", provider="stub:docs/contracts/examples/widget.json")
        self.write_catalog([row])
        code, out = self.lint()
        self.assertEqual(1, code, out)
        self.assertIn("stub", out)

    def test_the_provider_path_must_exist(self):
        row = catalog_row("widget-event", provider="fixture:docs/contracts/examples/absent.json")
        self.write_catalog([row])
        code, out = self.lint()
        self.assertEqual(1, code, out)
        self.assertIn("absent.json", out)

    def test_a_model_slot_without_a_training_state_is_a_warning(self):
        self.write_catalog([model_row("grade-model", STATES.replace("provider(fixture)", "provider(baseline)"))], head=HEAD)
        code, out = self.lint()
        self.assertEqual(2, code, out)
        self.assertIn("training", out)

    def test_a_model_slot_with_a_training_state_passes(self):
        behavior = (STATES.replace("provider(fixture)", "provider(baseline)")
                    + "; training: the released version answers (test: tests/test_widget_consumer.py::test_training)")
        self.write_catalog([model_row("grade-model", behavior)], head=HEAD)
        code, out = self.lint()
        self.assertEqual(0, code, out)

    def test_model_cards_are_validated_when_a_folder_is_given(self):
        card = CONTRACTS / "fixtures" / "C28" / "valid-released.json"
        good = self.proj.root / "models" / "m1"
        good.mkdir(parents=True)
        shutil.copy(card, good / "card.json")
        self.assertEqual(0, self.lint("--models", str(self.proj.root / "models"))[0])
        bad = self.proj.root / "models" / "m2"
        bad.mkdir()
        shutil.copy(CONTRACTS / "fixtures" / "C28" / "invalid-training-without-serving.json", bad / "card.json")
        code, out = self.lint("--models", str(self.proj.root / "models"))
        self.assertEqual(1, code, out)
        self.assertIn("m2", out)

    def test_no_catalog_at_the_default_place_is_a_skip_but_a_named_one_must_exist(self):
        (self.proj.root / "docs" / "contracts" / "catalog.md").unlink()
        code, out = self.lint()
        self.assertEqual(0, code, out)
        self.assertIn("SKIP", out)
        code, out = self.lint("--catalog", "docs/contracts/catalog.md")
        self.assertEqual(1, code, out)

    def test_a_file_without_a_catalog_table_is_refused(self):
        self.proj.write("docs/contracts/catalog.md", "# Catalog\n\nnothing here\n")
        self.assertEqual(1, self.lint()[0])

    def test_json_output(self):
        code, out = self.lint("--json")
        self.assertEqual(["provider", "lint"], [json.loads(out)["area"], json.loads(out)["verb"]])


class ProviderCheck(Case):
    def setUp(self):
        super().setUp()
        self.proj = self.project(git=False)
        self.proj.catalog()

    def response(self, doc, name="response.json"):
        return self.proj.write(name, json.dumps(doc) if not isinstance(doc, str) else doc)

    def check(self, path, *extra):
        return run("provider", "check", "--response", str(path), *extra)

    def fixture(self, name):
        return CONTRACTS / "fixtures" / "C26" / name

    def test_every_valid_runtime_block_fixture_passes(self):
        for path in sorted((CONTRACTS / "fixtures" / "C26").glob("valid-*.json")):
            code, out = self.check(path)
            self.assertEqual(0, code, (path.name, out))

    def test_every_invalid_runtime_block_fixture_is_refused(self):
        for path in sorted((CONTRACTS / "fixtures" / "C26").glob("invalid-*.json")):
            code, out = self.check(path)
            self.assertEqual(1, code, (path.name, out))

    def test_a_provider_answer_without_its_provenance_is_refused(self):
        code, out = self.check(self.fixture("invalid-runtime-provider-without-provenance.json"))
        self.assertEqual(1, code, out)
        self.assertIn("provenance", out)

    def test_a_provider_answer_claiming_to_be_real_is_refused(self):
        doc = json.loads(self.fixture("valid-runtime-provider.json").read_text(encoding="utf-8"))
        doc["provenance"] = "real"
        code, out = self.check(self.response(doc))
        self.assertEqual(1, code, out)

    def test_a_block_inside_a_response_is_found(self):
        doc = {"rows": [1, 2], "availability": json.loads(self.fixture("valid-runtime-stale-bilingual-reason.json").read_text(encoding="utf-8"))}
        self.assertEqual(0, self.check(self.response(doc))[0])

    def test_a_response_without_a_block_is_refused(self):
        code, out = self.check(self.response({"rows": [1, 2]}))
        self.assertEqual(1, code, out)
        self.assertIn("availability", out)

    def test_invalid_json_is_refused(self):
        self.assertEqual(1, self.check(self.response("{nope"))[0])

    def test_a_missing_file_is_refused(self):
        self.assertEqual(1, self.check(self.proj.root / "absent.json")[0])

    def test_the_state_must_be_one_the_row_declares(self):
        doc = json.loads(self.fixture("valid-runtime-stale-bilingual-reason.json").read_text(encoding="utf-8"))
        code, out = self.check(self.response(doc), "--root", str(self.proj.root), "--id", "widget-event")
        self.assertEqual(1, code, out)
        self.assertIn("stale", out)
        self.assertIn("declares", out)

    def test_a_declared_state_passes_with_the_catalog(self):
        for name in ("valid-runtime-available.json", "valid-runtime-provider.json", "valid-runtime-missing.json"):
            code, out = self.check(self.fixture(name), "--root", str(self.proj.root), "--id", "widget-event")
            self.assertEqual(0, code, (name, out))

    def test_the_provider_kind_must_be_the_declared_one(self):
        code, out = self.check(self.fixture("valid-runtime-provider-baseline.json"), "--root", str(self.proj.root), "--id", "widget-event")
        self.assertEqual(1, code, out)
        self.assertIn("baseline", out)

    def test_an_unknown_row_id_is_refused(self):
        code, out = self.check(self.fixture("valid-runtime-available.json"), "--root", str(self.proj.root), "--id", "nope")
        self.assertEqual(1, code, out)

    def test_id_is_required_with_a_catalog(self):
        code, out = self.check(self.fixture("valid-runtime-available.json"), "--catalog", "docs/contracts/catalog.md", "--root", str(self.proj.root))
        self.assertEqual(1, code, out)

    def test_without_a_catalog_the_declared_states_are_not_checked_and_that_is_said(self):
        code, out = self.check(self.fixture("valid-runtime-available.json"))
        self.assertEqual(0, code, out)
        self.assertIn("not checked", out)


if __name__ == "__main__":
    unittest.main()
