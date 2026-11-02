"""delegation.ledger_set_cells: set cells of one ledger row, adding the optional columns when the header lacks them (moved from
the dispatch area so the ledger keeps one writer and one set of text functions)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_brief_support  # noqa: E402,F401  (puts the scripts folder on sys.path)

from batuta_lib import delegation  # noqa: E402

BASE = ("# Delegation ledger\n\n| ID | Agent | Model | Brief | Report | Status | Accepted |\n|---|---|---|---|---|---|---|\n"
        "| a-2026-10-10 | searcher | haiku | b/a.brief.md | b/a.report.md | drafted | no |\n"
        "| z-2026-10-10 | searcher | haiku | b/z.brief.md | b/z.report.md | accepted | y |\n")
VALUES = {"Model": "gpt-5", "Provider": "openai", "Tokens in": 10, "Tokens out": 5, "Cost USD": 0.01, "Status": "complete"}


class SetCells(unittest.TestCase):
    def test_adds_the_dispatch_columns_and_fills_the_row_only(self):
        new = delegation.ledger_set_cells(BASE, "a-2026-10-10", VALUES)
        columns, rows = delegation.ledger_rows(new)
        for col in ("Provider", "Tokens in", "Tokens out", "Cost USD"):
            self.assertIn(col, columns)
        a, z = rows
        self.assertEqual((a["Provider"], a["Tokens in"], a["Cost USD"], a["Status"], a["Model"]), ("openai", "10", "0.01", "complete", "gpt-5"))
        self.assertEqual((z["Provider"], z["Status"], z["Accepted"]), ("", "accepted", "y"))     # the alias y is kept as written
        self.assertEqual(delegation.ledger_problems(new), [])

    def test_is_idempotent(self):
        once = delegation.ledger_set_cells(BASE, "a-2026-10-10", VALUES)
        self.assertEqual(delegation.ledger_set_cells(once, "a-2026-10-10", VALUES), once)

    def test_keeps_crlf_and_free_text_notes(self):
        text = BASE.replace("| Accepted |", "| Accepted | Notes |").replace("|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|")
        text = text.replace("| drafted | no |", "| drafted | no | keep me |").replace("| accepted | y |", "| accepted | y | checked by hand |")
        text = text.replace("\n", "\r\n")
        new = delegation.ledger_set_cells(text, "a-2026-10-10", VALUES)
        self.assertNotIn("\r\r", new)
        self.assertEqual(new.count("\r\n"), new.count("\n"))
        self.assertIn("keep me", new)
        self.assertIn("checked by hand", new)

    def test_a_row_that_is_missing_is_a_key_error(self):
        with self.assertRaises(KeyError):
            delegation.ledger_set_cells(BASE, "nope", VALUES)

    def test_a_pipe_or_newline_in_a_value_cannot_break_the_row(self):
        new = delegation.ledger_set_cells(BASE, "a-2026-10-10", {"Notes": "a|b\nc"})
        columns, rows = delegation.ledger_rows(new)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Notes"], "a\\|b c")

    def test_the_ledger_has_no_other_cell_setter_outside_delegation(self):
        root = Path(delegation.__file__).resolve().parent
        self.assertFalse((root / "dispatch" / "ledger.py").read_text(encoding="utf-8").count("def set_cells"))


if __name__ == "__main__":
    unittest.main()
