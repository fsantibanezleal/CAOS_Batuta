"""Re-check findings F-11, F-12, F-13 and F-14b: reproductions as tests."""
from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import TempCase, report_text  # noqa: E402
from test_report_hook import transcript  # noqa: E402

from batuta_lib import config, delegation  # noqa: E402
from batuta_lib.areas import report as report_area  # noqa: E402


class Setup(TempCase):
    def state_lines(self):
        path = self.root / ".batuta" / "delegation" / report_area.STATE_NAME
        return path.read_text(encoding="utf-8").split("\n")[:-1] if path.is_file() else []

    def log_lines(self, root=None):
        path = Path(root or self.root) / ".batuta" / "delegation" / "unverified.log"
        return path.read_text(encoding="utf-8").strip().splitlines() if path.is_file() else []

    def defective(self, status="FINISHED"):
        brief = self.filled_brief("alpha", "searcher") if not list(self.root.glob(".batuta/delegation/alpha*.brief.md")) \
            else next(self.root.glob(".batuta/delegation/alpha*.brief.md"))
        rep = Path(re.search(r"^- report: (.+)$", brief.read_text(encoding="utf-8"), re.M).group(1))
        rep.write_text(report_text([("D1", status, "x")]), encoding="utf-8")
        return brief, rep

    def payload(self, brief, rep, **extra):
        data = {"hook_event_name": "SubagentStop", "agent_type": "searcher", "cwd": str(self.root),
                "last_assistant_message": f"BRIEF: {brief.as_posix()}\nREPORT: {rep.as_posix()}"}
        data.update(extra)
        return data


class State(Setup):
    def cfg(self):
        return config.default_config({"BATUTA_HOME": str(self.root / "home")})

    def test_f11_a_long_key_is_stored_as_its_sha256(self):
        key = "k" * 600
        report_area._remember(self.root, self.cfg(), key)
        lines = self.state_lines()
        self.assertEqual(lines, [hashlib.sha256(key.encode("utf-8")).hexdigest()])
        self.assertTrue(report_area._held_before(self.root, self.cfg(), key))
        short = "s" * 512
        report_area._remember(self.root, self.cfg(), short)
        self.assertIn(short, self.state_lines())
        self.assertTrue(all(len(x) <= 512 for x in self.state_lines()))

    def test_f11_at_most_1000_entries_the_oldest_dropped_first_and_no_temp_file_left(self):
        for n in range(1005):
            report_area._remember(self.root, self.cfg(), f"key-{n}")
        lines = self.state_lines()
        self.assertEqual(len(lines), 1000)
        self.assertEqual(lines[0], "key-5")
        self.assertEqual(lines[-1], "key-1004")
        self.assertFalse(report_area._held_before(self.root, self.cfg(), "key-0"))
        self.assertTrue(report_area._held_before(self.root, self.cfg(), "key-1004"))
        self.assertEqual(sorted(p.name for p in (self.root / ".batuta" / "delegation").iterdir()
                                if p.name.startswith(".") or p.name.endswith((".tmp", ".lock"))), [])


class OncePerReport(Setup):
    def test_f12_the_same_defective_report_is_never_blocked_twice_a_new_one_is_blocked_once_more(self):
        brief, rep = self.defective("FINISHED")
        data = self.payload(brief, rep, agent_id="agent-1")
        self.assertEqual(report_area.handler(data)["output"]["decision"], "block")
        self.assertIsNone(report_area.handler(data)["output"])
        self.assertIsNone(report_area.handler(data)["output"])
        rep.write_text(report_text([("D1", "DONE-ISH", "y")]), encoding="utf-8")   # a resumed agent writes another defective report
        self.assertEqual(report_area.handler(data)["output"]["decision"], "block")
        self.assertIsNone(report_area.handler(data)["output"])
        self.assertEqual(len(self.log_lines()), 3)

    def test_f12_a_different_agent_with_the_same_report_is_held_once(self):
        brief, rep = self.defective()
        report_area.handler(self.payload(brief, rep, agent_id="a"))
        self.assertEqual(report_area.handler(self.payload(brief, rep, agent_id="b"))["output"]["decision"], "block")

    def test_f13_keys_with_line_boundaries_still_match(self):
        brief, rep = self.defective()
        for n, ch in enumerate(["\r", " ", "\x85", "\x0b", "\x1c", " "]):
            data = self.payload(brief, rep, agent_id=f"id{n}{ch}tail")
            self.assertEqual(report_area.handler(data)["output"]["decision"], "block", repr(ch))
            self.assertIsNone(report_area.handler(data)["output"], repr(ch))
        self.assertTrue(all(len(x.splitlines()) <= 1 for x in self.state_lines()))


class ProjectRoot(Setup):
    def run_from(self, sub):
        data = {"hook_event_name": "SubagentStop", "agent_type": "x", "cwd": str(sub), "stop_hook_active": True,
                "last_assistant_message": "no lines",
                "agent_transcript_path": str(transcript(self.root / "agent.jsonl", "Do it.\n\n## Deliverables\n- D1: x\n"))}
        report_area.handler(data)

    def test_f14b_a_git_folder_marks_the_project_root(self):
        (self.root / ".git").mkdir()
        sub = self.root / "a" / "b"
        sub.mkdir(parents=True)
        self.run_from(sub)
        self.assertEqual(len(self.log_lines()), 1)
        self.assertFalse((sub / ".batuta").exists())

    def test_f14b_a_batuta_folder_without_a_configuration_marks_it_too(self):
        (self.root / ".batuta").mkdir()
        sub = self.root / "a"
        sub.mkdir()
        self.run_from(sub)
        self.assertEqual(len(self.log_lines()), 1)
        self.assertFalse((sub / ".batuta").exists())

    def test_f14b_the_nearest_marker_wins_and_no_marker_falls_back_to_the_cwd(self):
        sub = self.root / "plain"
        sub.mkdir()
        self.assertEqual(delegation.find_project_root(sub), sub.resolve())
        (self.root / ".git").mkdir()
        inner = self.root / "inner"
        (inner / ".git").mkdir(parents=True)
        self.assertEqual(delegation.find_project_root(inner / "x" if (inner / "x").mkdir() is None else inner), inner.resolve())


if __name__ == "__main__":
    unittest.main()
