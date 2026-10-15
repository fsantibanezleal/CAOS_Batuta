"""dispatch ledger records: the row of a run, written through the one ledger writer (unit U13, D4)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from batuta_lib import delegation  # noqa: E402
from batuta_lib.dispatch import ledger  # noqa: E402

BASE = ("# Delegation ledger\n\n| ID | Agent | Model | Brief | Report | Status | Accepted |\n|---|---|---|---|---|---|---|\n"
        "| a-2026-10-10 | searcher | haiku | b/a.brief.md | b/a.report.md | drafted | no |\n"
        "| z-2026-10-10 | searcher | haiku | b/z.brief.md | b/z.report.md | accepted | y |\n")
VALUES = {"Model": "gpt-5", "Provider": "openai", "Tokens in": 10, "Tokens out": 5, "Cost USD": 0.01, "Status": "complete"}


class Record(unittest.TestCase):
    def test_updates_an_existing_row_through_update_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "delegation" / "ledger.md"
            path.parent.mkdir()
            path.write_text(BASE, encoding="utf-8")
            ledger.record(path, "a-2026-10-10", VALUES, defaults={"Agent": "searcher", "Brief": "b/a.brief.md", "Report": "b/a.report.md"})
            self.assertIn("openai", path.read_text(encoding="utf-8"))
            self.assertFalse(list(path.parent.glob(".ledger-*")))      # no temp file left behind

    def test_adds_a_row_when_the_brief_has_none_and_creates_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "delegation" / "ledger.md"
            ledger.record(path, "n-2026-10-10", VALUES, defaults={"Agent": "searcher", "Brief": "b/n.brief.md", "Report": "b/n.report.md"})
            columns, rows = delegation.ledger_rows(path.read_text(encoding="utf-8"))
            self.assertEqual(rows[0]["ID"], "n-2026-10-10")
            self.assertEqual(rows[0]["Provider"], "openai")
            self.assertEqual(delegation.ledger_problems(path.read_text(encoding="utf-8")), [])

    def test_a_billed_row_without_its_numbers_is_refused_by_the_contract_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.md"
            path.write_text(BASE, encoding="utf-8")
            with self.assertRaises(delegation.LedgerError):
                ledger.record(path, "a-2026-10-10", {"Provider": "openai", "Status": "complete"}, defaults={})
            self.assertEqual(path.read_text(encoding="utf-8"), BASE)


if __name__ == "__main__":
    unittest.main()
