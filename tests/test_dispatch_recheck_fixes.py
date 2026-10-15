"""Findings N1 to N6 of the focused code re-check of U13 at 925fc10: one reproduction per finding, written before the fixes."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dispatch_support import (ENV, DispatchCase, FakeResponse, FakeTransport, good_report, make_fake_sdk, openai_reply,  # noqa: E402
                               partial_report)
from test_brief_support import run  # noqa: E402

from batuta_lib import delegation  # noqa: E402
from batuta_lib.areas import dispatch as area  # noqa: E402
from batuta_lib.areas import guard as guard_area  # noqa: E402
from batuta_lib.dispatch import lanes, prices, transport  # noqa: E402

PER_ATTEMPT = 0.001575 + 0.16        # gpt-5: the estimated input of the brief plus 16000 output tokens at 10 USD per million


class Base(DispatchCase):
    def setUp(self):
        super().setUp()
        self.config()
        for p in (mock.patch("time.sleep"), mock.patch.object(area, "_run_command", return_value=(0, "ok"))):
            p.start()
            self.addCleanup(p.stop)

    def ids(self, brief):
        return delegation.deliverable_ids(brief.read_text(encoding="utf-8"))

    def go(self, request, *extra, tr=None, sdk=None):
        patches = []
        if tr is not None:
            patches.append(mock.patch.object(area, "_transport", return_value=tr))
        if sdk is not None:
            patches.append(mock.patch.object(area, "_load_sdk", return_value=sdk))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return run("dispatch", "run", "--request", request, "--root", self.root, *extra, env=ENV)

    def lookup(self, **over):
        brief = self.brief("look", "searcher")
        return brief, self.request_file(brief, "provider:openai", **over)


class N1ChargeEveryAttemptThatMayHaveBilled(Base):
    def test_five_read_timeouts_are_charged_five_attempts_not_one(self):
        brief, req = self.lookup(max_cost_usd=1.0)
        t = FakeTransport([transport.TransportError("read timed out")] * 10)
        self.go(req, "--apply", tr=t)
        result = self.result_of(req)
        self.assertEqual(len(t.requests), 5)
        self.assertAlmostEqual(result["cost_usd"], 5 * PER_ATTEMPT, delta=0.01)
        self.assertLessEqual(result["cost_usd"], 1.0)
        self.assertEqual(result["status"], "error")

    def test_the_run_stops_blocked_when_what_is_left_cannot_cover_another_attempt(self):
        brief, req = self.lookup(max_cost_usd=0.2)
        t = FakeTransport([transport.TransportError("connection reset after the send")] * 10)
        self.go(req, "--apply", tr=t)
        result = self.result_of(req)
        self.assertLess(len(t.requests), 5)
        self.assertEqual(result["status"], "over-budget")
        self.assertLessEqual(result["cost_usd"], 0.2 + 1e-9)
        self.assertGreater(result["cost_usd"], 0.15)
        self.assertIn("cannot cover", result["error"])

    def test_each_next_attempt_is_sized_to_what_is_left(self):
        brief, req = self.lookup(max_cost_usd=0.3)
        t = FakeTransport([transport.TransportError("read timed out")] * 10)
        self.go(req, "--apply", tr=t)
        sizes = [json.loads(r["body"])["max_completion_tokens"] for r in t.requests]
        self.assertGreater(len(sizes), 1)
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertLess(sizes[1], sizes[0])

    def test_a_5xx_answer_is_charged_and_the_next_attempt_gets_what_is_left(self):
        brief, req = self.lookup(max_cost_usd=1.0)
        ids = self.ids(brief)
        t = FakeTransport([FakeResponse(503), openai_reply(good_report(ids), 100, 50)])
        self.go(req, "--apply", tr=t)
        result = self.result_of(req)
        self.assertAlmostEqual(result["cost_usd"], PER_ATTEMPT + 0.000625, delta=0.005)

    def test_a_429_answer_retries_without_a_charge(self):
        brief, req = self.lookup(max_cost_usd=1.0)
        t = FakeTransport([FakeResponse(429), openai_reply(good_report(self.ids(brief)), 100, 50)])
        self.go(req, "--apply", tr=t)
        self.assertAlmostEqual(self.result_of(req)["cost_usd"], 0.000625, places=6)

    def test_an_error_before_the_send_retries_without_a_charge(self):
        brief, req = self.lookup(max_cost_usd=1.0)
        t = FakeTransport([transport.TransportError("name resolution failed", sent=False),
                           openai_reply(good_report(self.ids(brief)), 100, 50)])
        self.go(req, "--apply", tr=t)
        self.assertAlmostEqual(self.result_of(req)["cost_usd"], 0.000625, places=6)

    def test_urllib_style_classification_refused_and_dns_are_before_the_send(self):
        import socket
        self.assertTrue(transport.before_send(ConnectionRefusedError()))
        self.assertTrue(transport.before_send(socket.gaierror(-2, "no such host")))
        self.assertFalse(transport.before_send(ConnectionResetError()))         # a reset may come after the request went out


class N2StateKeyedByTask(Base):
    def test_a_request_written_elsewhere_still_sees_what_the_task_spent(self):
        brief = self.brief("work", "implementer")
        req = self.request_file(brief, "sdk", max_cost_usd=3.0)
        first = [("init", "sess-1"), ("write", str(self.report_path(brief)), partial_report(delegation.deliverable_ids(brief.read_text(encoding="utf-8")))),
                 ("result", {"subtype": "error_max_turns", "is_error": True, "total_cost_usd": 1.0, "result": ""})]
        self.go(req, "--apply", sdk=make_fake_sdk([first]))
        run_id = json.loads(req.read_text(encoding="utf-8"))["run_id"]
        self.assertTrue((req.parent / f"{run_id}.dispatch-state.json").is_file())    # keyed by the task, under the delegation folder
        elsewhere = self.root / "elsewhere" / "other-request.json"
        elsewhere.parent.mkdir()
        shutil.copy(req, elsewhere)
        sdk = make_fake_sdk([[("init", "sess-2"), ("result", {"subtype": "error_max_turns", "is_error": True, "total_cost_usd": 0.1, "result": ""})]])
        self.go(elsewhere, "--apply", sdk=sdk)
        self.assertEqual(sdk.calls[0]["options"].max_budget_usd, 2.0)

    def test_the_provider_lane_state_is_keyed_by_the_task_too(self):
        brief, req = self.lookup(max_cost_usd=1.0)
        self.go(req, "--apply", tr=FakeTransport([openai_reply(good_report(self.ids(brief)), 100, 4000)]))
        elsewhere = self.root / "elsewhere" / "other-request.json"
        elsewhere.parent.mkdir()
        shutil.copy(req, elsewhere)
        t = FakeTransport([openai_reply(good_report(self.ids(brief)), 100, 50)])
        self.go(elsewhere, "--apply", tr=t)
        result = json.loads(elsewhere.with_name("other-request.dispatch-result.json").read_text(encoding="utf-8"))
        self.assertGreater(result["cost_usd"], 0.04)


class N3N4Policy(unittest.TestCase):
    def decide(self, policy, tool="Bash", tool_input=None):
        return asyncio.run(policy({"tool_name": tool, "tool_input": tool_input or {"command": "ls"}}, "t", None))

    def test_n3_an_invalid_matcher_denies_the_call_with_the_reason(self):
        seen = []
        entries = [{"id": "guard-x", "matcher": "(", "timeout": None, "fail_closed": False}]
        pol = lanes.make_policy(["guard-x"], lambda *a, **k: seen.append(a) or (0, "", ""), cwd="/w", env={}, entries=entries)
        out = self.decide(pol)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("matcher", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(seen, [])

    def scoped(self, tmp):
        root = Path(tmp)
        return lanes.make_policy([], lambda *a, **k: (0, "", ""), cwd=root, env={}, scope=(root, ["src/area/", "tests/area/"], []))

    def test_n4_shell_writes_outside_the_write_scope_are_denied(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pol = self.scoped(tmp)
            for command in ("echo x > /etc/passwd", "cp a.txt /tmp/b.txt", "rm -rf /", "cat f | tee ../escape.txt", "echo x >> docs/notes.md",
                            "echo x > C:/Windows/x.txt", "Set-Content -Path /etc/hosts -Value x", "mv a.py other/dir/b.py", "echo x > $HOME/f",
                            "echo x > ~/f", "touch src/other/f.py"):
                out = self.decide(pol, tool_input={"command": command})
                self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny", command)
                self.assertIn("write", out["hookSpecificOutput"]["permissionDecisionReason"], command)

    def test_n4_shell_writes_inside_the_scope_and_reads_everywhere_pass(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pol = self.scoped(tmp)
            for command in ("echo x > src/area/a.py", "echo x >> tests/area/out.txt", "ls -la /etc", "cat /etc/hosts", "git status --short",
                            "python -m unittest > /dev/null", "git commit -m \"x\" 2> /dev/null", "grep -rn foo . | head"):
                self.assertEqual(self.decide(pol, tool_input={"command": command}), {}, command)

    def test_n4_the_policy_without_a_scope_does_not_judge_writes(self):
        pol = lanes.make_policy([], lambda *a, **k: (0, "", ""), cwd="/w", env={})
        self.assertEqual(self.decide(pol, tool_input={"command": "echo x > /etc/passwd"}), {})


class N5Headers(unittest.TestCase):
    class Conn:
        """A stand-in for http.client.HTTPSConnection."""
        instances = []
        mode = "hang"

        def __init__(self, host, port=None, timeout=None, **kw):
            self.closed = threading.Event()
            self.timeout = timeout
            N5Headers.Conn.instances.append(self)

        def connect(self):
            return None

        def request(self, method, path, body=None, headers=None):
            return None

        def getresponse(self):
            if self.mode == "hang":
                self.closed.wait(10)                                 # a server that never finishes its headers
                raise OSError("connection closed under the read")
            return type("R", (), {"status": 200, "getheaders": lambda s: [("X-Big", "x" * 70000)], "read": lambda s, n=-1: b"{}"})()

        def close(self):
            self.closed.set()

    def run_send(self, mode, timeout):
        self.Conn.mode = mode
        with mock.patch("http.client.HTTPSConnection", self.Conn), mock.patch("http.client.HTTPConnection", self.Conn):
            started = time.monotonic()
            try:
                transport.UrllibTransport().send("POST", "https://h.example/x", {}, b"{}", timeout)
            except transport.TransportError as exc:
                return exc, time.monotonic() - started
        return None, time.monotonic() - started

    def test_a_server_that_never_finishes_its_headers_is_cut_at_the_total_time_budget(self):
        exc, took = self.run_send("hang", 0.4)
        self.assertIsNotNone(exc)
        self.assertIn("time budget", str(exc))
        self.assertTrue(exc.sent)                                    # the request was sent: the call may have billed
        self.assertLess(took, 5.0)

    def test_oversized_headers_are_refused(self):
        exc, _took = self.run_send("big", 5)
        self.assertIsNotNone(exc)
        self.assertIn("headers", str(exc))

    def test_a_connect_failure_is_marked_as_before_the_send(self):
        class Refusing(self.Conn):
            def connect(self):
                raise ConnectionRefusedError("refused")

        with mock.patch("http.client.HTTPSConnection", Refusing):
            with self.assertRaises(transport.TransportError) as cm:
                transport.UrllibTransport().send("POST", "https://h.example/x", {}, b"{}", 5)
        self.assertFalse(cm.exception.sent)


class N6GuardDiscoveryAndLaunch(unittest.TestCase):
    def test_discovering_the_guard_ids_does_not_run_the_launcher_in_this_process(self):
        getattr(lanes, "_HOOK_MODULE", []).clear()
        with mock.patch.object(sys, "dont_write_bytecode", False):
            ids = lanes.default_guards()
            self.assertFalse(sys.dont_write_bytecode)                # hook.py sets this flag when it runs
        self.assertNotIn("batuta_hook_launcher_for_dispatch", sys.modules)
        self.assertEqual(ids, list(guard_area.HOOKS))

    def test_a_guard_runs_through_the_launcher_as_a_subprocess_bounded_by_a_timeout(self):
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(Path.cwd())})
        code, out, err = area._launch_guard("guard-secrets", payload, dict(os.environ), timeout=120)
        self.assertEqual(code, 0, (out, err))
        code, out, err = area._launch_guard("no-such-guard-id", payload, dict(os.environ), timeout=120)
        self.assertEqual(code, 1)                                   # the launcher's non-blocking error for an unknown id
        self.assertIn("unknown handler id", err)

    def test_a_guard_that_runs_too_long_is_cut_and_reported(self):
        import subprocess
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("hook.py", 3)):
            code, out, err = area._launch_guard("guard-secrets", "{}", {}, timeout=3)
        self.assertEqual(code, 1)
        self.assertIn("timed out", err)


if __name__ == "__main__":
    unittest.main()
