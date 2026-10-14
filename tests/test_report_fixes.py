"""Fixes after the adversary check (F-4, F-6, F-7): every reproduction is a test."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import TempCase, report_text, run, write_config  # noqa: E402
from test_report_hook import transcript  # noqa: E402

from batuta_lib.areas import report as report_area  # noqa: E402


class LedgerStatusFix(TempCase):
    def cell(self, ident, column=5):
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"| {ident} "):
                return [c.strip() for c in line.strip("|").split("|")][column]

    def test_f4_an_accepted_row_is_never_downgraded_and_a_missing_brief_is_reported(self):
        brief = self.filled_brief("one", "searcher")
        text = re.sub(r"(one-2026-10-10 \|[^\n]*\| )drafted \| no \|", r"\1accepted | yes |", self.ledger.read_text(encoding="utf-8"))
        self.ledger.write_text(text, encoding="utf-8", newline="\n")
        brief.unlink()
        code, out, _ = run("report", "ledger-status", "--write", "--root", self.root)
        self.assertEqual(self.cell("one-2026-10-10"), "accepted")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), text)
        self.assertRegex(out, r"brief missing")
        self.assertEqual(code, 2, out)

    def test_f4_a_lost_row_whose_brief_went_missing_stays_lost(self):
        brief = self.filled_brief("two", "searcher")
        text = re.sub(r"(two-2026-10-10 \|[^\n]*\| )drafted \| no \|", r"\1lost | no |", self.ledger.read_text(encoding="utf-8"))
        self.ledger.write_text(text, encoding="utf-8", newline="\n")
        brief.unlink()
        run("report", "ledger-status", "--write", "--root", self.root)
        self.assertEqual(self.cell("two-2026-10-10"), "lost")


class HookFix(TempCase):
    def payload(self, last="no lines", **extra):
        t = transcript(self.root / "agent.jsonl", "Do it.\n\n## Deliverables\n- D1: x\n")
        data = {"hook_event_name": "SubagentStop", "agent_type": "implementer", "cwd": str(self.root),
                "last_assistant_message": last, "agent_transcript_path": str(t)}
        data.update(extra)
        return data

    def log_lines(self, root=None):
        path = Path(root or self.root) / ".batuta" / "delegation" / "unverified.log"
        return path.read_text(encoding="utf-8").strip().splitlines() if path.is_file() else []

    def test_f6_without_stop_hook_active_the_second_attempt_of_the_same_agent_is_allowed_and_logged(self):
        first = report_area.handler(self.payload())          # the field is absent: C16 declares it optional
        self.assertEqual(first["output"]["decision"], "block")
        for _ in range(3):
            again = report_area.handler(self.payload())
            self.assertIsNone(again["output"])
        self.assertEqual(len(self.log_lines()), 3)

    def test_f6_another_agent_is_held_once_again(self):
        report_area.handler(self.payload())
        other = self.payload()
        other["agent_transcript_path"] = str(transcript(self.root / "other.jsonl", "Do it.\n\n## Deliverables\n- D1: x\n"))
        self.assertEqual(report_area.handler(other)["output"]["decision"], "block")

    def test_f6_with_the_field_present_it_still_works(self):
        self.assertIsNone(report_area.handler(self.payload(stop_hook_active=True))["output"])
        self.assertEqual(len(self.log_lines()), 1)

    def test_f6_an_agent_without_any_key_cannot_be_counted_but_the_field_still_guards(self):
        data = self.payload()
        data.pop("agent_transcript_path")
        data["last_assistant_message"] = "BRIEF: /nope/b.md\nREPORT: /nope/r.md"
        self.assertEqual(report_area.handler(data)["output"]["decision"], "block")
        self.assertIsNone(report_area.handler({**data, "stop_hook_active": True})["output"])

    def test_f7_the_log_goes_to_the_project_root_found_above_the_cwd(self):
        write_config(self.root, coordination_root="coord")
        deep = self.root / "deep" / "er"
        deep.mkdir(parents=True)
        report_area.handler(self.payload(cwd=str(deep), stop_hook_active=True))
        self.assertTrue((self.root / "coord" / "delegation" / "unverified.log").is_file())
        self.assertFalse((deep / ".batuta").exists())

    def test_f7_the_configuration_resolution_order_applies(self):
        other = self.root / "elsewhere.json"
        doc = write_config(self.root / "cfgs", coordination_root="viaenv")
        other.write_text(json.dumps(doc), encoding="utf-8")
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"BATUTA_CONFIG": str(other), "BATUTA_HOME": str(self.root / "nohome")}):
            report_area.handler(self.payload(stop_hook_active=True))
        self.assertTrue((self.root / "viaenv" / "delegation" / "unverified.log").is_file())

    def test_f7_without_any_configuration_the_cwd_is_the_root(self):
        report_area.handler(self.payload(stop_hook_active=True))
        self.assertEqual(len(self.log_lines()), 1)


if __name__ == "__main__":
    unittest.main()
