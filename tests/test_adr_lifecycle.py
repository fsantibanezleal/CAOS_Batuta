"""adr new and adr lint: C24 front matter, review triggers, supersession links, technology evaluations."""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import ADR, CONTRACTS, TECH, TODAY, make_project, messages, run_json, write  # noqa: E402
from batuta_lib import contract as core  # noqa: E402


class AdrLifecycle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_project(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def lint(self, *extra):
        return run_json("adr", "lint", "--root", self.root, "--today", TODAY, *extra)

    def adr(self, number, status="Accepted", **extra):
        text = ADR.replace("ADR-0001", f"ADR-{number:04d}").replace("status: Accepted", f"status: {status}")
        for key, value in extra.items():
            if re.search(rf"^{key}:", text, re.M):
                text = re.sub(rf"^{key}:.*$", f"{key}: {value}", text, flags=re.M)
            else:
                text = text.replace("\n---\n\n## Context", f"\n{key}: {value}\n---\n\n## Context", 1)
        for old in (self.root / "docs/decisions").glob(f"ADR-{number:04d}-*.md"):
            old.unlink()
        write(self.root, f"docs/decisions/ADR-{number:04d}-x.md", text)

    def test_new_without_apply_writes_nothing_and_with_apply_takes_the_next_number(self):
        code, doc, _ = run_json("adr", "new", "--root", self.root, "--title", "Queue choice")
        self.assertEqual(code, 0)
        self.assertEqual(len(list((self.root / "docs/decisions").glob("*.md"))), 1)
        code, doc, _ = run_json("adr", "new", "--root", self.root, "--title", "Queue choice", "--apply")
        self.assertEqual(code, 0, messages(doc))
        made = self.root / "docs/decisions/ADR-0002-queue-choice.md"
        self.assertTrue(made.is_file())
        text = made.read_text(encoding="utf-8")
        self.assertIn("id: ADR-0002", text)
        self.assertIn("status: Proposed", text)
        schema_path = core.find_schema(CONTRACTS, "C24")
        self.assertEqual(core.validate_file(made, schema_path), [])

    def test_new_starts_at_one_without_a_folder(self):
        with tempfile.TemporaryDirectory() as empty:
            code, doc, _ = run_json("adr", "new", "--root", empty, "--title", "First", "--apply")
            self.assertEqual(code, 0)
            self.assertTrue((Path(empty) / "docs/decisions/ADR-0001-first.md").is_file())

    def test_template_has_no_private_or_machine_content(self):
        text = (CONTRACTS.parent / "templates" / "spec" / "adr.md").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"[A-Za-z]:[\\/]Users")

    def test_valid_adr_passes(self):
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_no_adr_folder_is_skip(self):
        shutil.rmtree(self.root / "docs/decisions")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0)
        self.assertEqual([i["tag"] for i in doc["items"]][:1], ["SKIP"])

    def test_overdue_review_by_date_warns(self):
        self.adr(1, review_trigger="review-by: 2026-09-01")
        code, doc, _ = self.lint()
        self.assertEqual(code, 2)
        self.assertTrue(any("overdue" in m for m in messages(doc, "WARN")))

    def test_condition_review_trigger_is_not_overdue(self):
        self.adr(1, review_trigger="when the vendor changes its licence")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_superseded_without_a_valid_link_fails(self):
        self.adr(1, status="Superseded", superseded_by="ADR-0009")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("ADR-0009" in m for m in messages(doc, "FAIL")))

    def test_supersession_must_be_reciprocal(self):
        self.adr(1, status="Superseded", superseded_by="ADR-0002")
        self.adr(2, tech_evaluations="[]")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("supersedes" in m for m in messages(doc, "FAIL")), messages(doc))
        self.adr(2, tech_evaluations="[]", supersedes="[ADR-0001]")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_adr_superseding_itself_fails(self):
        self.adr(1, status="Superseded", superseded_by="ADR-0001")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("itself" in m for m in messages(doc, "FAIL")))
        self.adr(1, supersedes="[ADR-0001]")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_duplicate_ids_fail(self):
        write(self.root, "docs/decisions/ADR-0001-other.md", ADR)
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_filename_must_carry_the_id(self):
        write(self.root, "docs/decisions/ADR-0007-wrong.md", ADR)
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_accepted_adr_requires_decided_evaluations(self):
        (self.root / "docs/design/tech/fastapi.json").unlink()
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("fastapi" in m for m in messages(doc, "FAIL")))

    def test_accepted_adr_with_an_undecided_evaluation_fails(self):
        bare = {k: v for k, v in TECH.items() if k != "evaluation"}
        write(self.root, "docs/design/tech/fastapi.json", json.dumps(bare))
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("decided" in m for m in messages(doc, "FAIL")))

    def test_proposed_adr_may_leave_evaluations_open(self):
        (self.root / "docs/design/tech/fastapi.json").unlink()
        self.adr(1, status="Proposed")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_invalid_c24_fixtures_are_rejected_for_their_stated_reason(self):
        for fx in sorted((CONTRACTS / "fixtures" / "C24").glob("invalid-*.md")):
            with self.subTest(fixture=fx.name):
                shutil.rmtree(self.root / "docs/decisions")
                text = fx.read_text(encoding="utf-8")
                write(self.root, "docs/decisions/ADR-0003-fixture.md", text)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1)
                m = re.search(r"<!--\s*expect:\s*(.*?)\s*-->", text)
                if m:
                    self.assertIn(m.group(1).lower(), " ".join(messages(doc, "FAIL")).lower())


if __name__ == "__main__":
    unittest.main()


class AdrCycles(AdrLifecycle):
    """F-07: supersession chains never loop, and a superseded ADR is not still Accepted."""

    def test_two_adrs_superseding_each_other_fail(self):
        self.adr(1, status="Superseded", superseded_by="ADR-0002", supersedes="[ADR-0002]")
        self.adr(2, status="Superseded", superseded_by="ADR-0001", supersedes="[ADR-0001]", tech_evaluations="[]")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("cycle" in m for m in messages(doc, "FAIL")), messages(doc))

    def test_a_three_cycle_fails(self):
        self.adr(1, status="Superseded", superseded_by="ADR-0002", supersedes="[ADR-0003]")
        self.adr(2, status="Superseded", superseded_by="ADR-0003", supersedes="[ADR-0001]", tech_evaluations="[]")
        self.adr(3, status="Superseded", superseded_by="ADR-0001", supersedes="[ADR-0002]", tech_evaluations="[]")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("cycle" in m for m in messages(doc, "FAIL")), messages(doc))

    def test_an_accepted_or_proposed_adr_with_superseded_by_fails(self):
        for status in ("Accepted", "Proposed"):
            self.adr(1, status=status, superseded_by="ADR-0002")
            self.adr(2, tech_evaluations="[]", supersedes="[ADR-0001]")
            code, doc, _ = self.lint()
            self.assertEqual(code, 1, status)
            self.assertTrue(any("superseded_by" in m and status in m for m in messages(doc, "FAIL")), messages(doc))

    def test_a_straight_chain_passes(self):
        self.adr(1, status="Superseded", superseded_by="ADR-0002")
        self.adr(2, status="Superseded", superseded_by="ADR-0003", supersedes="[ADR-0001]", tech_evaluations="[]")
        self.adr(3, tech_evaluations="[]", supersedes="[ADR-0002]")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))
