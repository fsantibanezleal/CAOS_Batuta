"""report ledger-status: the Status column follows the reports (unit U2, D3)."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import CONTRACTS, FIXTURES, TempCase, report_text, run, run_json  # noqa: E402

from batuta_lib import contract  # noqa: E402

C04_FIX = CONTRACTS / "fixtures" / "C04"


class LedgerStatus(TempCase):
    def status(self, *extra):
        return run("report", "ledger-status", "--root", self.root, *extra)

    def report_path(self, brief):
        return Path(re.search(r"^- report: (.+)$", brief.read_text(encoding="utf-8"), re.M).group(1))

    def cell(self, ident, column=5):
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"| {ident} "):
                return [c.strip() for c in line.strip("|").split("|")][column]

    def test_a_report_not_written_yet_is_pending_and_dry_run_changes_nothing(self):
        self.filled_brief()
        before = self.ledger.read_bytes()
        code, out, _ = self.status()
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"alpha-2026-10-10.*pending|PENDING.*alpha-2026-10-10")
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_write_updates_the_status_column_only(self):
        brief = self.filled_brief("alpha", "searcher")
        before = self.ledger.read_text(encoding="utf-8")
        self.report_path(brief).write_text(report_text([("D1", "DONE", "`a`")]), encoding="utf-8")
        code, out, _ = self.status("--write")
        self.assertEqual(code, 0, out)
        after = self.ledger.read_text(encoding="utf-8")
        self.assertEqual(after, before.replace("| drafted |", "| complete |"))
        self.assertEqual(contract.validate_file(self.ledger, contract.find_schema(CONTRACTS, "C04")), [])
        code, _out, _ = self.status("--write")  # idempotent
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), after)

    def test_incomplete_and_defective(self):
        a = self.filled_brief("inc", "searcher")
        b = self.filled_brief("def", "searcher")
        self.report_path(a).write_text(report_text([("D1", "PARTIAL", "half")]), encoding="utf-8")
        self.report_path(b).write_text("# nothing\n", encoding="utf-8")
        code, out, _ = self.status("--write")
        self.assertEqual(code, 1, out)
        self.assertEqual(self.cell("inc-2026-10-10"), "incomplete")
        self.assertEqual(self.cell("def-2026-10-10"), "defective")

    def test_a_report_that_was_deleted_is_lost(self):
        brief = self.filled_brief("alpha", "searcher")
        rep = self.report_path(brief)
        rep.write_text(report_text([("D1", "DONE", "`a`")]), encoding="utf-8")
        self.status("--write")
        self.assertEqual(self.cell("alpha-2026-10-10"), "complete")
        rep.unlink()
        code, out, _ = self.status("--write")
        self.assertEqual(self.cell("alpha-2026-10-10"), "lost")
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"lost")

    def test_accepted_and_superseded_rows_are_kept(self):
        self.filled_brief("one", "searcher")
        self.filled_brief("two", "searcher")
        text = self.ledger.read_text(encoding="utf-8")
        text = re.sub(r"(one-2026-10-10 \|[^\n]*\| )drafted \| no \|", r"\1accepted | y |", text)
        self.ledger.write_text(text, encoding="utf-8", newline="\n")
        self.report_path(next(self.ledger.parent.glob("one-*.brief.md"))).write_text(
            report_text([("D1", "DONE", "`a`")]), encoding="utf-8")
        self.status("--write")
        self.assertEqual(self.cell("one-2026-10-10"), "accepted")
        self.assertEqual(self.cell("one-2026-10-10", 6), "y")  # the alias is never rewritten
        self.assertEqual(self.cell("two-2026-10-10"), "pending")

    def test_dispatch_outcomes_and_billed_columns_are_preserved(self):
        self.ledger.parent.mkdir(parents=True)
        text = re.sub(r"^(<!--.*-->\n)+", "", (C04_FIX / "valid-run-outcomes-timeout-error-over-budget.md").read_text(encoding="utf-8"))
        self.ledger.write_text(text, encoding="utf-8", newline="\n")
        self.status("--write")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), text)

    def test_the_caos_ledger_round_trips_through_write(self):
        self.ledger.parent.mkdir(parents=True)
        text = (FIXTURES / "ledger-caos-pending.md").read_text(encoding="utf-8")
        self.ledger.write_text(text, encoding="utf-8", newline="\n")
        for line in text.splitlines():  # the briefs the rows name exist; their reports are not written yet
            if line.startswith(("| alpha", "| beta")):
                brief = self.root / line.split("|")[4].strip()
                brief.parent.mkdir(parents=True, exist_ok=True)
                brief.write_text("# Brief\n", encoding="utf-8")
        code, out, _ = self.status("--write")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), text, out)

    def test_an_empty_ledger_has_no_rows_and_is_not_an_error(self):
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text("# Delegation ledger: x\n\n| ID | Agent | Model | Brief | Report | Status | Accepted |\n"
                               "|---|---|---|---|---|---|---|\n", encoding="utf-8")
        code, out, _ = self.status()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"no rows")

    def test_a_missing_ledger_is_a_failure(self):
        code, out, err = self.status()
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out + err)

    def test_a_brief_that_is_missing_is_defective(self):
        brief = self.filled_brief()
        brief.unlink()
        code, out, _ = self.status("--write")
        self.assertEqual(code, 1)
        self.assertEqual(self.cell("alpha-2026-10-10"), "defective")

    def test_every_invalid_c04_fixture_is_rejected_with_its_reason(self):
        for fx in sorted(C04_FIX.glob("invalid-*.md")):
            _why, expect = contract.fixture_meta(fx)
            self.ledger.parent.mkdir(parents=True, exist_ok=True)
            self.ledger.write_text(fx.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
            code, out, _ = self.status("--write")
            if fx.name == "invalid-no-rows.md":
                self.assertEqual(code, 0, out)  # a header-only ledger is the empty ledger, not a defect
                continue
            self.assertEqual(code, 1, fx.name)
            self.assertIn(expect, out, fx.name)
            self.assertEqual(self.ledger.read_text(encoding="utf-8"), fx.read_text(encoding="utf-8"), fx.name)

    def test_json_output(self):
        self.filled_brief()
        code, data, _ = run_json("report", "ledger-status", "--root", self.root)
        self.assertEqual((data["area"], data["verb"]), ("report", "ledger-status"))
        self.assertTrue(any("alpha-2026-10-10" in i["message"] for i in data["items"]))


if __name__ == "__main__":
    unittest.main()
