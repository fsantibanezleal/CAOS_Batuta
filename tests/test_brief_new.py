"""brief new: the brief from the template and its ledger row (unit U2, D2)."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import CONTRACTS, FIXTURES, TempCase, run, run_json, write_config  # noqa: E402

from batuta_lib import contract  # noqa: E402

NOTES_LEDGER = CONTRACTS / "fixtures" / "C04" / "valid-notes-column-before-the-dispatch-columns.md"


def ledger_problems(path):
    return contract.validate_file(path, contract.find_schema(CONTRACTS, "C04"))


class BriefNew(TempCase):
    def test_writes_the_brief_and_creates_the_ledger_with_the_c04_header(self):
        brief = self.new_brief()
        self.assertEqual(brief, self.root / ".batuta" / "delegation" / "alpha-2026-10-10.brief.md")
        text = brief.read_text(encoding="utf-8")
        self.assertIn("- id: alpha-2026-10-10\n", text)
        self.assertIn("- agent: implementer\n", text)
        self.assertIn("- kind: implement\n", text)
        self.assertIn("- model: sonnet (<fill:", text)
        ledger = self.ledger.read_text(encoding="utf-8")
        self.assertTrue(ledger.startswith("# Delegation ledger: demo\n\n| ID | Agent | Model | Brief | Report | Status | Accepted |\n|---|"))
        self.assertIn("| alpha-2026-10-10 | implementer | sonnet | .batuta/delegation/alpha-2026-10-10.brief.md "
                      "| .batuta/delegation/alpha-2026-10-10.report.md | drafted | no |", ledger)
        self.assertEqual(ledger_problems(self.ledger), [])

    def test_the_brief_report_line_is_absolute_and_the_ledger_paths_are_relative(self):
        brief = self.new_brief()
        report = re.search(r"^- report: (.+)$", brief.read_text(encoding="utf-8"), re.M).group(1)
        self.assertTrue(Path(report).is_absolute(), report)
        self.assertFalse(re.search(r"\| (/|[A-Za-z]:)", self.ledger.read_text(encoding="utf-8")))

    def test_the_agent_sets_model_and_kind(self):
        for agent, model, kind in (("searcher", "haiku", "lookup"), ("runner", "haiku", "run"),
                                   ("doc-writer", "sonnet", "docs"), ("reviewer", "opus", "review")):
            text = self.new_brief(f"t-{agent}", agent).read_text(encoding="utf-8")
            self.assertIn(f"- model: {model} (", text)
            self.assertIn(f"- kind: {kind}\n", text)

    def test_cpd_sections_only_for_implement_job_and_skeleton(self):
        impl = self.new_brief("a1", "implementer").read_text(encoding="utf-8")
        look = self.new_brief("a2", "searcher").read_text(encoding="utf-8")
        self.assertIn("## Must refute", impl)
        self.assertNotIn("## Must refute", look)
        job = self.new_brief("a3", "implementer", "--kind", "job").read_text(encoding="utf-8")
        self.assertIn("- kind: job\n", job)
        self.assertIn("## Production-path check", job)

    def test_general_purpose_needs_a_model(self):
        code, data, _ = run_json("brief", "new", "--slug", "d", "--topic", "t", "--agent", "general-purpose", "--title", "T",
                                 "--root", self.root)
        self.assertEqual(code, 1)
        self.assertIn("--model", json.dumps(data))
        text = self.new_brief("research", "general-purpose", "--model", "sonnet").read_text(encoding="utf-8")
        self.assertIn("- kind: research\n", text)

    def test_an_escalation_is_noted(self):
        code, out, _ = run("brief", "new", "--slug", "d", "--topic", "t", "--agent", "searcher", "--model", "sonnet",
                           "--title", "T", "--root", self.root)
        self.assertEqual(code, 0)
        self.assertRegex(out, r"pinned to haiku")

    def test_ids_that_collide_on_the_same_day_get_a_suffix(self):
        first = self.new_brief("same")
        second = self.new_brief("same")
        third = self.new_brief("same")
        self.assertEqual([first.name, second.name, third.name],
                         ["same-2026-10-10.brief.md", "same-2026-10-10-2.brief.md", "same-2026-10-10-3.brief.md"])
        self.assertIn("same-2026-10-10-3", self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(ledger_problems(self.ledger), [])

    def test_unicode_titles(self):
        brief = self.new_brief("uni", title="Inventario de scripts, version 2 (analisis, nino, cafe)")
        self.assertIn("# Brief: Inventario", brief.read_text(encoding="utf-8"))
        brief2 = self.new_brief("uni2", title="Prüfung der Zeichen: é ñ 中文")
        self.assertIn("é ñ 中文", brief2.read_text(encoding="utf-8"))

    def test_the_sizing_slot_is_written_when_given(self):
        brief = self.new_brief("sz", "implementer", "--sizing", "docs/sizing.md")
        self.assertIn("- sizing: docs/sizing.md\n", brief.read_text(encoding="utf-8"))
        self.assertNotIn("- sizing:", self.new_brief("sz2").read_text(encoding="utf-8"))

    def test_a_custom_coordination_root_from_the_configuration(self):
        write_config(self.root, coordination_root="coord")
        brief = self.new_brief("cr")
        self.assertEqual(brief.parent, self.root / "coord" / "delegation")
        self.assertTrue((self.root / "coord" / "delegation" / "ledger.md").is_file())

    def test_an_existing_ledger_keeps_its_rows_and_optional_columns_byte_for_byte(self):
        self.ledger.parent.mkdir(parents=True)
        original = re.sub(r"^(<!--.*-->\n)+", "", NOTES_LEDGER.read_text(encoding="utf-8"))
        self.ledger.write_text(original, encoding="utf-8", newline="\n")
        self.new_brief("keep")
        after = self.ledger.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(original.rstrip("\n")), after)
        added = after[len(original.rstrip("\n")):].strip("\n")
        cells = [c.strip() for c in added.strip("|").split("|")]
        self.assertEqual(len(cells), 12)  # every column of the existing header, optional ones empty
        self.assertEqual(cells[0], "keep-2026-10-10")
        self.assertEqual(ledger_problems(self.ledger), [])

    def test_crlf_ledger_keeps_its_line_endings(self):
        self.ledger.parent.mkdir(parents=True)
        original = (FIXTURES / "ledger-caos-new.md").read_bytes().replace(b"\n", b"\r\n")
        self.ledger.write_bytes(original)
        self.new_brief("crlf")
        data = self.ledger.read_bytes()
        self.assertTrue(data.startswith(original.rstrip(b"\r\n")))
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))

    def test_an_empty_ledger_with_only_the_header_takes_the_row(self):
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text("# Delegation ledger: x\n\n| ID | Agent | Model | Brief | Report | Status | Accepted |\n"
                               "|---|---|---|---|---|---|---|\n", encoding="utf-8")
        self.new_brief("empty")
        self.assertEqual(ledger_problems(self.ledger), [])

    def test_a_ledger_that_would_become_invalid_is_refused_and_left_alone(self):
        self.ledger.parent.mkdir(parents=True)
        text = (FIXTURES / "ledger-caos-new.md").read_text(encoding="utf-8").replace("alpha-2026-10-10-2", "alpha-2026-10-10")
        self.ledger.write_text(text, encoding="utf-8", newline="\n")
        code, data, _ = run_json("brief", "new", "--slug", "d", "--topic", "alpha", "--agent", "implementer", "--title", "T",
                                 "--root", self.root, "--date", "2026-10-10")
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", json.dumps(data))
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), text)

    def test_the_brief_validates_against_c02_once_filled(self):
        schema = contract.find_schema(CONTRACTS, "C02")
        for agent in ("implementer", "searcher", "doc-writer", "reviewer", "runner"):
            brief = self.filled_brief(f"c02-{agent}", agent)
            self.assertEqual(contract.validate_file(brief, schema), [], agent)

    def test_the_written_brief_has_no_unrendered_placeholder(self):
        text = self.new_brief("hyg").read_text(encoding="utf-8")
        self.assertNotIn("{{", text)
        self.assertNotIn("}}", text)


if __name__ == "__main__":
    unittest.main()
