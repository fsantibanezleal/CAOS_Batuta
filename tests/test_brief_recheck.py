"""Re-check findings F-8 (all line boundaries), F-14a (unlisted brief files) and `~~~` fences: reproductions as tests."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import TempCase, run, run_json  # noqa: E402

from batuta_lib import delegation  # noqa: E402
from batuta_lib.areas import report as report_area  # noqa: E402

BOUNDARIES = ["\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]


def tilde_fence(text, title, marker="~~~"):
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return text[:m.start(1)] + marker + "\n" + m.group(1).rstrip("\n") + "\n" + marker + "\n\n" + text[m.end(1):]


class Boundaries(TempCase):
    def new(self, **over):
        args = {"--slug": "d", "--topic": "t", "--agent": "implementer", "--title": "T", "--root": self.root, "--date": "2026-10-10"}
        args.update(over)
        flat = [x for kv in args.items() for x in kv]
        return run_json("brief", "new", *flat)

    def test_f8_every_splitlines_boundary_is_refused_in_every_header_field(self):
        for ch in BOUNDARIES:
            for field in ("--title", "--slug", "--sizing", "--report"):
                value = f"a{ch}- kind: docs" if field != "--report" else f"{self.root.as_posix()}/x{ch}y.md"
                code, data, _ = self.new(**{field: value})
                self.assertEqual(code, 1, (repr(ch), field))
                self.assertIn("one line", str(data), (repr(ch), field))
        self.assertFalse(self.ledger.exists())


class Unlisted(TempCase):
    def test_f14a_lint_warns_about_a_brief_file_with_no_ledger_row_and_keeps_it(self):
        brief = self.filled_brief("real")
        ghost = brief.parent / "ghost-2026-10-10.brief.md"
        ghost.write_text("not in the ledger\n", encoding="utf-8")
        code, out, _ = run("brief", "lint", brief, "--root", self.root)
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"WARN.*ghost-2026-10-10\.brief\.md")
        self.assertTrue(ghost.is_file())

    def test_f14a_ledger_status_warns_too_and_never_deletes(self):
        brief = self.filled_brief("real")
        ghost = brief.parent / "ghost-2026-10-10.brief.md"
        ghost.write_text("not in the ledger\n", encoding="utf-8")
        code, out, _ = run("report", "ledger-status", "--write", "--root", self.root)
        self.assertRegex(out, r"WARN.*ghost-2026-10-10\.brief\.md")
        self.assertEqual(code, 2, out)
        self.assertTrue(ghost.is_file())
        self.assertNotIn("ghost", self.ledger.read_text(encoding="utf-8"))

    def test_f14a_listed_briefs_do_not_warn(self):
        brief = self.filled_brief("real")
        self.assertEqual(run("brief", "lint", brief, "--root", self.root)[0], 0)


class TildeFences(TempCase):
    def test_deliverables_inside_a_tilde_fence_are_not_structure_for_lint_and_checker_alike(self):
        for marker in ("~~~", "~~~~", "~~~~~"):
            brief = self.filled_brief(f"tilde{len(marker)}")
            text = tilde_fence(brief.read_text(encoding="utf-8"), "Deliverables", marker)
            brief.write_text(text, encoding="utf-8", newline="\n")
            code, out, _ = run("brief", "lint", brief, "--root", self.root)
            self.assertEqual(code, 1, (marker, out))
            with self.assertRaises(delegation.DelegationError):
                delegation.deliverable_ids(text)
            result = report_area.check_report(text, "# R\n\n## Completeness\n\n| ID | Status | Evidence |\n|---|---|---|\n| D1 | DONE | x |\n")
            self.assertEqual(result.exit_code, 1)

    def test_a_placeholder_inside_a_tilde_fence_is_not_prose_for_the_checker(self):
        brief = self.filled_brief("tilde-ph", "searcher")
        rep = ("# R\n\n## D1 x\nok\n\n~~~\nTODO quoted\n~~~\n\n## Completeness\n\n| ID | Status | Evidence |\n|---|---|---|\n| D1 | DONE | `x` |\n")
        self.assertEqual(report_area.check_report(brief.read_text(encoding="utf-8"), rep).exit_code, 0)

    def test_backtick_fences_still_work_and_a_mixed_fence_does_not_close_early(self):
        text = "## A\n~~~\n```\n## B\n~~~\n## C\nbody\n"
        found = delegation.sections(text)
        self.assertEqual(list(found), ["a", "c"])
        self.assertEqual(delegation.sections("## A\n```\n## B\n```\n## C\n"), {"a": [], "c": []})


if __name__ == "__main__":
    unittest.main()
