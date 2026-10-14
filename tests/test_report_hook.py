"""The SubagentStop decision: holds a briefed agent once until its report passes, never loops (unit U2, D3)."""
from __future__ import annotations

import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import CONTRACTS, PLUGIN, TempCase, report_text, run, write_config  # noqa: E402

from batuta_lib import contract  # noqa: E402
from batuta_lib.areas import report as report_area  # noqa: E402

C16_FIX = CONTRACTS / "fixtures" / "C16"
C31 = contract.load_schema(contract.find_schema(CONTRACTS, "C31"))
C16 = contract.load_schema(contract.find_schema(CONTRACTS, "C16"))


def transcript(path, first_prompt):
    rec = {"type": "user", "message": {"role": "user", "content": first_prompt}}
    path.write_text(json.dumps(rec) + "\n" + json.dumps({"type": "assistant", "message": {"content": "ok"}}) + "\n",
                    encoding="utf-8")
    return path


class Hook(TempCase):
    def payload(self, last="done", active=False, prompt="Please implement the thing.\n\n## Deliverables\n- D1: x\n", **extra):
        tpath = transcript(self.root / "agent.jsonl", prompt) if prompt is not None else None
        data = {"session_id": "s", "cwd": str(self.root), "hook_event_name": "SubagentStop", "agent_type": "implementer",
                "last_assistant_message": last, "stop_hook_active": active}
        if tpath:
            data["agent_transcript_path"] = str(tpath)
        data.update(extra)
        return data

    def handle(self, payload):
        result = report_area.HOOKS["subagent-stop"](payload)
        self.assertEqual(contract.validate_instance("C31", result, C31), [], result)
        if result["output"] is not None:
            self.assertEqual(contract.validate_instance("C16", result["output"], C16), [], result)
        return result

    def blocked(self, result):
        self.assertEqual(result["exit_code"], 0)  # the Stop-type form: decision block with exit code 0
        self.assertEqual(result["output"]["decision"], "block")
        return result["output"]["reason"]

    def allowed(self, result):
        self.assertEqual((result["exit_code"], result["output"]), (0, None))

    def ready(self, rows, agent="searcher", report=None):
        brief = self.filled_brief("alpha", agent)
        rep = Path(re.search(r"^- report: (.+)$", brief.read_text(encoding="utf-8"), re.M).group(1))
        if rows is not None:
            rep.write_text(report if report is not None else report_text(rows), encoding="utf-8")
        return brief, rep

    def last(self, brief, rep):
        return f"All done.\n\nBRIEF: {brief.as_posix()}\nREPORT: {rep.as_posix()}"

    # ---- registration
    def test_the_handler_is_registered_under_one_literal_id(self):
        self.assertEqual(list(report_area.HOOKS), ["subagent-stop"])
        ids, problems = contract.discover_hook_ids(PLUGIN / "scripts" / "batuta_lib" / "areas")
        self.assertEqual(ids.get("subagent-stop"), ["report"])
        self.assertEqual(problems, [])

    def test_the_shipped_c16_subagent_stop_fixture_is_a_valid_input(self):
        payload = json.loads((C16_FIX / "valid-input-subagentstop.json").read_text(encoding="utf-8"))
        payload = {k: v for k, v in payload.items() if not k.startswith("_")}
        self.assertEqual(contract.validate_instance("C16", payload, C16), [])
        self.allowed(self.handle(payload))  # not briefed, transcript missing: allow

    # ---- allow paths
    def test_never_blocks_when_the_stop_hook_is_already_active(self):
        self.allowed(self.handle(self.payload(active=True)))

    def test_not_briefed_and_no_brief_line_is_allowed(self):
        self.allowed(self.handle(self.payload(prompt="what is 2+2?")))

    def test_no_transcript_field_is_allowed_quietly(self):
        result = self.handle(self.payload(prompt=None))
        self.allowed(result)
        self.assertNotIn("message", result)

    def test_an_unreadable_transcript_is_allowed_and_says_why(self):
        result = self.handle(self.payload(prompt=None, agent_transcript_path=str(self.root / "missing.jsonl")))
        self.allowed(result)
        self.assertRegex(result.get("message", ""), r"transcript")

    def test_brief_none_is_allowed(self):
        self.allowed(self.handle(self.payload(last="BRIEF: none", prompt="x")))

    def test_a_complete_report_is_allowed(self):
        brief, rep = self.ready([("D1", "DONE", "`a`")])
        self.allowed(self.handle(self.payload(last=self.last(brief, rep))))

    def test_missing_optional_fields_do_not_crash(self):
        self.allowed(self.handle({"hook_event_name": "SubagentStop", "agent_type": "x", "last_assistant_message": "hi"}))
        self.allowed(self.handle({"hook_event_name": "SubagentStop"}))

    # ---- block once
    def test_briefed_without_brief_and_report_lines_is_blocked(self):
        reason = self.blocked(self.handle(self.payload(last="finished, trust me")))
        self.assertIn("BRIEF:", reason)
        self.assertIn("REPORT:", reason)

    def test_a_brief_line_without_a_report_line_is_blocked(self):
        brief, _rep = self.ready(None)
        reason = self.blocked(self.handle(self.payload(last=f"BRIEF: {brief.as_posix()}")))
        self.assertIn("REPORT:", reason)

    def test_a_missing_report_blocks_with_the_instruction_to_write_it(self):
        brief, rep = self.ready(None)
        reason = self.blocked(self.handle(self.payload(last=self.last(brief, rep))))
        self.assertIn(rep.as_posix(), reason)
        self.assertRegex(reason, r"Write it")

    def test_an_unreadable_brief_blocks(self):
        reason = self.blocked(self.handle(self.payload(last="BRIEF: /nope/x.brief.md\nREPORT: /nope/x.md")))
        self.assertIn("/nope/x.brief.md", reason)

    def test_a_defective_report_blocks_with_the_exact_problems(self):
        brief, rep = self.ready([("D1", "FINISHED", "x")])
        reason = self.blocked(self.handle(self.payload(last=self.last(brief, rep))))
        self.assertIn("D1", reason)
        self.assertIn("FINISHED", reason)

    def test_open_rows_block_with_the_rows(self):
        brief, rep = self.ready([("D1", "PARTIAL", "half done")])
        reason = self.blocked(self.handle(self.payload(last=self.last(brief, rep))))
        self.assertIn("D1", reason)
        self.assertIn("half done", reason)

    def test_a_report_with_a_placeholder_blocks(self):
        brief, rep = self.ready([("D1", "DONE", "`a`")], report=report_text([("D1", "DONE", "`a`")], "\nTODO later\n"))
        self.assertIn("TODO", self.blocked(self.handle(self.payload(last=self.last(brief, rep)))))

    # ---- second attempt: allow and log
    def test_the_second_attempt_allows_and_logs_unverified(self):
        brief, rep = self.ready([("D1", "PARTIAL", "half done")])
        result = self.handle(self.payload(last=self.last(brief, rep), active=True))
        self.allowed(result)
        log = (self.root / ".batuta" / "delegation" / "unverified.log").read_text(encoding="utf-8")
        self.assertRegex(log, rf"^{date.today().isoformat()} UNVERIFIED ")
        self.assertIn("implementer", log)
        self.assertIn("D1", log)
        self.assertEqual(len(log.strip().splitlines()), 1)
        self.handle(self.payload(last=self.last(brief, rep), active=True))
        self.assertEqual(len((self.root / ".batuta" / "delegation" / "unverified.log").read_text(encoding="utf-8").strip().splitlines()), 2)

    def test_the_second_attempt_without_lines_and_with_a_missing_report_is_logged_too(self):
        self.allowed(self.handle(self.payload(last="no lines", active=True)))
        brief, rep = self.ready(None)
        self.allowed(self.handle(self.payload(last=self.last(brief, rep), active=True)))
        log = (self.root / ".batuta" / "delegation" / "unverified.log").read_text(encoding="utf-8")
        self.assertEqual(len(log.strip().splitlines()), 2)

    def test_the_second_attempt_of_a_complete_or_unbriefed_agent_logs_nothing(self):
        brief, rep = self.ready([("D1", "DONE", "`a`")])
        self.allowed(self.handle(self.payload(last=self.last(brief, rep), active=True)))
        self.allowed(self.handle(self.payload(prompt="what is 2+2?", active=True)))
        self.assertFalse((self.root / ".batuta" / "delegation" / "unverified.log").exists())

    def test_the_log_goes_to_the_configured_coordination_root(self):
        write_config(self.root, coordination_root="coord")
        self.allowed(self.handle(self.payload(last="no lines", active=True)))
        self.assertTrue((self.root / "coord" / "delegation" / "unverified.log").is_file())

    # ---- fail open
    def test_an_internal_error_allows_and_says_why(self):
        (self.root / ".batuta").mkdir(exist_ok=True)
        (self.root / ".batuta" / "batuta.json").write_text("{broken", encoding="utf-8")
        result = self.handle(self.payload(last="no lines"))
        self.allowed(result)
        self.assertRegex(result["message"], r"configuration|allowed")

    def test_a_payload_that_is_not_an_object_allows(self):
        result = report_area.HOOKS["subagent-stop"](["not", "an", "object"])
        self.assertEqual((result["exit_code"], result["output"]), (0, None))
        self.assertIn("message", result)

    # ---- paths
    def test_windows_and_posix_paths_in_the_lines(self):
        brief, rep = self.ready([("D1", "DONE", "`a`")])
        win = f"BRIEF: {str(brief)}\nREPORT: {str(rep)}"       # native separators
        self.allowed(self.handle(self.payload(last=win)))
        quoted = f"**BRIEF:** `{brief.as_posix()}`\n**REPORT:** `{rep.as_posix()}`"
        self.allowed(self.handle(self.payload(last=quoted)))
        crlf = f"BRIEF: {brief.as_posix()}\r\nREPORT: {rep.as_posix()}\r\n"
        self.allowed(self.handle(self.payload(last=crlf)))

    def test_a_relative_path_is_resolved_against_the_payload_cwd(self):
        brief, rep = self.ready([("D1", "DONE", "`a`")])
        rel = lambda p: p.relative_to(self.root).as_posix()  # noqa: E731
        self.allowed(self.handle(self.payload(last=f"BRIEF: {rel(brief)}\nREPORT: {rel(rep)}")))

    def test_the_agent_last_message_names_the_brief_even_when_the_transcript_is_not_a_brief(self):
        brief, rep = self.ready([("D1", "PARTIAL", "x")])
        # briefed by the last message alone (no readable prompt): the lines are checked
        reason = self.blocked(self.handle(self.payload(last=self.last(brief, rep), prompt="hello")))
        self.assertIn("D1", reason)

    # ---- the CLI twin
    def test_cli_twin_prints_the_output_and_returns_zero(self):
        brief, rep = self.ready([("D1", "PARTIAL", "half done")])
        code, out, err = run("report", "hook-subagent-stop", stdin=json.dumps(self.payload(last=self.last(brief, rep))))
        self.assertEqual(code, 0, err)
        decision = json.loads(out)
        self.assertEqual(decision["decision"], "block")
        self.assertIn("half done", decision["reason"])

    def test_cli_twin_prints_nothing_on_allow_and_the_message_on_stderr(self):
        code, out, err = run("report", "hook-subagent-stop", stdin=json.dumps(self.payload(prompt="hello?")))
        self.assertEqual((code, out.strip()), (0, ""))
        code, out, err = run("report", "hook-subagent-stop",
                             stdin=json.dumps(self.payload(prompt=None, agent_transcript_path=str(self.root / "gone.jsonl"))))
        self.assertEqual((code, out.strip()), (0, ""))
        self.assertIn("transcript", err)

    def test_cli_twin_on_garbage_stdin_allows_with_a_stderr_line(self):
        code, out, err = run("report", "hook-subagent-stop", stdin="{not json")
        self.assertEqual((code, out.strip()), (0, ""))
        self.assertTrue(err.strip())

    def test_cli_twin_on_every_c16_subagent_stop_fixture(self):
        for fx in sorted(C16_FIX.glob("*subagentstop*.json")):
            payload = json.loads(fx.read_text(encoding="utf-8"))
            payload = {k: v for k, v in payload.items() if not k.startswith("_")}
            code, out, err = run("report", "hook-subagent-stop", stdin=json.dumps(payload))
            self.assertEqual(code, 0, (fx.name, err))


if __name__ == "__main__":
    unittest.main()
