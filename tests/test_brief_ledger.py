"""The ledger (C04): reading, byte-stable edits, atomic writes under concurrency, the CAOS differential (unit U2, D2)."""
from __future__ import annotations

import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import CONTRACTS, FIXTURES  # noqa: E402

from batuta_lib import contract, delegation  # noqa: E402

C04_FIX = CONTRACTS / "fixtures" / "C04"


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def c04_problems(text):
    return contract.validate_markdown(text, contract.load_schema(contract.find_schema(CONTRACTS, "C04")),
                                      contract.load_sections_spec(contract.find_schema(CONTRACTS, "C04")))


class LedgerText(unittest.TestCase):
    def test_a_ledger_written_by_the_caos_tool_is_read_and_round_trips_unchanged(self):
        for name in ("ledger-caos-new.md", "ledger-caos-pending.md", "ledger-caos-accepted.md"):
            text = read(name)
            columns, rows = delegation.ledger_rows(text)
            self.assertEqual(columns[:7], list(delegation.LEDGER_COLUMNS), name)
            self.assertEqual(len(rows), 3, name)
            self.assertEqual(delegation.ledger_render(text), text, name)  # parse then write: identical bytes
            self.assertEqual(c04_problems(text), [], name)

    def test_the_caos_fixtures_have_no_machine_paths(self):
        # private names are the leaks scan's job (its deny-list lives outside the repository); this test names none
        for name in ("ledger-caos-new.md", "ledger-caos-pending.md", "ledger-caos-accepted.md"):
            self.assertNotRegex(read(name), r"(?i)(?<![a-z])[a-z]:[\\/]|[\\/](users|home)[\\/]")

    def test_rows_expose_the_columns_and_alias_values_are_not_rewritten(self):
        _cols, rows = delegation.ledger_rows(read("ledger-caos-accepted.md"))
        self.assertEqual([r["Accepted"] for r in rows], ["y", "N", "no"])
        self.assertEqual(delegation.accepted_value("y"), "yes")
        self.assertEqual(delegation.accepted_value("N"), "no")

    def test_set_status_changes_only_that_cell(self):
        text = read("ledger-caos-new.md")
        out = delegation.ledger_set_status(text, "beta-2026-10-10", "complete")
        a, b = text.splitlines(), out.splitlines()
        changed = [i for i in range(len(a)) if a[i] != b[i]]
        self.assertEqual(len(changed), 1)
        self.assertEqual(b[changed[0]], a[changed[0]].replace("| drafted |", "| complete |"))
        self.assertEqual(delegation.ledger_set_status(out, "beta-2026-10-10", "complete"), out)  # idempotent

    def test_set_status_keeps_optional_columns_notes_and_the_alias(self):
        text = (C04_FIX / "valid-notes-column-before-the-dispatch-columns.md").read_text(encoding="utf-8")
        out = delegation.ledger_set_status(text, "run-2026-10-12", "accepted")
        self.assertIn("| accepted | y | check_report COMPLETE and diff re-read | anthropic | 1200 | 300 | 0.42 |", out)

    def test_set_status_unknown_id_is_an_error(self):
        with self.assertRaises(KeyError):
            delegation.ledger_set_status(read("ledger-caos-new.md"), "nope", "complete")

    def test_add_row_goes_after_the_last_row_and_fills_every_column(self):
        text = (C04_FIX / "valid-dispatch-columns-billed-and-subagent.md").read_text(encoding="utf-8")
        text = re.sub(r"^(<!--.*-->\n)+", "", text)
        out = delegation.ledger_add_row(text, {"ID": "z-2026-10-12", "Agent": "searcher", "Model": "haiku",
                                               "Brief": "b.md", "Report": "r.md", "Status": "drafted", "Accepted": "no"})
        last = out.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.startswith("| z-2026-10-12 | searcher | haiku | b.md | r.md | drafted | no |"))
        self.assertEqual(len(last.strip("|").split("|")), 11)
        self.assertEqual(c04_problems(out), [])

    def test_add_row_keeps_text_after_the_table(self):
        text = read("ledger-caos-new.md") + "\nNotes for humans.\n"
        out = delegation.ledger_add_row(text, {"ID": "z-2026-10-12", "Agent": "searcher", "Model": "haiku", "Brief": "b.md",
                                               "Report": "r.md", "Status": "drafted", "Accepted": "no"})
        self.assertTrue(out.endswith("\nNotes for humans.\n"))
        self.assertLess(out.index("z-2026-10-12"), out.index("Notes for humans."))

    def test_an_empty_text_gets_the_header(self):
        out = delegation.ledger_add_row("", {"ID": "z-2026-10-12", "Agent": "searcher", "Model": "haiku", "Brief": "b.md",
                                            "Report": "r.md", "Status": "drafted", "Accepted": "no"}, title="demo")
        self.assertTrue(out.startswith("# Delegation ledger: demo\n\n| ID |"))
        self.assertEqual(c04_problems(out), [])

    def test_crlf_text_keeps_crlf(self):
        text = read("ledger-caos-new.md").replace("\n", "\r\n")
        out = delegation.ledger_add_row(text, {"ID": "z-2026-10-12", "Agent": "searcher", "Model": "haiku", "Brief": "b.md",
                                               "Report": "r.md", "Status": "drafted", "Accepted": "no"})
        self.assertEqual(out.count("\n"), out.count("\r\n"))
        out2 = delegation.ledger_set_status(out, "beta-2026-10-10", "complete")
        self.assertEqual(out2.count("\n"), out2.count("\r\n"))

    def test_every_invalid_c04_fixture_is_rejected_with_its_reason(self):
        for fx in sorted(C04_FIX.glob("invalid-*.md")):
            _why, expect = contract.fixture_meta(fx)
            problems = delegation.ledger_problems(fx.read_text(encoding="utf-8"))
            self.assertTrue(problems, fx.name)
            if expect:
                self.assertTrue(any(expect in p for p in problems), f"{fx.name}: {expect!r} not in {problems}")

    def test_every_valid_c04_fixture_is_accepted_and_round_trips(self):
        for fx in sorted(C04_FIX.glob("valid-*.md")):
            text = fx.read_text(encoding="utf-8")
            self.assertEqual(delegation.ledger_problems(text), [], fx.name)
            self.assertEqual(delegation.ledger_render(text), text, fx.name)


class LedgerFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "delegation" / "ledger.md"

    def row(self, n):
        return {"ID": f"r{n:03d}-2026-10-12", "Agent": "searcher", "Model": "haiku", "Brief": f"b{n}.md",
                "Report": f"r{n}.md", "Status": "drafted", "Accepted": "no"}

    def test_the_write_is_atomic_no_temp_file_is_left_and_the_text_is_lf(self):
        delegation.update_ledger(self.path, lambda t: delegation.ledger_add_row(t, self.row(1), title="demo"))
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["ledger.md"])
        self.assertNotIn(b"\r", self.path.read_bytes())

    def test_a_row_added_by_another_writer_between_read_and_replace_is_kept(self):
        delegation.update_ledger(self.path, lambda t: delegation.ledger_add_row(t, self.row(1), title="demo"))
        fired = []

        def concurrent_writer():
            if not fired:
                fired.append(1)
                self.path.write_text(delegation.ledger_add_row(self.path.read_text(encoding="utf-8"), self.row(2)),
                                     encoding="utf-8", newline="\n")

        delegation.update_ledger(self.path, lambda t: delegation.ledger_add_row(t, self.row(3)), before_replace=concurrent_writer)
        ids = [r["ID"] for r in delegation.ledger_rows(self.path.read_text(encoding="utf-8"))[1]]
        self.assertEqual(ids, ["r001-2026-10-12", "r002-2026-10-12", "r003-2026-10-12"])

    def test_concurrent_writers_lose_no_row(self):
        delegation.update_ledger(self.path, lambda t: delegation.ledger_add_row(t, self.row(0), title="demo"))
        errors = []

        def worker(start):
            try:
                for n in range(start, start + 8):
                    delegation.update_ledger(self.path, lambda t, n=n: delegation.ledger_add_row(t, self.row(n)))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(100 * k + 1,)) for k in range(1, 5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(errors, [])
        text = self.path.read_text(encoding="utf-8")
        ids = [r["ID"] for r in delegation.ledger_rows(text)[1]]
        self.assertEqual(len(ids), 33)
        self.assertEqual(len(set(ids)), 33)
        self.assertEqual(c04_problems(text), [])
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["ledger.md"])

    def test_a_mutation_that_makes_the_ledger_invalid_is_refused_and_the_file_is_untouched(self):
        delegation.update_ledger(self.path, lambda t: delegation.ledger_add_row(t, self.row(1), title="demo"))
        before = self.path.read_bytes()
        with self.assertRaises(delegation.LedgerError) as caught:
            delegation.update_ledger(self.path, lambda t: delegation.ledger_add_row(t, self.row(1)))
        self.assertIn("duplicate", str(caught.exception))
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
