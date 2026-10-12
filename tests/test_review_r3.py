"""The reproductions of the re-review findings R01 to R20 and the leftovers (contracts, U0 revision 3).

Each test is the re-review's reproduction turned into an assertion: it failed on the tree before the revision and
passes after it. Test names start with the finding id so the re-check table can name them.

The CAOS tools are optional oracles: set `BATUTA_CAOS_TOOLS` to the folder that holds `sizing_check.py` and
`delegation.py` to run the differential tests; without it they are skipped (the recorded fixture still guards drift).
"""
import contextlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib import config, contract, frontmatter  # noqa: E402
from batuta_lib.areas import contract as area  # noqa: E402

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"
FX = CONTRACTS / "fixtures"
CAOS_TOOLS = os.environ.get("BATUTA_CAOS_TOOLS")


def sp(cid):
    found = sorted(CONTRACTS.glob(f"{cid}-*.schema.json"))
    return found[0] if found else None


def read(cid, name):
    return (FX / cid / name).read_text(encoding="utf-8")


def check_text(cid, text, ext=None, name=None):
    """Validate text as contract `cid` through the file path the CLI uses."""
    if ext is None:
        ext = ".txt" if cid == "C32" else ".md" if list(CONTRACTS.glob(f"{cid}-*.sections.json")) else ".json"
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / (name or f"artifact{ext}")
        p.write_text(text, encoding="utf-8", newline="")
        return contract.validate_file(p, sp(cid), cid)


def check_doc(cid, doc, name=None):
    return check_text(cid, json.dumps(doc), name=name)


def mentions(errs, *words):
    return any(all(w.lower() in e.lower() for w in words) for e in errs)


# ------------------------------------------------------------------ R01, R02: C23 and C02 against the CAOS tools


SIZING = read("C23", "valid-product-sizing.md")
BRIEF = read("C02", "valid-implement-from-delegation-new.md")


def without_section(text, title):
    return re.sub(rf"(?ms)^## {re.escape(title)}\n.*?(?=^## )", "", text)


def with_brief(text, body):
    return re.sub(r"(?m)^## Executive brief\n.*?(?=^## )", "## Executive brief\n" + body + "\n\n", text, flags=re.S)


class R01(unittest.TestCase):
    def test_R01_a_sizing_without_the_executive_brief_is_refused(self):
        text = without_section(SIZING, "Executive brief")
        self.assertNotIn("Executive brief", text)
        self.assertTrue(mentions(check_text("C23", text), "executive brief"))

    def test_R01_the_valid_fixtures_have_an_executive_brief_and_validate(self):
        for name in sorted(p.name for p in (FX / "C23").glob("valid-*.md")):
            with self.subTest(name):
                self.assertIn("## Executive brief", read("C23", name).replace("## executive brief", "## Executive brief"))
                self.assertEqual(check_text("C23", read("C23", name)), [])

    def test_R01_not_a_product_needs_a_reason_of_five_words(self):
        self.assertEqual(check_text("C23", with_brief(SIZING, "Not a product: a shared build tool with no executive of its own.")), [])
        self.assertTrue(mentions(check_text("C23", with_brief(SIZING, "Not a product: internal tool")), "not a product"))

    def test_R01_each_part_needs_five_words_of_content(self):
        for part in ("Initiative", "Outcomes", "Positioning", "Credibility"):
            with self.subTest(part):
                body = "\n".join(l for l in re.search(r"(?ms)^## Executive brief\n(.*?)(?=^## )", SIZING).group(1).splitlines()
                                 if not l.lstrip("-* ").startswith(part + ":"))
                errs = check_text("C23", with_brief(SIZING, body))
                self.assertTrue(mentions(errs, part), errs)

    def test_R01_the_initiative_is_quantified_with_a_source(self):
        no_number = "- Initiative: help operators triage alerts quickly (https://example.org/study).\n" + \
            "- Outcomes: fewer missed alerts for the people on shift every week.\n" + \
            "- Positioning: a small service for operators who run telemetry fleets.\n" + \
            "- Credibility: built on the maintainers' own incident review history."
        self.assertTrue(mentions(check_text("C23", with_brief(SIZING, no_number)), "initiative", "quantified"))
        no_source = no_number.replace("help operators triage alerts quickly (https://example.org/study)", "cut 40 percent of missed alerts by next quarter")
        self.assertTrue(mentions(check_text("C23", with_brief(SIZING, no_source)), "initiative", "quantified"))

    def test_R01_c23_requires_the_sections_the_recorded_sizing_check_requires(self):
        rec = json.loads((FX / "_upstream" / "sizing_check.recorded.json").read_text(encoding="utf-8"))
        for key in ("copied_from", "commit", "date", "sections", "tables", "executive_brief_parts"):
            self.assertIn(key, rec)
        spec = contract.load_sections_spec(sp("C23"))
        ours = [s.lower() for s in spec["required_sections"]]
        self.assertEqual(sorted(ours), sorted(s.lower() for s in rec["sections"]))
        tables = {t["section"].lower(): [h.lower() for h in t["headers"]] for t in spec["tables"]}
        self.assertEqual(tables, {k.lower(): [h.lower() for h in v] for k, v in rec["tables"].items()})
        rule = next(r for r in spec["rules"] if r["type"] == "labeled_parts")
        self.assertEqual([x.lower() for x in rule["labels"]], [x.lower() for x in rec["executive_brief_parts"]])

    @unittest.skipUnless(CAOS_TOOLS, "BATUTA_CAOS_TOOLS is not set")
    def test_R01_the_caos_checker_and_c23_agree_on_every_fixture(self):
        sys.path.insert(0, CAOS_TOOLS)
        import sizing_check  # noqa: E402
        rec = json.loads((FX / "_upstream" / "sizing_check.recorded.json").read_text(encoding="utf-8"))
        self.assertEqual(list(sizing_check.SECTIONS), rec["sections"], "the recorded fixture is out of date: copy it again")
        for path in sorted((FX / "C23").glob("*.md")):
            with self.subTest(path.name):
                ours = contract.validate_file(path, sp("C23"))
                theirs = sizing_check.check_text(path.read_text(encoding="utf-8"))
                if path.name.startswith("valid-"):
                    self.assertEqual((ours, theirs), ([], []))
                else:
                    self.assertTrue(ours, "C23 accepts an invalid fixture")


class R02(unittest.TestCase):
    def test_R02_a_brief_with_an_unfilled_slot_is_refused(self):
        text = BRIEF.replace("## Goal\n", "## Goal\n<fill: the goal in two sentences>\n", 1)
        self.assertTrue(mentions(check_text("C02", text), "placeholder"))

    def test_R02_a_slot_inside_a_code_block_is_still_refused(self):
        text = BRIEF.rstrip("\n") + "\n\n```\n<fill: command>\n```\n"
        self.assertTrue(mentions(check_text("C02", text), "placeholder"))

    def test_R02_the_slot_check_is_case_insensitive_and_tolerates_attributes(self):
        for slot in ("<FILL: x>", "<fill x>", "<Fill:x>"):
            with self.subTest(slot):
                self.assertTrue(check_text("C02", BRIEF.replace("## Goal\n", f"## Goal\n{slot}\n", 1)))

    def test_R02_a_filled_brief_still_validates(self):
        self.assertEqual(check_text("C02", BRIEF), [])
        self.assertNotRegex(BRIEF, r"(?i)<fill\b")

    @unittest.skipUnless(CAOS_TOOLS, "BATUTA_CAOS_TOOLS is not set")
    def test_R02_a_brief_from_delegation_new_is_refused_until_filled(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, str(pathlib.Path(CAOS_TOOLS) / "delegation.py"), "new", "--root", d, "--slug", "p",
                            "--topic", "rev", "--agent", "reviewer", "--title", "Probe", "--date", "2026-10-12"],
                           check=True, capture_output=True, text=True)
            brief = next(pathlib.Path(d).glob("wip/p/delegation/*.brief.md"))
            self.assertTrue(mentions(contract.validate_file(brief, sp("C02")), "placeholder"))
            ledger = next(pathlib.Path(d).glob("wip/p/delegation/ledger.md"))
            self.assertEqual(contract.validate_file(ledger, sp("C04")), [])


# ------------------------------------------------------------------ R03, R04: the Markdown ledger


HEAD7 = "| ID | Agent | Model | Brief | Report | Status | Accepted |\n|---|---|---|---|---|---|---|\n"
HEAD11 = ("| ID | Agent | Model | Brief | Report | Status | Accepted | Provider | Tokens in | Tokens out | Cost USD |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|\n")
ROW7 = "| ingest-2026-10-12 | implementer | sonnet | wip/p/delegation/ingest-2026-10-12.brief.md | wip/p/ingest-2026-10-12.md | {status} | {acc} |\n"
ROW11 = ("| run-2026-10-12 | implementer | sonnet | wip/p/delegation/run-2026-10-12.brief.md | wip/p/run-2026-10-12.md | {status} | {acc} | "
         "{prov} | {tin} | {tout} | {cost} |\n")


def ledger7(status="drafted", acc="no"):
    return "# Delegation ledger: p\n\n" + HEAD7 + ROW7.format(status=status, acc=acc)


def ledger11(status="complete", acc="no", prov="-", tin="-", tout="-", cost="-"):
    return "# Delegation ledger: p\n\n" + HEAD11 + ROW11.format(status=status, acc=acc, prov=prov, tin=tin, tout=tout, cost=cost)


class R03(unittest.TestCase):
    def test_R03_the_table_the_caos_tool_writes_is_a_valid_ledger(self):
        self.assertEqual(check_text("C04", ledger7()), [])

    def test_R03_c04_is_markdown_and_no_jsonl_survives(self):
        self.assertTrue(list(CONTRACTS.glob("C04-*.sections.json")))
        self.assertEqual(list((FX / "C04").glob("*.jsonl")), [])
        self.assertNotIn("jsonl", json.loads(sp("C04").read_text(encoding="utf-8"))["description"].lower())

    def test_R03_the_dispatch_columns_are_optional_and_accepted(self):
        self.assertEqual(check_text("C04", ledger11(prov="anthropic", tin="1200", tout="300", cost="0.42")), [])
        self.assertEqual(check_text("C04", ledger11()), [])

    def test_R03_a_ledger_with_no_row_is_refused(self):
        self.assertTrue(check_text("C04", "# Delegation ledger: p\n\n" + HEAD7))

    def test_R03_an_unknown_status_is_refused(self):
        self.assertTrue(mentions(check_text("C04", ledger7(status="finished")), "status"))

    def test_R03_the_accepted_column_is_yes_or_no(self):
        self.assertTrue(check_text("C04", ledger7(acc="maybe")))
        self.assertEqual(check_text("C04", ledger7(status="accepted", acc="yes")), [])

    def test_R03_an_accepted_status_needs_accepted_yes(self):
        self.assertTrue(mentions(check_text("C04", ledger7(status="accepted", acc="no")), "accepted"))

    def test_R03_a_superseded_row_names_its_replacement(self):
        text = ledger7(status="superseded").replace("| Accepted |", "| Accepted | Superseded by |").replace("|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|")
        text = text.replace("| superseded | no |", "| superseded | no |  |")
        self.assertTrue(mentions(check_text("C04", text), "superseded"))
        self.assertEqual(check_text("C04", text.replace("| superseded | no |  |", "| superseded | no | run-2026-10-13 |")), [])

    def test_R03_duplicate_ids_are_refused(self):
        text = ledger7() + ROW7.format(status="pending", acc="no")
        self.assertTrue(mentions(check_text("C04", text), "duplicate"))


class R04(unittest.TestCase):
    def test_R04_every_c30_result_status_is_a_c04_status(self):
        c30 = json.loads(sp("C30").read_text(encoding="utf-8"))["$defs"]["result"]["properties"]["status"]["enum"]
        c04 = json.loads(sp("C04").read_text(encoding="utf-8"))["$defs"]["ledger_row"]["properties"]["Status"]["enum"]
        self.assertFalse(set(c30) - set(c04), set(c30) - set(c04))
        for status in ("timeout", "error", "over-budget"):
            with self.subTest(status):
                self.assertEqual(check_text("C04", ledger7(status=status)), [])

    def test_R04_the_lint_checks_the_status_mapping(self):
        items = []
        loaded = {c: contract.load_schema(sp(c)) for c in ("C04", "C30")}
        area._lint_consistency(loaded, items)
        self.assertTrue(any(i["tag"] == "OK" and "C30" in i["message"] and "C04" in i["message"] and "status" in i["message"] for i in items), items)

    def test_R04_the_mapping_is_documented(self):
        text = (CONTRACTS / "README.md").read_text(encoding="utf-8")
        for status in ("timeout", "error", "over-budget"):
            self.assertRegex(text, rf"(?s)C30.*{status}.*C04|C04.*{status}.*C30")

    def test_R04_a_billed_lane_row_needs_tokens_and_cost(self):
        for prov in ("anthropic", "openai"):
            with self.subTest(prov):
                errs = check_text("C04", ledger11(prov=prov, tin="10", tout="5", cost="-"))
                self.assertTrue(mentions(errs, "cost"), errs)
                errs = check_text("C04", ledger11(prov=prov, tin="-", tout="5", cost="0.1"))
                self.assertTrue(mentions(errs, "tokens in"), errs)
                errs = check_text("C04", ledger11(prov=prov, tin="1", tout="-", cost="0.1"))
                self.assertTrue(mentions(errs, "tokens out"), errs)

    def test_R04_a_subagent_row_needs_no_cost(self):
        self.assertEqual(check_text("C04", ledger11(prov="-")), [])

    def test_R04_cost_is_a_finite_non_negative_number(self):
        for cost in ("-1", "NaN", "inf", "1e999", "free"):
            with self.subTest(cost):
                self.assertTrue(check_text("C04", ledger11(prov="anthropic", tin="1", tout="1", cost=cost)))

    def test_R04_c01_names_the_sdk_key_file(self):
        doc = json.loads(read("C01", "valid-sdk-lane-with-cost-cap.json"))
        doc.pop("_why", None)
        doc["dispatch"]["sdk"] = {"key_file": "$ANTHROPIC_KEY_FILE"}
        self.assertEqual(check_doc("C01", doc), [])
        doc["dispatch"]["sdk"] = {"key_file": 5}
        self.assertTrue(check_doc("C01", doc))


# ------------------------------------------------------------------ R05, R06, R07: hooks


LAUNCHER = "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py"


def entry(**kw):
    base = {"type": "command", "command": "python", "args": [LAUNCHER, "report-check"]}
    base.update(kw)
    return base


def hooks_doc(event="PreToolUse", group=None, **kw):
    g = {"hooks": [entry(**kw)]}
    g.update(group or {})
    return {"hooks": {event: [g]}}


class R06(unittest.TestCase):
    def test_R06_a_fail_closed_entry_carries_args_and_on_failure_block(self):
        doc = hooks_doc(group={"matcher": "Bash"}, args=["-I", LAUNCHER, "automation-guard"], onFailure="block", timeout=10)
        self.assertEqual(check_doc("C31", doc, name="hooks.json"), [])

    def test_R06_the_other_official_entry_fields_are_accepted(self):
        doc = hooks_doc(timeout=5, shell="bash", statusMessage="checking", once=False, **{"async": False, "if": "Bash(git *)"})
        self.assertEqual(check_doc("C31", doc), [])

    def test_R06_on_failure_takes_only_block(self):
        self.assertTrue(check_doc("C31", hooks_doc(onFailure="allow")))

    def test_R06_an_unknown_entry_field_is_refused(self):
        self.assertTrue(check_doc("C31", hooks_doc(retry=3)))

    def test_R06_args_run_the_launcher_then_the_handler_id(self):
        for args in ([LAUNCHER], ["report-check"], [LAUNCHER, "Report"], ["-I", "report-check", LAUNCHER], ["/opt/x/hook.py", "report-check"],
                     [LAUNCHER, "report-check", "extra"], []):
            with self.subTest(args=args):
                self.assertTrue(check_doc("C31", hooks_doc(args=args)))

    def test_R06_interpreter_flags_come_before_the_launcher(self):
        self.assertEqual(check_doc("C31", hooks_doc(args=["-I", "-B", LAUNCHER, "report-check"])), [])

    def test_R06_the_shell_form_and_the_exec_form_share_one_grammar(self):
        shell = hooks_doc(command=f'python -I "{LAUNCHER}" report-check')
        shell["hooks"]["PreToolUse"][0]["hooks"][0].pop("args")
        self.assertEqual(check_doc("C31", shell), [])
        exec_form = hooks_doc(command="python", args=["-I", LAUNCHER, "report-check"])
        self.assertEqual(check_doc("C31", exec_form), [])

    def test_R06_a_command_with_args_is_a_bare_interpreter_name(self):
        self.assertTrue(mentions(check_doc("C31", hooks_doc(command="python -I")), "bare"))
        self.assertTrue(check_doc("C31", hooks_doc(command="/usr/bin/python")))

    def test_R06_a_machine_path_launcher_is_refused(self):
        doc = hooks_doc(command='python "/opt/me/plugin/scripts/hook.py" report-check')
        doc["hooks"]["PreToolUse"][0]["hooks"][0].pop("args")
        self.assertTrue(check_doc("C31", doc))


class R07(unittest.TestCase):
    def test_R07_session_start_and_subagent_stop_groups_carry_matchers(self):
        self.assertEqual(check_doc("C31", hooks_doc("SessionStart", {"matcher": "startup|resume"})), [])
        self.assertEqual(check_doc("C31", hooks_doc("SubagentStop", {"matcher": "implementer"})), [])

    def test_R07_on_failure_block_is_refused_where_the_event_cannot_block_through_it(self):
        for event in ("SessionStart", "SubagentStop", "Stop"):
            with self.subTest(event):
                self.assertTrue(mentions(check_doc("C31", hooks_doc(event, onFailure="block")), "onfailure"))
        for event in ("PreToolUse", "UserPromptSubmit"):
            with self.subTest(event):
                self.assertEqual(check_doc("C31", hooks_doc(event, onFailure="block")), [])

    def test_R07_an_unquoted_placeholder_in_the_shell_form_is_refused(self):
        for command in (f"python {LAUNCHER} report-check", f'python "{LAUNCHER} report-check', f"python '{LAUNCHER}' report-check"):
            with self.subTest(command):
                doc = hooks_doc(command=command)
                doc["hooks"]["PreToolUse"][0]["hooks"][0].pop("args")
                self.assertTrue(check_doc("C31", doc))

    def test_R07_the_unquoted_fixture_is_gone(self):
        self.assertFalse((FX / "C31" / "valid-hooks-file-unquoted-launcher.json").exists())


class R05(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.areas = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        (self.areas / f"{name}.py").write_text(text, encoding="utf-8")

    def test_R05_an_area_module_declares_hooks_as_a_dict_and_ids_are_found(self):
        self.write("a", "def f(p):\n    return None\n\nHOOKS = {'report-check': f, 'doctor': f}\n")
        self.write("b", "AREA = 'b'\n")
        found, problems = contract.discover_hook_ids(self.areas)
        self.assertEqual(problems, [])
        self.assertEqual({k: v for k, v in found.items()}, {"report-check": ["a"], "doctor": ["a"]})

    def test_R05_a_duplicate_id_across_areas_is_a_problem(self):
        self.write("a", "HOOKS = {'x': None}\n")
        self.write("b", "HOOKS = {'x': None}\n")
        found, problems = contract.discover_hook_ids(self.areas)
        self.assertTrue(mentions(problems, "duplicate", "'x'"), problems)

    def test_R05_a_hooks_value_that_is_not_a_literal_dict_is_a_problem(self):
        self.write("a", "HOOKS = build()\n")
        self.assertTrue(mentions(contract.discover_hook_ids(self.areas)[1], "literal"))
        self.write("a", "HOOKS = {1: None}\n")
        self.assertTrue(mentions(contract.discover_hook_ids(self.areas)[1], "string"))

    def test_R05_an_id_that_breaks_the_pattern_is_a_problem(self):
        self.write("a", "HOOKS = {'Bad_Id': None}\n")
        self.assertTrue(mentions(contract.discover_hook_ids(self.areas)[1], "bad_id"))

    def test_R05_the_lint_resolves_every_hooks_json_id_to_one_handler(self):
        plugin = self.areas / "plugin"
        (plugin / "hooks").mkdir(parents=True)
        (plugin / "scripts" / "batuta_lib" / "areas").mkdir(parents=True)
        (plugin / "scripts" / "batuta_lib" / "areas" / "guard.py").write_text("HOOKS = {'automation-guard': None}\n", encoding="utf-8")
        hooks = hooks_doc(args=[LAUNCHER, "automation-guard"])
        (plugin / "hooks" / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
        items = []
        area._lint_hooks(plugin, items)
        self.assertEqual([i["tag"] for i in items], ["OK", "OK"], items)
        (plugin / "hooks" / "hooks.json").write_text(json.dumps(hooks_doc(args=[LAUNCHER, "unknown-id"])), encoding="utf-8")
        items = []
        area._lint_hooks(plugin, items)
        self.assertTrue(any(i["tag"] == "FAIL" and "unknown-id" in i["message"] for i in items), items)

    def test_R05_the_lint_fails_on_duplicate_ids(self):
        plugin = self.areas / "plugin"
        (plugin / "scripts" / "batuta_lib" / "areas").mkdir(parents=True)
        for n in ("a", "b"):
            (plugin / "scripts" / "batuta_lib" / "areas" / f"{n}.py").write_text("HOOKS = {'same-id': None}\n", encoding="utf-8")
        items = []
        area._lint_hooks(plugin, items)
        self.assertTrue(any(i["tag"] == "FAIL" and "same-id" in i["message"] for i in items), items)

    def test_R05_the_handler_result_is_contracted(self):
        ok = {"contract_version": "1.0", "exit_code": 0, "output": None}
        self.assertEqual(check_doc("C31", ok), [])
        block = {"contract_version": "1.0", "exit_code": 2, "output": None, "message": "blocked: locked test"}
        self.assertEqual(check_doc("C31", block), [])
        self.assertTrue(mentions(check_doc("C31", {**block, "message": ""}), "message"))
        self.assertTrue(mentions(check_doc("C31", {k: v for k, v in block.items() if k != "message"}), "message"))
        decision = {"contract_version": "1.0", "exit_code": 0, "output": {"decision": "block", "reason": "no report"}}
        self.assertEqual(check_doc("C31", decision), [])
        self.assertTrue(check_doc("C31", {**ok, "output": {"decision": "maybe"}}))
        self.assertTrue(check_doc("C31", {**ok, "exit_code": 1}))

    def test_R05_the_readme_names_the_registry_path_and_the_discovery_rule(self):
        text = (CONTRACTS / "README.md").read_text(encoding="utf-8")
        self.assertIn("plugins/batuta/hooks/hooks.json", text)
        self.assertIn("HOOKS = {", text)


# ------------------------------------------------------------------ R07 of availability: C26 and C22 (decision 7)


CATALOG = read("C22", "valid-three-rows-with-a-model-slot.md")


def catalog_with(cell):
    """The three-row catalog with the missing-data behavior cell of its first row replaced."""
    lines = CATALOG.split("\n")
    first = next(i for i, ln in enumerate(lines) if ln.startswith("| alert-event"))
    cells = lines[first].split("|")
    cells[8] = f" {cell} "   # the leading empty string shifts the columns by one: the 8th column is index 8
    lines[first] = "|".join(cells)
    return "\n".join(lines)


STATES = ("available: the real event is used (test: tests/contracts/test_alert_consumer.py::test_available); "
          "missing: drop the event and show \"no data\" (test: tests/contracts/test_alert_consumer.py::test_missing)")


class Decision7(unittest.TestCase):
    def test_D7_c26_keeps_the_vocabulary_and_the_runtime_block_only(self):
        schema = json.loads(sp("C26").read_text(encoding="utf-8"))
        self.assertNotIn("components", schema.get("properties", {}))
        self.assertEqual(sorted(schema["$defs"]), ["state"])
        self.assertEqual(sorted(schema["required"]), ["age", "reason", "source", "state"])
        self.assertEqual(list((FX / "C26").glob("*declaration*")), [])
        self.assertFalse(hasattr(contract, "check_declaration_states"))

    def test_D7_a_runtime_block_is_the_document(self):
        self.assertEqual(check_text("C26", read("C26", "valid-runtime-provider.json")), [])
        self.assertTrue(check_text("C26", '{"components": []}'))

    def test_D7_the_catalog_cell_declares_the_states_with_a_test_each(self):
        text = catalog_with(STATES)
        self.assertEqual(check_text("C22", text), [], text)

    def test_D7_a_provider_state_names_its_provenance_kind(self):
        text = catalog_with(STATES + "; provider(fixture): show the fixture labelled fixture (test: tests/contracts/test_alert_swap.py)")
        self.assertEqual(check_text("C22", text), [])
        bare = catalog_with(STATES + "; provider: show the fixture (test: tests/contracts/test_alert_swap.py)")
        self.assertTrue(mentions(check_text("C22", bare), "provider"))
        bad = catalog_with(STATES + "; provider(mock): show the mock (test: tests/contracts/test_alert_swap.py)")
        self.assertTrue(check_text("C22", bad))

    def test_D7_a_state_without_its_test_is_refused(self):
        self.assertTrue(check_text("C22", catalog_with("available: the real event is used; missing: drop it (test: tests/t.py)")))

    def test_D7_the_cell_declares_available_and_one_other_state(self):
        self.assertTrue(mentions(check_text("C22", catalog_with("missing: drop it (test: tests/t.py)")), "available"))
        self.assertTrue(check_text("C22", catalog_with("available: use it (test: tests/t.py)")))

    def test_D7_a_state_is_declared_once_and_is_one_of_the_six(self):
        self.assertTrue(mentions(check_text("C22", catalog_with(STATES + "; missing: again (test: tests/t.py)")), "duplicate"))
        self.assertTrue(check_text("C22", catalog_with(STATES + "; synthetic: x (test: tests/t.py)")))

    def test_D7_a_test_reference_is_a_relative_path(self):
        for ref in ("/abs/t.py", "../t.py", "a/../t.py"):
            with self.subTest(ref):
                self.assertTrue(check_text("C22", catalog_with(f"available: use it (test: {ref}); missing: drop (test: tests/t.py)")))

    def test_D7_free_text_without_states_is_refused(self):
        self.assertTrue(check_text("C22", catalog_with("drop the event, log a warning, show no data")))


# ------------------------------------------------------------------ R08, decision 9: configuration after expansion


def write_config(d, **override):
    doc = config.default_config({"BATUTA_HOME": str(d)})
    doc.update(override)
    p = pathlib.Path(d) / "batuta.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


class R08(unittest.TestCase):
    def test_R08_a_variable_that_expands_to_a_traversing_path_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_config(d, coordination_root="$EVIL")
            with self.assertRaises(config.ConfigError) as cm:
                config.load(config_arg=str(p), env={"EVIL": "../../../outside"})
            self.assertIn("coordination_root", str(cm.exception))

    def test_R08_the_knowledge_manifest_is_checked_after_expansion_too(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_config(d, knowledge_manifest="${K}/m.json")
            with self.assertRaises(config.ConfigError) as cm:
                config.load(config_arg=str(p), env={"K": "../x"})
            self.assertIn("knowledge_manifest", str(cm.exception))

    def test_R08_a_variable_that_expands_to_an_absolute_path_is_refused(self):
        for value in ("/etc/x", "C:/x", "\\\\host\\x"):
            with self.subTest(value):
                with tempfile.TemporaryDirectory() as d:
                    p = write_config(d, coordination_root="$ROOT")
                    with self.assertRaises(config.ConfigError):
                        config.load(config_arg=str(p), env={"ROOT": value})

    def test_R08_a_safe_expansion_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_config(d, coordination_root="$SUB/coord")
            r = config.load(config_arg=str(p), env={"SUB": "work"})
            self.assertEqual(r.config["coordination_root"], "work/coord")

    def test_R08_an_unset_variable_in_a_path_field_names_the_variable_and_the_field(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_config(d, coordination_root="$NOPE/coord")
            with self.assertRaises(config.ConfigError) as cm:
                config.load(config_arg=str(p), env={})
            msg = str(cm.exception)
            self.assertIn("NOPE", msg)
            self.assertIn("coordination_root", msg)
            self.assertNotIn("/coord", msg)   # never a partial path

    def test_R08_an_unset_root_still_falls_back_under_the_batuta_home(self):
        with tempfile.TemporaryDirectory() as d:
            doc = config.default_config({"BATUTA_HOME": d})
            doc["roots"]["temp"] = "$MISSING_TEMP/t"
            p = pathlib.Path(d) / "batuta.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            r = config.load(config_arg=str(p), env={"BATUTA_HOME": d})
            self.assertEqual(pathlib.Path(r.config["roots"]["temp"]), pathlib.Path(d) / "temp")

    def test_R08_the_expanded_document_satisfies_c01(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_config(d, coordination_root="$SUB/coord")
            r = config.load(config_arg=str(p), env={"SUB": "work"})
            self.assertEqual(config.validate(r.config), [])

    def test_R08_a_value_that_expands_to_a_wrong_type_is_refused_with_the_field(self):
        with tempfile.TemporaryDirectory() as d:
            doc = config.default_config({"BATUTA_HOME": d})
            doc["caps"]["max_concurrent_agents"] = "$N"
            p = pathlib.Path(d) / "batuta.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(config.ConfigError) as cm:
                config.load(config_arg=str(p), env={"N": "4"})
            self.assertIn("max_concurrent_agents", str(cm.exception))


# ------------------------------------------------------------------ R09, R10: relative paths


class R09(unittest.TestCase):
    def test_R09_an_embedded_newline_does_not_hide_a_parent_segment(self):
        self.assertTrue(contract._bad_relpath("a\n/../b"))
        self.assertTrue(contract._bad_relpath("tests/x.py\n"))
        self.assertTrue(contract._bad_relpath("a\tb"))
        self.assertFalse(contract._bad_relpath("tests/x.py"))

    def test_R09_c07_refuses_paths_with_control_characters(self):
        doc = json.loads(read("C07", "valid-one-entry.json"))
        doc.pop("_why", None)
        for path in ("tests/a\n../../x.py", "tests/test_x.py\n", "tests/a\tb.py"):
            with self.subTest(path=path):
                bad = json.loads(json.dumps(doc))
                bad["entries"][0]["path"] = path
                self.assertTrue(check_doc("C07", bad))

    def test_R09_c01_refuses_a_newline_before_a_parent_segment(self):
        doc = json.loads(read("C01", "valid-minimal.json"))
        doc.pop("_why", None)
        doc["coordination_root"] = "a\n/../../b"
        self.assertTrue(check_doc("C01", doc))

    def test_R09_c30_refuses_a_newline_before_a_parent_segment(self):
        req = json.loads(read("C30", "valid-request-subagent.json"))
        req.pop("_why", None)
        req["brief"] = "a\n/../b"
        self.assertTrue(check_doc("C30", req))


RELPATH_FIELDS = (("C01", ("properties", "coordination_root")), ("C01", ("properties", "knowledge_manifest")),
                  ("C07", ("$defs", "entry", "properties", "path")), ("C30", ("$defs", "request", "properties", "brief")),
                  ("C30", ("$defs", "request", "properties", "report")), ("C30", ("$defs", "result", "properties", "report")),
                  ("C30", ("$defs", "result", "properties", "patch")), ("C30", ("$defs", "request", "properties", "write_scope", "items")),
                  ("C28", ("properties", "io_contract")))


class R10(unittest.TestCase):
    def _field(self, cid, keys):
        node = json.loads(sp(cid).read_text(encoding="utf-8"))
        for k in keys:
            node = node[k]
        return node

    def test_R10_one_relative_path_pattern_everywhere(self):
        patterns = {f"{c} {'/'.join(k)}": self._field(c, k).get("pattern") for c, k in RELPATH_FIELDS if sp(c)}
        self.assertEqual(len(set(patterns.values())), 1, patterns)

    def test_R10_the_lint_checks_the_relative_path_pattern(self):
        items = []
        loaded = {c: contract.load_schema(sp(c)) for c in ("C01", "C07", "C28", "C30")}
        area._lint_consistency(loaded, items)
        self.assertTrue(any(i["tag"] == "OK" and "relative path" in i["message"] for i in items), items)

    def test_R10_dot_slash_and_double_slash_are_refused_in_c01_and_c30(self):
        doc = json.loads(read("C01", "valid-minimal.json"))
        doc.pop("_why", None)
        for path in ("./x", "a//b", "a/./b", "a/.", "."):
            with self.subTest(path):
                self.assertTrue(check_doc("C01", {**doc, "coordination_root": path}))

    def test_R10_the_plain_forms_stay_valid(self):
        doc = json.loads(read("C01", "valid-minimal.json"))
        doc.pop("_why", None)
        for path in (".batuta", ".batuta/knowledge/manifest.json", "a.b/c-d"):
            with self.subTest(path):
                self.assertEqual(check_doc("C01", {**doc, "coordination_root": path}), [])


# ------------------------------------------------------------------ minors of the validator core


class Minors(unittest.TestCase):
    def test_R11_an_overflowing_number_is_refused(self):
        for text in ('{"a": 1e999}', '{"a": -1e999}', "[1e400]"):
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    contract.loads_strict(text)
        self.assertEqual(contract.loads_strict('{"a": 1.5e3}'), {"a": 1500.0})

    def test_R11_a_threshold_that_overflows_is_refused(self):
        text = read("C11", "valid-no-history.json").replace("200", "1e999")
        self.assertTrue(mentions(check_text("C11", text), "finite"))

    def test_R12_the_sections_file_values_are_checked(self):
        base = {"contract_id": "C99", "contract_version": "1.0"}
        cases = [({"front_matter": "bulets"}, "front_matter"),
                 ({"tables": [{"headers": ["a"], "coerce": {"a": "lsit"}}]}, "coerce"),
                 ({"coerce": {"a": "lsit"}}, "coerce"),
                 ({"rules": [{"type": "exit_code", "section": "x", "expect": "nonzro"}]}, "expect"),
                 ({"mode": "line"}, "mode"),
                 ({"rules": [{"type": "labeled_parts", "section": "x", "labels": []}]}, "labels")]
        for extra, word in cases:
            with self.subTest(extra):
                self.assertTrue(mentions(contract.check_sections_spec({**base, **extra}), word), contract.check_sections_spec({**base, **extra}))
        self.assertEqual(contract.check_sections_spec({**base, "front_matter": "bullets", "coerce": {"a": "list"}}), [])

    def test_R12_a_misspelled_front_matter_no_longer_skips_the_header_check(self):
        schema = contract.load_schema(sp("C05"))
        spec = dict(contract.load_sections_spec(sp("C05")))
        spec["front_matter"] = "bulets"
        errs = contract.validate_markdown("# x\n", schema, spec)
        self.assertTrue(mentions(errs, "front_matter"), errs)

    def test_R13_a_date_must_exist_on_the_calendar(self):
        tech = json.loads(read("C25", "valid-matrix-row-only.json"))
        tech.pop("_why", None)
        self.assertEqual(check_doc("C25", tech), [])
        for bad in ("2026-13-45", "2026-02-31", "2026-00-10", "2026-04-31"):
            with self.subTest(bad):
                self.assertTrue(mentions(check_doc("C25", {**tech, "verified_date": bad}), "date"))
        self.assertEqual(check_doc("C25", {**tech, "verified_date": "2028-02-29"}), [])
        self.assertTrue(check_doc("C25", {**tech, "verified_date": "2027-02-29"}))

    def test_R13_c09_and_c23_dates_too(self):
        text = read("C09", "valid-pass-with-fixes.md").replace("date: 2026-10-11", "date: 2026-02-31")
        self.assertTrue(mentions(check_text("C09", text), "date"))
        row = SIZING.replace("2026-10-12 |", "2026-13-45 |", 1)
        self.assertTrue(check_text("C23", row))

    def test_R13_the_dialect_supports_format_date_only(self):
        self.assertEqual(contract.check_schema({"type": "string", "format": "date"}), [])
        self.assertTrue(contract.check_schema({"type": "string", "format": "email"}))
        self.assertEqual(contract.validate("2026-10-12", {"type": "string", "format": "date"}), [])
        self.assertTrue(contract.validate("2026-10-32", {"type": "string", "format": "date"}))
        self.assertTrue(contract.validate("2026-1-1", {"type": "string", "format": "date"}))

    def test_R14_fixture_keys_are_stripped_only_from_fixture_files(self):
        doc = json.loads(read("C07", "valid-one-entry.json"))
        doc["_why"] = "x"
        doc["_recorded"] = False
        self.assertTrue(mentions(check_doc("C07", doc, name="test-locks.json"), "_why"))
        self.assertEqual(check_doc("C07", doc, name="valid-lock.json"), [])
        self.assertTrue(check_doc("C07", {**doc, "_expect": "x"}, name="test-locks.json"))

    def test_R15_a_recheck_line_in_a_code_fence_does_not_count(self):
        text = read("C09", "valid-pass-with-fixes.md").replace("Re-check: F-2 verified at abc1234.", "```\nRe-check: F-2 verified at abc1234.\n```")
        self.assertTrue(mentions(check_text("C09", text), "re-check"))

    def test_R15_each_fixed_finding_needs_its_own_recheck_line(self):
        text = read("C09", "invalid-two-fixed-findings-one-recheck-line.md")
        self.assertTrue(mentions(check_text("C09", text), "re-check", "F-2"))
        self.assertEqual(check_text("C09", text.replace("Re-check: F-1 verified.", "Re-check: F-1 verified.\nRe-check: F-2 verified.")), [])

    def test_R15_a_recheck_line_for_another_id_does_not_count(self):
        text = read("C09", "valid-pass-with-fixes.md").replace("Re-check: F-2 verified", "Re-check: F-9 verified")
        self.assertTrue(mentions(check_text("C09", text), "re-check", "F-2"))

    def test_R16_two_live_locks_for_one_path_are_refused(self):
        doc = json.loads(read("C07", "valid-one-entry.json"))
        doc.pop("_why", None)
        second = dict(doc["entries"][0], sha256="b" * 64)
        errs = check_doc("C07", {**doc, "entries": [doc["entries"][0], second]})
        self.assertTrue(mentions(errs, "live", "tests/test_a.py"), errs)

    def test_R16_a_superseded_lock_is_not_live(self):
        doc = json.loads(read("C07", "valid-superseding.json"))
        doc.pop("_why", None)
        self.assertEqual(check_doc("C07", doc), [])

    def test_R16_a_supersedes_that_names_no_entry_leaves_two_live_locks(self):
        doc = json.loads(read("C07", "valid-superseding.json"))
        doc.pop("_why", None)
        doc["entries"][1]["supersedes"] = "c" * 64
        self.assertTrue(mentions(check_doc("C07", doc), "live"))

    def test_R17_the_reserved_trailer_key_has_one_spelling(self):
        msg = "[green] T-001 add the parser\n\nbody\n\n{key}: CR-1\n"
        self.assertEqual(check_text("C32", msg.format(key="Test-Change-Approved")), [])
        for key in ("test-change-approved", "TEST-CHANGE-APPROVED", "Test-change-approved"):
            with self.subTest(key):
                self.assertTrue(mentions(check_text("C32", msg.format(key=key)), "Test-Change-Approved"))

    def test_R17_the_grammar_says_the_key_is_case_sensitive_on_write(self):
        text = json.loads(sp("C32").read_text(encoding="utf-8"))["description"]
        self.assertIn("case", text.lower())


# ------------------------------------------------------------------ the whole set


class R19(unittest.TestCase):
    """Decisions 11 and 12: the typed approval prefix, the test change requests contract, the hooks shell enum."""

    def _c06(self):
        doc = json.loads(read("C06", "valid-full.json"))
        doc.pop("_why", None)
        return doc

    def test_R19_the_approval_carries_the_typed_prefix_of_the_spec_hash(self):
        doc = self._c06()
        self.assertEqual(doc["approved_spec_sha256_prefix"], doc["spec_sha256"][:12])
        self.assertEqual(check_doc("C06", doc), [])

    def test_R19_a_prefix_that_differs_from_the_spec_hash_is_refused(self):
        doc = self._c06()
        other = "0" if doc["spec_sha256"][0] != "0" else "1"
        doc["approved_spec_sha256_prefix"] = other + doc["spec_sha256"][1:12]
        self.assertTrue(mentions(check_doc("C06", doc), "first 12 characters"))

    def test_R19_the_prefix_is_required_and_twelve_lowercase_hex(self):
        doc = self._c06()
        self.assertTrue(mentions(check_doc("C06", {k: v for k, v in doc.items() if k != "approved_spec_sha256_prefix"}), "approved_spec_sha256_prefix"))
        for bad in (doc["spec_sha256"][:11], doc["spec_sha256"][:12].upper() + "A", "g" * 12):
            self.assertTrue(check_doc("C06", {**doc, "approved_spec_sha256_prefix": bad}))

    def test_R19_c33_is_the_markdown_table_of_test_change_requests(self):
        self.assertIsNotNone(sp("C33"))
        ok = read("C33", "valid-approved-and-rejected.md")
        self.assertEqual(check_text("C33", ok), [])
        self.assertTrue(mentions(check_text("C33", ok.replace("| approved | felipe |", "| approved |  |")), "decided"))
        self.assertTrue(mentions(check_text("C33", ok.replace("CR-002", "CR-001")), "duplicate"))
        self.assertTrue(check_text("C33", ok.replace("| rejected |", "| denied |")))

    def test_R19_c33_id_is_the_c07_change_request_pattern(self):
        c07 = json.loads(sp("C07").read_text(encoding="utf-8"))["$defs"]["entry"]["properties"]["change_request"]
        c33 = json.loads(sp("C33").read_text(encoding="utf-8"))["$defs"]["request_row"]["properties"]["Id"]
        self.assertEqual(c07["pattern"], c33["pattern"])
        self.assertIn("C33", c07["description"])
        self.assertIn("C33", (CONTRACTS / "README.md").read_text(encoding="utf-8"))

    def test_R19_the_hooks_shell_is_bash_or_powershell(self):
        for shell in ("bash", "powershell"):
            self.assertEqual(check_doc("C31", hooks_doc(shell=shell)), [])
        self.assertTrue(check_doc("C31", hooks_doc(shell="zsh")))


class Skip(unittest.TestCase):
    def test_SKIP_is_a_c20_tag_and_an_output_tag(self):
        from batuta_lib import output
        enum = json.loads(sp("C20").read_text(encoding="utf-8"))["$defs"]["item"]["properties"]["tag"]["enum"] \
            if "item" in json.loads(sp("C20").read_text(encoding="utf-8")).get("$defs", {}) else None
        if enum is None:
            enum = re.search(r'"enum": \[([^\]]*"SAME"[^\]]*)\]', sp("C20").read_text(encoding="utf-8")).group(1)
            enum = re.findall(r'"([A-Z]+)"', enum)
        self.assertIn("SKIP", enum)
        self.assertEqual(list(output.TAGS), enum)
        self.assertEqual(output.item("SKIP", "nothing to do")["tag"], "SKIP")
        self.assertEqual(output.exit_code([output.item("SKIP", "x"), output.item("OK", "y")]), 0)
        self.assertEqual(check_text("C20", read("C20", "valid-skip-item.json")), [])


class Whole(unittest.TestCase):
    def test_lint_of_the_shipped_contracts_is_clean(self):
        items = area.lint()
        bad = [i for i in items if i["tag"] in ("FAIL", "WARN")]
        self.assertEqual(bad, [])

    def test_every_invalid_fixture_breaks_exactly_one_rule(self):
        many = []
        for p in sorted(FX.glob("C*/invalid-*")):
            cid = p.parent.name
            if sp(cid) is None:
                continue
            errs = contract.validate_file(p, sp(cid))
            if len(errs) != 1:
                many.append((f"{cid}/{p.name}", len(errs)))
        self.assertEqual(many, [])

    def test_the_upstream_record_is_dated_and_names_its_commit(self):
        rec = json.loads((FX / "_upstream" / "sizing_check.recorded.json").read_text(encoding="utf-8"))
        self.assertRegex(rec["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(rec["commit"], r"^[0-9a-f]{7,40}$")


if __name__ == "__main__":
    unittest.main()
