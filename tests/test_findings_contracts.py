"""The reproductions of the adversarial review findings F01 to F31 (contracts, U0 revision 2), one test per finding.

Each test is the review's reproduction turned into an assertion: it failed on the tree before the revision and passes
after it. Test names start with the finding id so the re-check table can name them.
"""
import copy
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

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"
FX = CONTRACTS / "fixtures"


def sp(cid):
    found = sorted(CONTRACTS.glob(f"{cid}-*.schema.json"))
    return found[0] if found else None


def read(cid, name):
    return (FX / cid / name).read_text(encoding="utf-8")


def load(cid, name):
    return json.loads(read(cid, name))


def inspect_source(fn):
    import inspect
    return inspect.getsource(fn)


def check_text(cid, text, name=None, root=None):
    """Validate text as contract `cid` through the file path the CLI uses."""
    ext = {"C32": ".txt"}.get(cid, ".md" if list(CONTRACTS.glob(f"{cid}-*.sections.json")) else ".json")
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / (name or f"artifact{ext}")
        p.write_text(text, encoding="utf-8", newline="")
        return contract.validate_file(p, sp(cid), cid)


def check_doc(cid, doc):
    return check_text(cid, json.dumps(doc))


def cli(*argv):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = area.main(list(argv))
    return code, buf.getvalue()


class Critical(unittest.TestCase):
    def test_F01_c23_is_the_markdown_contract_of_sizing_md_not_a_machine_readable_inventory(self):
        self.assertFalse(list(CONTRACTS.glob("C23-inventory*")), "the withdrawn inventory schema is gone")
        self.assertTrue(sp("C23").name.startswith("C23-sizing"))
        spec = json.loads(sp("C23").with_name("C23-sizing.sections.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["required_sections"], ["Problem", "Executive brief", "ADR constraints", "Repositories", "Components", "Modules and functions",
                                                     "Boundaries", "Technology matrix", "Machine limits", "Parallel units",
                                                     "Integrator and merge order", "Reservations"])
        self.assertEqual([t["name"] for t in spec["tables"]], ["Modules and functions", "Boundaries", "Technology matrix", "Parallel units"])
        text = read("C23", "valid-product-sizing.md")
        self.assertEqual(check_text("C23", text), [])
        overlapping = text.replace("| u-ui | ui/ | alert-list |", "| u-ui | ui/, api/routes/ | alert-list |")
        self.assertTrue(any("write scopes overlap" in e for e in check_text("C23", overlapping)))
        self.assertTrue(any("Reservations" in e for e in check_text("C23", text.replace("\n## Reservations\nnone\n", "\n"))))

    def test_F01_the_area_has_no_inventory_code_left(self):
        for name in ("unit_providers", "_check_c23"):
            self.assertFalse(hasattr(contract, name), name)
        for name in ("graph_inventory", "load_inventory", "INVENTORY_PATHS"):
            self.assertFalse(hasattr(area, name), name)

    def test_F02_c22_is_the_catalog_contract_and_accepts_the_templates_semver_row(self):
        header = ("| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io "
                  "| swap test | status |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        row = ('| alert-event | 1.0.0 | unit | docs/contracts/alert-event.schema.json | docs/contracts/examples/alert-event.json | '
               'tests/contracts/test_alert_producer.py::test_schema | tests/contracts/test_alert_consumer.py::test_schema | '
               'available: ok (test: t/a.py); missing: drop the event (test: t/a.py) | fixture:tests/fixtures/alert-event.json | - | '
               'tests/contracts/test_alert_swap.py | active |\n')
        self.assertTrue(sp("C22").name.startswith("C22-catalog"))
        self.assertEqual(check_text("C22", header + row), [])
        self.assertTrue(any("/version" in e for e in check_text("C22", header + row.replace("| 1.0.0 |", "| 1.0 |"))))
        model = row.replace("alert-event", "severity").replace("| - |", "| in: a, out: b |")
        self.assertTrue(any("baseline provider" in e for e in check_text("C22", header + model)))
        self.assertEqual(check_text("C22", header + model.replace("fixture:tests/fixtures/severity.json", "baseline:models/b.py")), [])
        self.assertTrue(any("duplicate" in e for e in check_text("C22", header + row + row)))

    def test_F02_the_catalog_paths_must_exist_under_the_root(self):
        with tempfile.TemporaryDirectory() as d:
            cat = pathlib.Path(d) / "catalog.md"
            cat.write_text(read("C22", "valid-template-example-row.md"), encoding="utf-8")
            code, out = cli("validate", "C22", str(cat), "--root", d)
            self.assertEqual(code, 1)
            self.assertIn("schema file path not found", out)
            self.assertEqual(cli("validate", "C22", str(cat))[0], 0)


class Major(unittest.TestCase):
    def test_F03_c21_names_catalog_ids_and_one_wave_numbering(self):
        text = read("C21", "valid-tasks-with-catalog-ids.md")
        self.assertEqual(check_text("C21", text), [])
        self.assertTrue(check_text("C21", text.replace("| alert-event, severity-score |", "| docs/contracts/alert-event.schema.json |")))
        self.assertTrue(any("/Wave" in e for e in check_text("C21", text.replace("| 3 | implementer | u-pipeline |", "| 1 | implementer | u-pipeline |"))))

    def test_F03_a_task_reports_the_wave_of_its_unit_in_the_same_numbering(self):
        sizing = read("C23", "valid-product-sizing.md")
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "sizing.md").write_text(sizing, encoding="utf-8")
            (d / "catalog.md").write_text(
                "| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io | swap test | status | frozen |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n" + "".join(
                    f"| {i} | 1.0.0 | {o} | s | e | p | c | available: ok (test: t/a.py); missing: drop (test: t/a.py) | fixture:f | - | w | active | no |\n"
                    for i, o in (("alert-event", "u-pipeline"), ("alert-list", "u-api"), ("severity-score", "u-model"))), encoding="utf-8")
            (d / "tasks.md").write_text(
                "| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |\n|---|---|---|---|---|---|---|---|\n"
                "| T-001 | x | REQ-X-001 | alert-list | - |  | implementer | u-api |\n", encoding="utf-8")
            items = area.graph(d / "catalog.md", d / "sizing.md", d / "tasks.md")
        msgs = [i["message"] for i in items]
        self.assertIn("wave 4: u-api", msgs)
        self.assertIn("task T-001 runs in unit u-api (wave 4)", msgs)

    def test_F04_c25_refuses_ranges_and_needs_source_and_date_and_a_passed_spike_for_a_risky_choice(self):
        row = load("C25", "valid-matrix-row-only.json")
        for bad in ("1.x", "1.0-2.0", "3+", "^1.2.3", ">=2", "3"):
            with self.subTest(version=bad):
                self.assertTrue(check_doc("C25", {**row, "version": bad}), bad)
        self.assertEqual(check_doc("C25", {**row, "version": "2.0.0-rc.1"}), [])
        self.assertTrue(check_doc("C25", {k: v for k, v in row.items() if k != "verified_date"}))
        self.assertTrue(check_doc("C25", {**row, "primary_source_url": "the docs"}))
        risky = load("C25", "invalid-risky-choice-with-a-failed-spike.json")
        risky = {k: v for k, v in risky.items() if not k.startswith("_")}
        self.assertTrue(any("spike that passed" in e for e in check_doc("C25", risky)))

    def test_F04_the_sizing_technology_matrix_row_has_the_same_rules(self):
        text = read("C23", "valid-product-sizing.md")
        for bad_row in ("| Python | 3.13+ | https://docs.python.org/3.13/ | 2026-10-12 |", "| Python | 3.13.1 | docs | 2026-10-12 |",
                        "| Python | 3.13.1 | https://docs.python.org/3.13/ | someday |"):
            with self.subTest(row=bad_row):
                self.assertTrue(check_text("C23", text.replace("| Python | 3.13.1 | https://docs.python.org/3.13/ | 2026-10-12 |", bad_row)))

    def test_F05_the_template_readiness_document_validates_with_provider_as_the_state(self):
        doc = load("C27", "valid-template-readiness.json")
        self.assertEqual(check_doc("C27", doc), [])
        code, out = cli("validate", "C27", str(FX / "C27" / "valid-template-readiness.json"), "--json")
        obj = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual({i["tag"] for i in obj["items"]}, {"OK"})
        self.assertTrue(check_doc("C27", {**doc, "contracts": [{**doc["contracts"][0], "state": "synthetic"}]}), "no synthetic alias")

    def test_F06_the_availability_states_are_adr_0080s_six_in_every_contract(self):
        states = ["available", "partial", "stale", "provider", "training", "missing"]
        self.assertEqual(json.loads(sp("C26").read_text(encoding="utf-8"))["$defs"]["state"]["enum"], states)
        self.assertEqual(json.loads(sp("C27").read_text(encoding="utf-8"))["$defs"]["entry"]["properties"]["state"]["enum"], states)
        readme = (CONTRACTS / "README.md").read_text(encoding="utf-8")
        self.assertIn("There is no alias", readme)
        provider = json.loads(read("C26", "valid-runtime-provider.json"))
        self.assertEqual(check_doc("C26", provider), [])
        self.assertTrue(check_doc("C26", {k: v for k, v in provider.items() if k != "provenance"}), "a provider answer carries its kind")

    def test_F07_c27_is_as_strict_as_adr_0080_and_the_product_templates_schema(self):
        base = load("C27", "valid-all-six-states.json")
        for key in ("schema", "product_version", "catalog_sha256"):
            with self.subTest(missing=key):
                self.assertTrue(check_doc("C27", {k: v for k, v in base.items() if k != key}))
        e = base["contracts"]
        mutate = lambda i, **ch: {**base, "contracts": [{**e[i], **ch}]}
        self.assertEqual(check_doc("C27", mutate(3, status="simulator", provenance="simulator")), [], "status admits the provider kinds")
        self.assertTrue(check_doc("C27", mutate(1, status="active")), "active with real provenance")
        self.assertTrue(check_doc("C27", mutate(0, reason={"en": "x", "es": "y"})), "available with a reason")
        self.assertTrue(check_doc("C27", mutate(0, missing=["a"])), "available with a missing list")
        self.assertTrue(check_doc("C27", mutate(1, missing=[])), "partial without missing")

    def test_F08_the_brief_delegation_new_writes_and_the_reports_in_use_validate(self):
        self.assertEqual(check_text("C02", read("C02", "valid-implement-from-delegation-new.md")), [])
        self.assertEqual(check_text("C03", read("C03", "valid-implement-with-red-and-green.md")), [])
        no_summary_no_final_lines = read("C03", "valid-research-with-sources-no-summary.md")
        self.assertNotIn("## Summary", no_summary_no_final_lines)
        self.assertNotIn("BRIEF:", no_summary_no_final_lines)
        self.assertEqual(check_text("C03", no_summary_no_final_lines), [])
        brief = read("C02", "valid-implement-from-delegation-new.md")
        errs = check_text("C02", brief.replace("## Contracts\n", "## Interfaces\n"))
        self.assertTrue(any("missing required section 'contracts'" in e for e in errs), errs)

    def test_F09_c01_critical_gates_use_the_names_of_c09_and_c10(self):
        c09 = json.loads(sp("C09").read_text(encoding="utf-8"))["properties"]["gate"]["enum"]
        c10 = list(json.loads(sp("C10").read_text(encoding="utf-8"))["properties"]["gates"]["properties"])
        c01 = json.loads(sp("C01").read_text(encoding="utf-8"))["properties"]["gates"]["properties"]["critical"]["items"]["enum"]
        self.assertEqual(c01, c09)
        self.assertEqual(c01, c10)
        full = load("C01", "valid-full.json")
        self.assertEqual(full["gates"]["critical"], ["L2-decide", "L5-freeze", "L9-promote"])
        self.assertTrue(set(full["gates"]["critical"]) <= set(c09))
        self.assertTrue(check_doc("C01", {**full, "gates": {**full["gates"], "critical": ["spec-freeze"]}}))

    def test_F10_the_lifecycle_gates_are_named_and_product_level_evidence_validates(self):
        self.assertEqual(json.loads(sp("C09").read_text(encoding="utf-8"))["properties"]["gate"]["enum"],
                         ["L0-understand", "L1-size", "L2-decide", "L3-contracts", "L4-boundaries", "L5-freeze", "L6-skeleton",
                          "L7-build", "L8-integrate", "L9-promote", "L10-lessons"])
        ev = read("C09", "valid-product-level-evidence-feature-slug.md")
        self.assertIn("feature: batuta", ev)
        self.assertEqual(check_text("C09", ev), [])
        self.assertTrue(any("/gate" in e for e in check_text("C09", ev.replace("gate: L3-contracts", "gate: P1b-contracts"))))
        self.assertEqual(check_text("C09", ev.replace("feature: batuta", "feature: 001-validator")), [])

    def test_F11_pass_with_fixes_with_an_open_critical_or_major_finding_is_refused(self):
        base = read("C09", "valid-pass-with-fixes.md")
        for sev in ("critical", "major"):
            with self.subTest(severity=sev):
                text = base.replace("| F-2 | major | off by one | run x | fixed |", f"| F-2 | major | off by one | run x | fixed |\n| F-9 | {sev} | probe | probe | open |")
                self.assertTrue(any("require no open critical or major finding" in e for e in check_text("C09", text)))
        self.assertEqual(check_text("C09", base), [])

    def test_F12_the_locked_path_is_a_posix_relative_path_and_a_supersede_names_its_change_request(self):
        base = load("C07", "valid-one-entry.json")
        for bad in ("../outside/test_x.py", "C:/work/test_x.py", "tests\\test_x.py", "/abs/test_x.py", "./tests/test_x.py", "a//b.py"):
            with self.subTest(path=bad):
                doc = copy.deepcopy(base)
                doc["entries"][0]["path"] = bad
                self.assertTrue(check_doc("C07", doc), bad)
        doc = copy.deepcopy(base)
        doc["entries"][0]["supersedes"] = "f" * 64
        self.assertTrue(any("change request" in e for e in check_doc("C07", doc)))
        doc["entries"][0]["change_request"] = "CR-001"
        self.assertEqual(check_doc("C07", doc), [])

    def test_F13_c30_exists_and_c04_and_c01_carry_the_dispatch_fields(self):
        self.assertIsNotNone(sp("C30"))
        ledger = read("C04", "valid-dispatch-columns-billed-and-subagent.md")
        self.assertIn("| anthropic | 1200 | 300 | 0.42 |", ledger)
        self.assertEqual(check_text("C04", ledger), [])
        full = load("C01", "valid-full.json")
        self.assertEqual(full["caps"]["max_cost_usd_per_task"], 5.0)
        self.assertIn("dispatch", full)
        self.assertTrue(check_doc("C01", {**full, "dispatch": {**full["dispatch"], "providers": {"x": {"kind": "gemini", "credential_env": "sk-secret-value"}}}}))
        req = load("C30", "valid-request-provider-lane.json")
        self.assertEqual(check_doc("C30", req), [])

    def test_F14_the_hook_registration_and_the_commit_grammar_have_contracts(self):
        self.assertIsNotNone(sp("C31"))
        self.assertIsNotNone(sp("C32"))
        self.assertEqual(check_text("C31", read("C31", "valid-hooks-file-exec-form-fail-closed.json")), [])
        self.assertEqual(check_text("C31", read("C31", "valid-handler-result-allow.json")), [])
        self.assertEqual(check_text("C32", "[red] T-001 lock the tests\n"), [])
        self.assertEqual(check_text("C32", "[green] T-001 update\n\nTest-Change-Approved: CR-001\n"), [])
        self.assertTrue(check_text("C32", "green: T-001 update\n"))

    def test_F14_the_shared_helpers_exist_and_the_area_uses_them(self):
        from batuta_lib import config, output
        self.assertTrue(callable(config.load) and callable(output.emit))
        self.assertIs(area.emit, output.emit)
        self.assertIs(area.item, output.item)

    def test_F15_a_handler_id_has_one_owner_and_a_guard_fails_closed(self):
        # revision 3 (ADR-0004): hooks.json is the registry and a duplicate handler id across areas is a lint failure
        doc = load("C31", "valid-hooks-file-exec-form-fail-closed.json")
        guard = doc["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(guard["onFailure"], "block")
        self.assertIn("duplicate handler id", inspect_source(contract.discover_hook_ids))

    def test_F16_the_approval_hashes_the_accepted_adrs(self):
        full = load("C06", "valid-full.json")
        self.assertEqual(check_doc("C06", full), [])
        self.assertIn("adrs_sha256", json.loads(sp("C06").read_text(encoding="utf-8"))["required"])
        self.assertTrue(check_doc("C06", {k: v for k, v in full.items() if k != "adrs_sha256"}))
        self.assertTrue(check_doc("C06", {**full, "adrs_sha256": {"../x.md": "a" * 64}}))

    def test_F17_frozen_is_one_thing_the_catalog_row_says_frozen(self):
        self.assertNotIn("frozen", json.dumps(json.loads(sp("C23").read_text(encoding="utf-8"))))
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            cat = ("| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io "
                   "| swap test | status | frozen |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                   "| a-1 | 1.0.0 | u | s.json | e.json | p | c | available: ok (test: t/a.py); missing: drop (test: t/a.py) | fixture:f | - | w | active | yes |\n"
                   "| b-1 | 1.0.0 | u | s.json | e.json | p | c | available: ok (test: t/a.py); missing: drop (test: t/a.py) | fixture:f | - | w | active | no |\n")
            (d / "catalog.md").write_text(cat, encoding="utf-8")
            (d / "s.json").write_text("{}", encoding="utf-8")  # the schema file exists for both rows
            items = area.graph(d / "catalog.md")
        self.assertIn("wave 0: a-1", [i["message"] for i in items])

    def test_F18_the_catalog_readme_lists_every_contract_and_the_implemented_fields(self):
        readme = (CONTRACTS / "README.md").read_text(encoding="utf-8")
        for n in range(1, 33):
            self.assertIn(f"C{n:02d}", readme)
        for field in ("max_cost_usd_per_task", "adrs_sha256", "frozen", "provenance", "forbidden_prose", "headers_match"):
            self.assertIn(field, readme, field)
        code, out = cli("lint")
        self.assertEqual(code, 0, out)

    def test_F19_a_brief_may_depend_on_catalog_contract_ids(self):
        brief = read("C02", "valid-implement-from-delegation-new.md")
        self.assertEqual(check_text("C02", brief.replace("- sizing: wip/alerts/sizing.md", "- sizing: wip/alerts/sizing.md\n- depends: alert-event, C02")), [])
        self.assertTrue(check_text("C02", brief.replace("- sizing: wip/alerts/sizing.md", "- sizing: wip/alerts/sizing.md\n- depends: Alert_Event")))


class Minor(unittest.TestCase):
    def test_F20_patterns_match_the_whole_text_with_ascii_digits(self):
        self.assertTrue(contract.validate("T-001\n", {"type": "string", "pattern": "^T-\\d{3}$"}))
        self.assertTrue(contract.validate("T-\u0661\u0662\u0663", {"type": "string", "pattern": "^T-\\d{3}$"}))

    def test_F21_nan_and_duplicate_keys_are_refused(self):
        self.assertTrue(any("NaN" in e for e in check_text("C11", '{"contract_version": "1.0", "values": {"x": NaN}}')))
        self.assertTrue(any("duplicate key" in e for e in check_text("C07", '{"contract_version": "1.0", "entries": [], "entries": []}')))

    def test_F22_a_byte_order_mark_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "brief.md"
            p.write_bytes((FX / "C02" / "valid-with-a-byte-order-mark.md").read_bytes())
            self.assertTrue(p.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(contract.validate_file(p, sp("C02")), [])

    def test_F22_crlf_markdown_validates(self):
        text = read("C02", "valid-implement-from-delegation-new.md").replace("\n", "\r\n")
        self.assertEqual(check_text("C02", text), [])

    def test_F23_a_misspelled_sections_key_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "CX-t.schema.json").write_text("{}", encoding="utf-8")
            (pathlib.Path(d) / "CX-t.sections.json").write_text(json.dumps({"tables": [{"name": "T", "headers": ["A"], "min_row": 99}]}), encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                contract.load_sections_spec(pathlib.Path(d) / "CX-t.schema.json")
            self.assertIn("min_row", str(cm.exception))

    def test_F24_a_ref_cycle_is_reported_at_load(self):
        self.assertTrue(any("cycle" in p for p in contract.check_schema({"$ref": "#/$defs/a", "$defs": {"a": {"$ref": "#/$defs/a"}}})))

    def test_F25_relative_paths_cannot_climb_out(self):
        full = load("C01", "valid-full.json")
        self.assertTrue(check_doc("C01", {**full, "coordination_root": "../../elsewhere"}))
        self.assertEqual(check_doc("C01", {**full, "coordination_root": ".batuta"}), [])
        self.assertTrue(check_doc("C28", {**load("C28", "valid-released.json"), "io_contract": "../io.schema.json"}))

    def test_F26_every_invalid_fixture_fails_for_exactly_one_stated_reason(self):
        checked = 0
        for schema in sorted(CONTRACTS.glob("C*-*.schema.json")):
            cid = schema.name.split("-")[0]
            for fx in sorted((FX / cid).glob("invalid-*")):
                checked += 1
                with self.subTest(fixture=f"{cid}/{fx.name}"):
                    why, expect = contract.fixture_meta(fx)
                    self.assertTrue(why and expect, "states why and what error to look for")
                    errs = contract.validate_file(fx, schema)
                    self.assertEqual(len(errs), 1, errs)
                    self.assertIn(expect, errs[0])
        self.assertGreater(checked, 250)

    def test_F27_the_configuration_example_of_the_design_validates_as_c01(self):
        self.assertEqual(check_doc("C01", load("C01", "valid-design-example.json")), [])

    def test_F28_trace_matrix_status_is_the_spec_enum(self):
        base = load("C08", "valid-ok.json")
        row = base["requirements"][0]
        self.assertEqual(check_doc("C08", {**base, "requirements": [{**row, "status": "retired"}]}), [])
        self.assertTrue(check_doc("C08", {**base, "requirements": [{**row, "status": "whatever"}]}))

    def test_F29_a_frozen_spec_has_at_least_one_requirement(self):
        text = read("C05", "valid-frozen.md")
        a, b = text.index("| REQ-VAL-001"), text.index("## Interfaces")
        errs = check_text("C05", text[:a] + "\n" + text[b:])
        self.assertTrue(any("at least one requirement row" in e for e in errs), errs)
        self.assertEqual(check_text("C05", text), [])

    def test_F30_lint_enforces_two_valid_and_three_invalid_fixtures(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(CONTRACTS, root / "contracts")
            for p in sorted((root / "contracts" / "fixtures" / "C14").glob("valid-*"))[1:]:
                p.unlink()
            code, out = cli("lint", "--root", d)
            self.assertEqual(code, 1)
            self.assertIn("C14 needs at least 2 valid and 3 invalid fixtures", out)

    def test_F31_an_accepted_or_superseded_row_names_who_and_by_what(self):
        # revision 3 (ADR-0004): the ledger is the Markdown table; accepted is the Accepted column
        base = read("C04", "valid-drafted-pending-complete-accepted.md")
        self.assertEqual(check_text("C04", base), [])
        self.assertTrue(any("status accepted" in e for e in check_text("C04", base.replace("| accepted | yes |", "| accepted | no |"))))
        sup = read("C04", "valid-superseded-row-names-its-replacement.md")
        self.assertEqual(check_text("C04", sup), [])
        self.assertTrue(any("replaces" in e for e in check_text("C04", sup.replace("| a-2026-10-12-2 |\n", "|  |\n", 1))))


if __name__ == "__main__":
    unittest.main()
