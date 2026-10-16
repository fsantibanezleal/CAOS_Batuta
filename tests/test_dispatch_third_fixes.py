"""Findings N5 (real sockets), M2, M3 and M4 of the focused code re-check of U13 at 8e2ec6c, written before the fixes.

The network tests use loopback servers started and stopped by the test itself; nothing leaves this machine."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dispatch_support import ENV, DispatchCase, FakeTransport, good_report, make_fake_sdk, openai_reply, partial_report  # noqa: E402
from test_brief_support import run  # noqa: E402

from batuta_lib import delegation  # noqa: E402
from batuta_lib.areas import dispatch as area  # noqa: E402
from batuta_lib.dispatch import lanes, transport  # noqa: E402


class Server:
    """A loopback TCP server: `handler(conn)` runs for each connection; `stop()` closes everything and joins the thread."""

    def __init__(self, handler):
        self.handler = handler
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.stopped = threading.Event()
        self.connections = 0
        self.thread = threading.Thread(target=self.serve)
        self.thread.start()

    def serve(self):
        while not self.stopped.is_set():
            try:
                conn, _addr = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.connections += 1
            try:
                self.handler(conn, self.stopped)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def stop(self):
        self.stopped.set()
        self.listener.close()
        self.thread.join(15)


def trickle(mode, total=10.0, step=0.2):
    def handler(conn, stopped):
        conn.settimeout(2)
        conn.recv(65536)                                           # the request
        head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100000\r\n\r\n"
        began = time.monotonic()
        if mode == "body":
            conn.sendall(head)
            data = b"x" * 1000
        else:
            data = head                                            # the headers themselves arrive one byte at a time
        for byte in data:
            if stopped.is_set() or time.monotonic() - began > total:
                return
            conn.sendall(bytes([byte]))
            time.sleep(step)
        while not stopped.is_set() and time.monotonic() - began < total:
            conn.sendall(b"y")
            time.sleep(step)
    return handler


class N5RealSockets(unittest.TestCase):
    def call(self, mode, budget):
        server = Server(trickle(mode))
        try:
            started = time.monotonic()
            try:
                transport.UrllibTransport().send("POST", f"http://127.0.0.1:{server.port}/v1/x", {}, b"{}", budget)
            except transport.TransportError as exc:
                return exc, time.monotonic() - started
            return None, time.monotonic() - started
        finally:
            server.stop()

    def test_a_server_that_trickles_its_headers_is_cut_at_the_total_budget(self):
        exc, took = self.call("headers", 1.0)
        self.assertIsNotNone(exc)
        self.assertIn("time budget", str(exc))
        self.assertTrue(exc.sent)
        self.assertLess(took, 3.0, f"the call lasted {took:.1f} s on a 1.0 s budget")

    def test_a_server_that_trickles_its_body_is_cut_at_the_total_budget(self):
        exc, took = self.call("body", 1.0)
        self.assertIsNotNone(exc)
        self.assertIn("time budget", str(exc))
        self.assertTrue(exc.sent)
        self.assertLess(took, 3.0, f"the call lasted {took:.1f} s on a 1.0 s budget")


class N5ChargedAsAnErrorAfterTheSend(DispatchCase):
    def test_a_trickling_provider_ends_the_run_inside_its_limit_and_the_attempt_is_charged(self):
        self.config()
        server = Server(trickle("body"))
        try:
            brief = self.brief("look", "searcher")
            req = self.request_file(brief, "provider:openai", timeout_s=1, max_cost_usd=1.0)
            env = dict(ENV, OPENAI_BASE_URL=f"http://127.0.0.1:{server.port}/v1")
            with mock.patch("time.sleep"):
                started = time.monotonic()
                code, out, err = run("dispatch", "run", "--request", req, "--root", self.root, "--apply", env=env)
                took = time.monotonic() - started
        finally:
            server.stop()
        result = self.result_of(req)
        self.assertLess(took, 8.0)
        self.assertIn(result["status"], ("timeout", "error"))
        self.assertGreater(result["cost_usd"], 0)                   # an error after the send is charged its allowed budget


class M2Proxy(unittest.TestCase):
    def test_no_proxy_matches_hosts_and_domain_suffixes(self):
        env = {"HTTPS_PROXY": "http://proxy.example:3128"}
        self.assertEqual(transport.proxy_for("https://api.example.org/x", env).host, "proxy.example")
        self.assertEqual(transport.proxy_for("https://api.example.org/x", env).port, 3128)
        for entry in ("example.org", ".example.org", "api.example.org", "*", "other.net, example.org"):
            self.assertIsNone(transport.proxy_for("https://api.example.org/x", dict(env, NO_PROXY=entry)), entry)
        for entry in ("other.org", "xample.org", "api.example.org:8443", ""):
            self.assertIsNotNone(transport.proxy_for("https://api.example.org/x", dict(env, NO_PROXY=entry)), entry)
        self.assertIsNone(transport.proxy_for("https://api.example.org/x", dict(env, no_proxy="example.org")))

    def test_lower_case_variable_and_no_variable(self):
        self.assertEqual(transport.proxy_for("https://h.example/x", {"https_proxy": "http://p:8080"}).port, 8080)
        self.assertIsNone(transport.proxy_for("https://h.example/x", {}))
        self.assertIsNone(transport.proxy_for("http://127.0.0.1:1/x", {"HTTPS_PROXY": "http://p:8080"}))      # plain local http is never proxied

    def test_proxy_credentials_become_a_header_and_other_schemes_are_refused(self):
        proxy = transport.proxy_for("https://h.example/x", {"HTTPS_PROXY": "http://user:pa%20ss@p:8080"})
        self.assertTrue(proxy.headers["Proxy-Authorization"].startswith("Basic "))
        with self.assertRaises(transport.TransportError):
            transport.proxy_for("https://h.example/x", {"HTTPS_PROXY": "https://p:8080"})

    def test_a_connect_tunnel_goes_through_the_proxy_stub(self):
        seen = []

        def handler(conn, stopped):
            conn.settimeout(2)
            seen.append(conn.recv(65536).decode("latin-1").split("\r\n")[0])
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")

        server = Server(handler)
        try:
            with mock.patch.dict(os.environ, {"HTTPS_PROXY": f"http://127.0.0.1:{server.port}"}, clear=False):
                os.environ.pop("NO_PROXY", None)
                os.environ.pop("no_proxy", None)
                with self.assertRaises(transport.TransportError) as cm:
                    transport.UrllibTransport().send("POST", "https://api.example.org/v1/x", {}, b"{}", 5)
        finally:
            server.stop()
        self.assertEqual(seen, ["CONNECT api.example.org:443 HTTP/1.1"])
        self.assertFalse(cm.exception.sent)                         # a failed tunnel is before the send

    def test_no_proxy_keeps_the_call_off_the_proxy(self):
        server = Server(lambda conn, stopped: None)
        try:
            with mock.patch.dict(os.environ, {"HTTPS_PROXY": f"http://127.0.0.1:{server.port}", "NO_PROXY": "127.0.0.1"}, clear=False):
                with self.assertRaises(transport.TransportError):
                    transport.UrllibTransport().send("POST", "https://127.0.0.1:9/x", {}, b"{}", 5)    # nothing listens on port 9
        finally:
            server.stop()
        self.assertEqual(server.connections, 0)


class M3Base(DispatchCase):
    def setUp(self):
        super().setUp()
        self.config()
        for p in (mock.patch("time.sleep"), mock.patch.object(area, "_run_command", return_value=(0, "ok"))):
            p.start()
            self.addCleanup(p.stop)

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


class M3DeletingTheStateKeepsTheSpend(M3Base):
    def test_the_provider_lane_takes_the_larger_of_the_state_and_the_ledger(self):
        brief = self.brief("look", "searcher")
        ids = delegation.deliverable_ids(brief.read_text(encoding="utf-8"))
        req = self.request_file(brief, "provider:openai", max_cost_usd=0.05)
        self.go(req, "--apply", tr=FakeTransport([openai_reply(good_report(ids), 100, 4000)]))
        first = self.result_of(req)["cost_usd"]
        state = req.parent / f"{json.loads(req.read_text())['run_id']}.dispatch-state.json"
        self.assertTrue(state.is_file())
        state.unlink()
        t = FakeTransport([openai_reply(good_report(ids), 100, 50)])
        self.go(req, "--apply", tr=t)
        self.assertLessEqual(json.loads(t.requests[0]["body"])["max_completion_tokens"], 1000)
        result = self.result_of(req)
        self.assertAlmostEqual(result["cost_usd"], first + 0.000625, places=6)
        self.assertEqual(result["tokens_in"], 200)

    def test_the_sdk_lane_too(self):
        brief = self.brief("work", "implementer")
        req = self.request_file(brief, "sdk", max_cost_usd=3.0)
        ids = delegation.deliverable_ids(brief.read_text(encoding="utf-8"))
        first = [("init", "s1"), ("write", str(self.report_path(brief)), partial_report(ids)),
                 ("result", {"subtype": "error_max_turns", "is_error": True, "total_cost_usd": 1.0, "result": ""})]
        self.go(req, "--apply", sdk=make_fake_sdk([first]))
        (req.parent / f"{json.loads(req.read_text())['run_id']}.dispatch-state.json").unlink()
        sdk = make_fake_sdk([[("init", "s2"), ("result", {"subtype": "error_max_turns", "is_error": True, "total_cost_usd": 0.25, "result": ""})]])
        self.go(req, "--apply", sdk=sdk)
        self.assertEqual(sdk.calls[0]["options"].max_budget_usd, 2.0)
        self.assertAlmostEqual(self.result_of(req)["cost_usd"], 1.25)


class M4DirectoryChanges(unittest.TestCase):
    def decide(self, tmp, command):
        root = Path(tmp)
        pol = lanes.make_policy([], lambda *a, **k: (0, "", ""), cwd=root, env={}, scope=(root, ["src/area/", "tests/area/"], []))
        return asyncio.run(pol({"tool_name": "Bash", "tool_input": {"command": command}}, "t", None))

    def test_a_relative_target_is_resolved_against_the_folder_the_command_moved_into(self):
        with tempfile.TemporaryDirectory() as tmp:
            for command in ("cd src/area && echo x > a.py", "cd tests/area; touch t.py", "pushd src/area && echo x > b.py",
                            "cd src && cd area && echo x > c.py", "Set-Location src/area; Set-Content -Path x.txt -Value 1",
                            "chdir src/area && echo x > d.py"):
                self.assertEqual(self.decide(tmp, command), {}, command)

    def test_a_move_out_of_the_scope_or_one_that_cannot_be_resolved_denies_the_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            for command in ("cd .. && echo x > f.txt", "cd /tmp && touch a", "cd $DIR && echo x > src/area/a.py", "pushd ../other; touch x",
                            "Set-Location ..; Set-Content -Path x.txt -Value 1", "sl ..; New-Item -Path f -ItemType File",
                            "chdir ../..; rm a", "cd src/area && cd ../.. && echo x > a.py", "cd ~ && echo x > f", "cd src/area; cd -; echo x > a.py"):
                out = self.decide(tmp, command)
                self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny", command)

    def test_a_write_without_any_directory_change_keeps_its_old_behaviour(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.decide(tmp, "echo x > src/area/a.py"), {})
            self.assertEqual(self.decide(tmp, "echo x > docs/a.md").get("hookSpecificOutput", {}).get("permissionDecision"), "deny")


class M5PipeFedWriters(unittest.TestCase):
    """A writer at the end of a pipe or under xargs writes what its input names: deny unless the names are literal paths inside the scope."""

    def decide(self, tmp, command):
        root = Path(tmp)
        pol = lanes.make_policy([], lambda *a, **k: (0, "", ""), cwd=root, env={}, scope=(root, ["src/area/", "tests/area/"], []))
        return asyncio.run(pol({"tool_name": "Bash", "tool_input": {"command": command}}, "t", None)).get("hookSpecificOutput", {}).get("permissionDecision")

    def test_targets_that_cannot_be_known_or_lie_outside_the_scope_are_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            for command in ("ls | xargs rm", "ls docs | xargs rm", "find . -name x | xargs rm", "cat list.txt | xargs touch",
                            "ls src/area | xargs rm -f ../x", "git ls-files | xargs rm", "echo a b | xargs touch", "ls docs | xargs -I{} cp {} src/area/",
                            "cd src/area && ls | xargs rm"):
                self.assertEqual(self.decide(tmp, command), "deny", command)

    def test_literal_paths_inside_the_scope_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            for command in ("ls src/area | xargs rm", "echo src/area/a.py | xargs touch", "ls tests/area | xargs cat"):
                self.assertEqual(self.decide(tmp, command), None, command)


if __name__ == "__main__":
    unittest.main()
