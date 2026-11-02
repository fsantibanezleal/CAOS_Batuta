"""brief lint: every CAOS lint rule plus C02 (unit U2, D2)."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import CONTRACTS, TempCase, run  # noqa: E402

from batuta_lib import contract  # noqa: E402

FIX = CONTRACTS / "fixtures" / "C02"


def drop_section(text, title):
    return re.sub(rf"^## {re.escape(title)}\n.*?(?=^## |\Z)", "", text, flags=re.M | re.S)


class BriefLint(TempCase):
    def lint(self, brief):
        return run("brief", "lint", brief, "--root", self.root)

    def edit(self, brief, fn):
        brief.write_text(fn(brief.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")

    def test_a_fresh_brief_fails_with_the_unfilled_slots(self):
        brief = self.new_brief()
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"slot")
        self.assertIn("<fill", out)

    def test_a_filled_brief_passes(self):
        for n, agent in enumerate(("implementer", "searcher", "doc-writer", "reviewer", "runner")):
            brief = self.filled_brief(f"ok-{agent}", agent)
            self.edit(brief, lambda t, n=n: t.replace("src/area/, tests/area/", f"area{n}/"))
            code, out, _ = self.lint(brief)
            self.assertEqual(code, 0, (agent, out))
            self.assertIn("OK", out)

    def test_missing_definitions_fails(self):
        brief = self.filled_brief()
        self.edit(brief, lambda t: drop_section(t, "Definitions"))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 1)
        self.assertRegex(out.lower(), r"definitions")

    def test_missing_spec_fails_for_docs(self):
        brief = self.filled_brief("d1", "doc-writer")
        self.edit(brief, lambda t: drop_section(t, "Spec"))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 1)
        self.assertRegex(out.lower(), r"spec")

    def test_a_lookup_does_not_need_definitions_or_spec(self):
        brief = self.filled_brief("l1", "searcher")
        self.edit(brief, lambda t: drop_section(drop_section(t, "Definitions"), "Spec"))
        self.assertEqual(self.lint(brief)[0], 0)

    def test_each_cpd_section_is_required_for_implement(self):
        for n, title in enumerate(("ADR constraints", "Sizing reference", "Contracts", "Invariants and edge cases",
                                   "Missing-data behavior", "Environment and limits", "Owner prerequisites", "Shared files",
                                   "Must refute", "Production-path check")):
            brief = self.filled_brief(f"cpd-{n}")
            self.edit(brief, lambda t, title=title: drop_section(t, title))
            code, out, _ = self.lint(brief)
            self.assertEqual(code, 1, title)
            self.assertIn(title.lower(), out.lower(), title)

    def test_contracts_must_list_consumed_and_produced(self):
        brief = self.filled_brief()
        self.edit(brief, lambda t: t.replace("Consumed: alert v1 (alert.schema.json). Produced: report v1 (report.schema.json).",
                                             "Alert v1 and report v1."))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 1)
        self.assertRegex(out.lower(), r"consumed")

    def test_a_check_without_a_backticked_command_fails_for_implement(self):
        brief = self.filled_brief()
        self.edit(brief, lambda t: t.replace("- C1: `python -m unittest` exits 0", "- C1: the tests pass"))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"command")

    def test_missing_header_fields_fail(self):
        for n, key in enumerate(("working directory", "write scope", "budget")):
            brief = self.filled_brief(f"h-{n}")
            self.edit(brief, lambda t, key=key: re.sub(rf"^- {key}:.*\n", "", t, flags=re.M))
            code, out, _ = self.lint(brief)
            self.assertEqual(code, 1, key)
            self.assertIn(key, out, key)

    def test_no_deliverables_and_no_checks_fail(self):
        brief = self.filled_brief("nd")
        self.edit(brief, lambda t: re.sub(r"^- D1:.*\n", "", t, flags=re.M))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 1)
        self.assertRegex(out.lower(), r"deliverable")
        brief = self.filled_brief("nc")
        self.edit(brief, lambda t: drop_section(t, "Checks"))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 1)
        self.assertRegex(out.lower(), r"checks")

    def test_an_unknown_agent_and_a_bad_model_fail(self):
        brief = self.filled_brief("ua")
        self.edit(brief, lambda t: t.replace("- agent: implementer", "- agent: wizard"))
        self.assertEqual(self.lint(brief)[0], 1)
        brief = self.filled_brief("bm")
        self.edit(brief, lambda t: t.replace("- model: sonnet", "- model: gpt"))
        self.assertEqual(self.lint(brief)[0], 1)

    def test_a_relative_report_fails(self):
        brief = self.filled_brief("rr")
        self.edit(brief, lambda t: re.sub(r"^- report: .*$", "- report: reports/x.md", t, flags=re.M))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 1)
        self.assertIn("report", out)

    def test_an_escalation_is_a_warning_not_an_error(self):
        brief = self.filled_brief("es", "searcher", "--model", "sonnet")
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"WARN.*pinned to haiku")

    def test_fable_is_a_warning(self):
        brief = self.filled_brief("fb", "reviewer", "--model", "fable")
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 2, out)
        self.assertRegex(out.lower(), r"warn.*fable")

    def test_more_than_eight_deliverables_is_a_warning(self):
        brief = self.filled_brief("many")
        self.edit(brief, lambda t: t.replace("## Checks", "".join(f"- D{n}: another outcome\n" for n in range(2, 11)) + "\n## Checks"))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"WARN.*10 deliverables")

    def test_overlapping_write_scope_with_an_open_sibling_warns(self):
        self.filled_brief("one")
        second = self.filled_brief("two")
        code, out, _ = self.lint(second)
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"WARN.*overlaps.*one-2026-10-10")
        # a closed sibling (accepted) no longer counts
        text = re.sub(r"(one-2026-10-10 \|[^\n]*\| )drafted \| no \|", r"\1accepted | yes |",
                      self.ledger.read_text(encoding="utf-8"))
        self.ledger.write_text(text, encoding="utf-8", newline="\n")
        self.assertEqual(self.lint(second)[0], 0)

    def test_disjoint_write_scopes_do_not_warn(self):
        self.filled_brief("one")
        second = self.filled_brief("two")
        self.edit(second, lambda t: t.replace("src/area/, tests/area/", "docs/other/"))
        self.assertEqual(self.lint(second)[0], 0)

    def test_crlf_brief_passes(self):
        brief = self.filled_brief("crlf")
        brief.write_bytes(brief.read_bytes().replace(b"\n", b"\r\n"))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 0, out)

    def test_a_missing_brief_is_a_failure(self):
        code, out, err = self.lint(self.root / "nope.brief.md")
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out + err)

    def test_every_invalid_c02_fixture_is_rejected_with_its_reason(self):
        for fx in sorted(FIX.glob("invalid-*.md")):
            _why, expect = contract.fixture_meta(fx)
            code, out, _ = self.lint(fx)
            self.assertEqual(code, 1, fx.name)
            if expect:
                self.assertIn(expect, out, f"{fx.name}: expected {expect!r} in the output")

    def test_every_valid_c02_fixture_passes(self):
        for fx in sorted(FIX.glob("valid-*.md")):
            code, out, _ = self.lint(fx)
            self.assertIn(code, (0, 2), (fx.name, out))
            self.assertNotIn("FAIL", out, fx.name)


if __name__ == "__main__":
    unittest.main()
