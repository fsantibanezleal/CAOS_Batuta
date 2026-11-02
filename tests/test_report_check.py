"""report check: the CAOS checker plus C03 (unit U2, D3)."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import CONTRACTS, TempCase, report_text, run, run_json  # noqa: E402

from batuta_lib import contract  # noqa: E402
from batuta_lib.areas import report as report_area  # noqa: E402

FIX = CONTRACTS / "fixtures" / "C03"


class ReportCheck(TempCase):
    def brief(self, topic="alpha", agent="searcher", deliverables=2):
        brief = self.filled_brief(topic, agent)
        text = brief.read_text(encoding="utf-8")
        extra = "".join(f"- D{n}: another outcome\n" for n in range(2, deliverables + 1))
        brief.write_text(text.replace("## Checks", extra + "\n## Checks"), encoding="utf-8", newline="\n")
        return brief

    def check(self, brief, report, *extra):
        return run("report", "check", "--brief", brief, report, "--root", self.root, *extra)

    def write(self, text, name="rep.md", crlf=False):
        path = self.root / name
        path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
        return path

    def test_complete_is_exit_0(self):
        brief = self.brief()
        rep = self.write(report_text([("D1", "DONE", "`a.py:1`"), ("D2", "DONE", "`b.py:2`")]))
        code, out, _ = self.check(brief, rep)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"2/2 deliverables DONE")

    def test_partial_and_blocked_rows_are_exit_2(self):
        brief = self.brief()
        rep = self.write(report_text([("D1", "PARTIAL", "page unreachable"), ("D2", "BLOCKED", "needs a decision")]))
        code, out, _ = self.check(brief, rep)
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"WARN.*D1.*PARTIAL")

    def test_a_missing_deliverable_row_is_exit_1(self):
        brief = self.brief()
        rep = self.write(report_text([("D1", "DONE", "`a.py:1`")]))
        code, out, _ = self.check(brief, rep)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"D2.*no row")

    def test_a_placeholder_in_prose_is_exit_1_but_not_inside_code(self):
        brief = self.brief()
        rep = self.write(report_text([("D1", "DONE", "`a`"), ("D2", "DONE", "`b`")], "\nTODO: write this\n"))
        code, out, _ = self.check(brief, rep)
        self.assertEqual(code, 1)
        self.assertIn("TODO", out)
        rep = self.write(report_text([("D1", "DONE", "`a`"), ("D2", "DONE", "`b`")], "\nThe code `TODO` stays.\n\n```\nTBD\n```\n"))
        self.assertEqual(self.check(brief, rep)[0], 0)

    def test_every_placeholder_kind_is_refused(self):
        brief = self.brief()
        for bad in ("TBD", "FIXME", "lorem ipsum", "<what was done>", "<fill in>"):
            rep = self.write(report_text([("D1", "DONE", "`a`"), ("D2", "DONE", "`b`")], f"\nNote: {bad}\n"))
            self.assertEqual(self.check(brief, rep)[0], 1, bad)

    def test_a_status_outside_the_enum_and_a_missing_evidence_are_exit_1(self):
        brief = self.brief()
        rep = self.write(report_text([("D1", "FINISHED", "x"), ("D2", "DONE", "-")]))
        code, out, _ = self.check(brief, rep)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"D1.*FINISHED")
        self.assertRegex(out, r"D2.*without evidence")

    def test_an_extra_deliverable_row_is_flagged_not_a_crash(self):
        brief = self.brief()
        rep = self.write(report_text([("D1", "DONE", "`a`"), ("D2", "DONE", "`b`"), ("D9", "DONE", "`c`")]))
        code, out, _ = self.check(brief, rep)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"D9.*not a deliverable")

    def test_research_needs_sources_with_a_url_and_docs_needs_sources(self):
        brief = self.filled_brief("res", "general-purpose", "--model", "sonnet")
        rows = [("D1", "DONE", "`a`")]
        self.assertEqual(self.check(brief, self.write(report_text(rows)))[0], 1)
        ok = self.write(report_text(rows, "\n## Sources\n- https://example.org/spec\n"))
        self.assertEqual(self.check(brief, ok)[0], 0)
        docs = self.filled_brief("doc", "doc-writer")
        self.assertEqual(self.check(docs, self.write(report_text(rows), "d.md"))[0], 1)
        self.assertEqual(self.check(docs, self.write(report_text(rows, "\n## Sources\n- docs/spec.md\n"), "d2.md"))[0], 0)

    def test_implement_needs_red_before_green_and_the_production_path(self):
        brief = self.filled_brief("impl", "implementer")
        rows = [("D1", "DONE", "`a`")]
        code, out, _ = self.check(brief, self.write(report_text(rows)))
        self.assertEqual(code, 1)
        self.assertIn("Red run", out)
        self.assertIn("Production path", out)
        full = ("\n## Red run\n`python -m unittest` exit code 1\n\n## Green run\n`python -m unittest` exit code 0\n"
                "\n## Production path\n`python run.py --real` printed ok\n")
        self.assertEqual(self.check(brief, self.write(report_text(rows, full), "ok.md"))[0], 0)
        swapped = ("\n## Green run\n`x` exit code 0\n\n## Red run\n`x` exit code 1\n\n## Production path\n`x` ok\n")
        code, out, _ = self.check(brief, self.write(report_text(rows, swapped), "sw.md"))
        self.assertEqual(code, 1)
        self.assertIn("red first", out)

    def test_a_red_run_that_exits_zero_is_refused(self):
        brief = self.filled_brief("impl", "implementer")
        full = ("\n## Red run\n`x` exit code 0\n\n## Green run\n`x` exit code 0\n\n## Production path\n`x` ok\n")
        code, out, _ = self.check(brief, self.write(report_text([("D1", "DONE", "`a`")], full)))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"Red run")

    def test_crlf_brief_and_report(self):
        brief = self.brief()
        brief.write_bytes(brief.read_bytes().replace(b"\n", b"\r\n"))
        rep = self.write(report_text([("D1", "DONE", "`a`"), ("D2", "DONE", "`b`")]), crlf=True)
        code, out, _ = self.check(brief, rep)
        self.assertEqual(code, 0, out)

    def test_the_report_defaults_to_the_briefs_report_line(self):
        brief = self.brief()
        path = Path(re.search(r"^- report: (.+)$", brief.read_text(encoding="utf-8"), re.M).group(1))
        path.write_text(report_text([("D1", "DONE", "`a`"), ("D2", "DONE", "`b`")]), encoding="utf-8")
        code, out, _ = run("report", "check", "--brief", brief, "--root", self.root)
        self.assertEqual(code, 0, out)

    def test_a_missing_report_is_exit_1_and_says_so(self):
        brief = self.brief()
        code, out, _ = self.check(brief, self.root / "nope.md")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"not found")

    def test_an_empty_report_and_a_report_without_completeness(self):
        brief = self.brief()
        self.assertEqual(self.check(brief, self.write(""))[0], 1)
        code, out, _ = self.check(brief, self.write("# Report\n\nNothing here.\n", "n.md"))
        self.assertEqual(code, 1)
        self.assertIn("Completeness", out)

    def test_unicode_in_the_report(self):
        brief = self.brief()
        rep = self.write(report_text([("D1", "DONE", "`a` éñ中"), ("D2", "DONE", "`b`")]))
        self.assertEqual(self.check(brief, rep)[0], 0)

    def test_json_output_is_the_c20_object(self):
        brief = self.brief()
        rep = self.write(report_text([("D1", "DONE", "`a`"), ("D2", "PARTIAL", "half")]))
        code, data, _ = run_json("report", "check", "--brief", brief, rep, "--root", self.root)
        self.assertEqual((code, data["exit_code"], data["area"], data["verb"]), (2, 2, "report", "check"))
        self.assertTrue(any(i["tag"] == "WARN" for i in data["items"]))

    def test_every_invalid_c03_fixture_is_rejected_with_its_reason(self):
        brief = self.brief(deliverables=4)
        for fx in sorted(FIX.glob("invalid-*.md")):
            _why, expect = contract.fixture_meta(fx)
            code, out, _ = self.check(brief, fx)
            self.assertEqual(code, 1, fx.name)
            if expect:
                self.assertIn(expect, out, f"{fx.name}: expected {expect!r}")

    def test_every_valid_c03_fixture_satisfies_the_contract(self):
        for fx in sorted(FIX.glob("valid-*.md")):
            self.assertEqual(report_area.c03_problems(fx.read_text(encoding="utf-8")), [], fx.name)

    def test_the_c03_check_is_applied_on_top_of_the_native_one(self):
        # a deliverable section without a table row is a C03 rule (ids_match), not a native one
        brief = self.brief(deliverables=1)
        rep = self.write(report_text([("D1", "DONE", "`a`")]).replace("## Completeness", "## D7 stray\nx\n\n## Completeness"))
        code, out, _ = self.check(brief, rep)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"(?i)d7")


if __name__ == "__main__":
    unittest.main()
