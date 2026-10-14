"""spec new and spec lint: templates, C05, runnable gates, interfaces against the catalog, never-reused ids, tiers."""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import CONTRACTS, SPEC, SPEC_ID, make_project, messages, run_json, write  # noqa: E402
from batuta_lib import contract as core  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_project(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def lint(self, *extra):
        return run_json("spec", "lint", "--root", self.root, *extra)

    def clear_specs(self):
        for d in (self.root / "specs").iterdir():
            if d.name != "000-foundation":
                shutil.rmtree(d)

    def spec_text(self):
        return (self.root / f"specs/{SPEC_ID}/spec.md").read_text(encoding="utf-8")

    def edit(self, old, new, rel=f"specs/{SPEC_ID}/spec.md"):
        p = self.root / rel
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        write(self.root, rel, text.replace(old, new))


class SpecNew(Base):
    def new(self, *extra, apply=True):
        return run_json("spec", "new", "--root", self.root, "--owner", "alex", *extra, *(["--apply"] if apply else []))

    def test_dry_run_writes_nothing(self):
        before = sorted(p.as_posix() for p in self.root.rglob("*"))
        code, doc, _ = self.new("--title", "Rate limits", apply=False)
        self.assertEqual(code, 0, messages(doc))
        self.assertEqual(before, sorted(p.as_posix() for p in self.root.rglob("*")))
        self.assertTrue(any(i["tag"] == "NEW" for i in doc["items"]))

    def test_creates_the_feature_folder_from_the_templates(self):
        code, doc, _ = self.new("--title", "Rate limits", "--tier", "M")
        self.assertEqual(code, 0, messages(doc))
        folder = self.root / "specs/002-rate-limits"
        for name in ("spec.md", "plan.md", "tasks.md"):
            self.assertTrue((folder / name).is_file(), name)
        self.assertFalse((folder / "test-change-requests.md").exists())
        self.assertTrue((folder / "approvals").is_dir())
        self.assertTrue((folder / "evidence").is_dir())
        text = (folder / "spec.md").read_text(encoding="utf-8")
        self.assertIn("id: 002-rate-limits", text)
        self.assertIn("status: Draft", text)
        self.assertIn("tier: M", text)
        self.assertNotIn("{{", text)
        self.assertIn("| Id | Kind | EARS text | Gate | Verification | Status |", text)
        self.assertIn("## Interfaces", text)

    def test_next_number_skips_the_foundation_and_counts_existing(self):
        code, doc, _ = self.new("--title", "Second one")
        self.assertTrue((self.root / "specs/002-second-one").is_dir())
        code, doc, _ = self.new("--title", "Third one")
        self.assertTrue((self.root / "specs/003-third-one").is_dir())

    def test_first_spec_of_an_empty_project_is_001_and_gets_a_constitution(self):
        with tempfile.TemporaryDirectory() as empty:
            code, doc, _ = run_json("spec", "new", "--root", empty, "--title", "Hello", "--owner", "alex", "--apply")
            self.assertEqual(code, 0, messages(doc))
            self.assertTrue((Path(empty) / "specs/001-hello/spec.md").is_file())
            self.assertTrue((Path(empty) / "specs/000-foundation/constitution.md").is_file())

    def test_tier_s_has_no_plan_and_bad_tier_is_refused(self):
        self.new("--title", "Tiny", "--tier", "S")
        self.assertFalse((self.root / "specs/002-tiny/plan.md").exists())
        code, doc, err = run_json("spec", "new", "--root", self.root, "--title", "X", "--tier", "Q")
        self.assertNotEqual(code, 0)

    def test_fresh_spec_lints_clean_and_its_examples_count_for_nothing(self):
        self.new("--title", "Rate limits", "--tier", "L")
        code, doc, _ = self.lint("--spec", "002-rate-limits")
        self.assertEqual(code, 0, messages(doc))
        folder = self.root / "specs/002-rate-limits"
        self.assertIn("<!--", (folder / "spec.md").read_text(encoding="utf-8"))
        self.assertIn("<!--", (folder / "tasks.md").read_text(encoding="utf-8"))

    def test_spec_new_writes_no_change_request_file_and_the_template_stays_for_the_first_request(self):
        self.new("--title", "Rate limits")
        self.assertFalse((self.root / "specs/002-rate-limits/test-change-requests.md").exists())
        text = (CONTRACTS.parent / "templates" / "spec" / "test-change-requests.md").read_text(encoding="utf-8")
        self.assertIn("| Id | Date | Test path | Requirement | Reason | Proposed change | Status | Decided by |", text)

    def test_a_fresh_spec_lints_clean_with_a_skip_for_the_empty_tasks(self):
        self.new("--title", "Rate limits", "--tier", "L")
        code, doc, _ = self.lint("--spec", "002-rate-limits")
        self.assertEqual(code, 0, messages(doc))
        self.assertTrue(any(i["tag"] == "SKIP" and "tasks" in i["message"] for i in doc["items"]), messages(doc))

    def test_apply_prints_new_for_the_folders_it_creates(self):
        code, doc, _ = self.new("--title", "Rate limits")
        tags = {i["message"]: i["tag"] for i in doc["items"]}
        self.assertEqual(tags["002-rate-limits/approvals/"], "NEW")
        self.assertEqual(tags["002-rate-limits/evidence/"], "NEW")

    def test_templates_ship_generic_content(self):
        folder = CONTRACTS.parent / "templates" / "spec"
        for name in ("spec.md", "plan.md", "tasks.md", "constitution.md", "test-change-requests.md", "adr.md"):
            text = (folder / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"[A-Za-z]:[\\/]Users|/home/\w+/", name)
        const = (folder / "constitution.md").read_text(encoding="utf-8")
        for tier in ("Tier S", "Tier M", "Tier L"):
            self.assertIn(tier, const)
        self.assertIn("Simpler alternative rejected", (folder / "plan.md").read_text(encoding="utf-8"))
        self.assertIn("Constitution check", (folder / "plan.md").read_text(encoding="utf-8"))


class SpecLint(Base):
    def fails(self, doc):
        return " | ".join(messages(doc, "FAIL"))

    def test_valid_review_spec_passes(self):
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_requirement_without_a_runnable_gate_fails(self):
        for bad in ("TBD", "manual review", "pytest tests/test_alerts.py", "-", "`TODO`", "n/a"):
            with self.subTest(gate=bad):
                write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace("`pytest tests/test_alerts.py`", bad))
                code, doc, _ = self.lint()
                self.assertEqual(code, 1)
                self.assertIn("REQ-ALR-001", self.fails(doc))

    def test_retired_row_may_keep_a_loose_gate(self):
        text = SPEC.replace("`pytest tests/test_alerts.py` | unit test | active", "TBD | unit test | retired")
        write(self.root, f"specs/{SPEC_ID}/spec.md", text)
        code, doc, _ = self.lint()
        self.assertNotIn("REQ-ALR-001: gate", self.fails(doc))

    def test_needs_clarification_fails_at_review_and_frozen_not_at_draft(self):
        text = SPEC.replace("None.", "[NEEDS CLARIFICATION] what is the limit?")
        write(self.root, f"specs/{SPEC_ID}/spec.md", text)
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        write(self.root, f"specs/{SPEC_ID}/spec.md", text.replace("status: Review", "status: Draft"))
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_interface_that_is_not_a_catalog_row_fails(self):
        self.edit("- alert-list:", "- ghost-contract:")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("ghost-contract", self.fails(doc))

    def test_no_catalog_reports_the_interfaces_unresolved_with_the_path(self):
        (self.root / "docs/contracts/catalog.md").unlink()
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("docs/contracts/catalog.md", self.fails(doc))

    def test_empty_interfaces_with_tasks_naming_contracts_fails(self):
        text = SPEC.replace("- alert-event: produced by the pipeline, consumed by the API.\n- alert-list: produced by the API, consumed by the page.", "none")
        write(self.root, f"specs/{SPEC_ID}/spec.md", text)
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("T-001", self.fails(doc))

    def test_task_contract_missing_from_interfaces_fails(self):
        self.edit("| alert-list | T-001 |", "| alert-event | T-001 |", f"specs/{SPEC_ID}/tasks.md")
        self.edit("- alert-list: produced by the API, consumed by the page.", "- alert-event: again.")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))
        self.edit("| alert-event | T-001 |", "| alert-list | T-001 |", f"specs/{SPEC_ID}/tasks.md")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_ids_are_never_reused_across_specs(self):
        other = SPEC.replace("001-alerts", "002-other").replace("status: Review", "status: Draft")
        write(self.root, "specs/002-other/spec.md", other)
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("REQ-ALR-001", self.fails(doc))
        self.assertIn("002-other", self.fails(doc))

    def test_a_retired_id_reused_in_another_spec_fails(self):
        self.edit("`node --test tests/api.test.js` | unit test | active", "`node --test tests/api.test.js` | unit test | retired")
        other = SPEC.replace("001-alerts", "002-other").replace("status: Review", "status: Draft")
        write(self.root, "specs/002-other/spec.md", other.replace("REQ-ALR-001", "REQ-NEW-001").replace("REQ-ALR-002", "REQ-NEW-002"))
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("REQ-ALR-003", self.fails(doc))

    def test_commented_template_rows_are_not_requirements(self):
        text = SPEC.replace("## Edge cases", "<!--\n| REQ-ALR-001 | ubiquitous | example | TBD | x | active |\n-->\n\n## Edge cases")
        write(self.root, f"specs/{SPEC_ID}/spec.md", text)
        other = SPEC.replace("001-alerts", "002-other").replace("status: Review", "status: Draft")
        code, doc, _ = self.lint("--spec", SPEC_ID)
        self.assertEqual(code, 0, messages(doc))

    def test_folder_name_must_equal_the_spec_id(self):
        write(self.root, "specs/009-wrong/spec.md", SPEC.replace("001-alerts", "003-alerts").replace("REQ-ALR", "REQ-ZZZ"))
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("009-wrong", self.fails(doc))

    def test_plan_needs_a_constitution_check_with_the_rejected_alternative_for_tiers_m_and_l(self):
        (self.root / f"specs/{SPEC_ID}/plan.md").unlink()
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        write(self.root, f"specs/{SPEC_ID}/plan.md", "# Plan\n\n## Design\nx\n")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("Constitution check", self.fails(doc))
        write(self.root, f"specs/{SPEC_ID}/plan.md",
              "# Plan\n\n## Constitution check\n\n| Decision | Article | Simpler alternative rejected |\n|---|---|---|\n| a | Art. 1 | |\n")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("Simpler alternative rejected", self.fails(doc))

    def test_tier_s_needs_no_plan(self):
        (self.root / f"specs/{SPEC_ID}/plan.md").unlink()
        self.edit("tier: M", "tier: S")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_tier_l_needs_an_adr_reference(self):
        self.edit("tier: M", "tier: L")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))
        self.edit("Decision context: ADR-0001.", "")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("ADR", self.fails(doc))

    def test_named_test_file_missing_is_a_warning_at_review_and_a_failure_when_frozen(self):
        (self.root / "tests/api.test.js").unlink()
        code, doc, _ = self.lint()
        self.assertEqual(code, 2)
        self.edit("status: Review", "status: Frozen")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_tasks_naming_an_unknown_requirement_fails(self):
        self.edit("REQ-ALR-002 | alert-list", "REQ-ALR-009 | alert-list", f"specs/{SPEC_ID}/tasks.md")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("REQ-ALR-009", self.fails(doc))

    def test_unknown_referenced_adr_is_a_warning_not_a_failure(self):
        self.edit("ADR-0001.", "ADR-0001 and ADR-0042.")
        code, doc, _ = self.lint()
        self.assertEqual(code, 2)
        self.assertTrue(any("ADR-0042" in m for m in messages(doc, "WARN")))

    def test_invalid_c05_fixtures_are_rejected_for_their_stated_reason(self):
        for fx in sorted((CONTRACTS / "fixtures" / "C05").glob("invalid-*.md")):
            with self.subTest(fixture=fx.name):
                text = fx.read_text(encoding="utf-8")
                self.clear_specs()
                m_id = re.search(r"^id:\s*(\S+)", text, re.M)
                folder = m_id.group(1) if m_id and re.fullmatch(r"\d{3}-[a-z0-9-]+", m_id.group(1)) else "001-validator"
                write(self.root, f"specs/{folder}/spec.md", text)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1)
                m = re.search(r"<!--\s*expect:\s*(.*?)\s*-->", text)
                if m:
                    self.assertIn(m.group(1).lower(), self.fails(doc).lower())

    def test_valid_c05_fixtures_do_not_fail_the_c05_rules(self):
        for fx in sorted((CONTRACTS / "fixtures" / "C05").glob("valid-*.md")):
            with self.subTest(fixture=fx.name):
                text = fx.read_text(encoding="utf-8")
                self.clear_specs()
                write(self.root, "specs/001-validator/spec.md", text)
                code, doc, _ = self.lint()
                self.assertNotIn("front matter", self.fails(doc))
                self.assertNotIn("section", self.fails(doc))
                schema = core.load_schema(core.find_schema(CONTRACTS, "C05"))
                self.assertEqual(core.validate_file(fx, core.find_schema(CONTRACTS, "C05")), [])


if __name__ == "__main__":
    unittest.main()
