"""Findings of the Opus code review of U13 (F1 to F17): one reproduction per finding, written before the fixes."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dispatch_support import (ENV, DispatchCase, FakeResponse, FakeTransport, fake_key, good_report, make_fake_sdk,  # noqa: E402
                               openai_reply, partial_report, report_text)
from test_brief_support import run  # noqa: E402

from batuta_lib import delegation  # noqa: E402
from batuta_lib.areas import dispatch as area  # noqa: E402
from batuta_lib.areas import guard as guard_area  # noqa: E402
from batuta_lib.dispatch import lanes, prices, transport  # noqa: E402


class Base(DispatchCase):
    def setUp(self):
        super().setUp()
        self.config()
        for p in (mock.patch("time.sleep"), mock.patch.object(area, "_run_command", return_value=(0, "ok"))):
            p.start()
            self.addCleanup(p.stop)

    def ids(self, brief):
        return delegation.deliverable_ids(brief.read_text(encoding="utf-8"))

    def row(self, ident):
        return next(r for r in delegation.ledger_rows(self.ledger.read_text(encoding="utf-8"))[1] if r["ID"] == ident)

    def go(self, request, *extra, tr=None, sdk=None, env=None, verb="run"):
        patches = []
        if tr is not None:
            patches.append(mock.patch.object(area, "_transport", return_value=tr))
        if sdk is not None:
            patches.append(mock.patch.object(area, "_load_sdk", return_value=sdk))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        flag = "--request" if verb == "run" else "--result"
        return run("dispatch", verb, flag, request, "--root", self.root, *extra, env=ENV if env is None else env)

    def everything(self, *outputs):
        files = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in self.root.rglob("*")
                        if p.is_file() and not p.name.endswith(".replay.json"))
        return "".join(outputs) + files

    def sdk_case(self, **over):
        brief = self.brief("work", "implementer")
        return brief, self.request_file(brief, "sdk", **over)

    def ok_steps(self, brief, **result):
        return [("init", "sess-1"), ("write", str(self.report_path(brief)), good_report(self.ids(brief))), ("result", result)]


class F1CumulativeCost(Base):
    def test_a_crash_charges_the_budget_the_call_was_given_and_resume_cannot_spend_it_again(self):
        brief, req = self.sdk_case(max_cost_usd=2.0)
        sdk = make_fake_sdk([[("init", "sess-1"), ("raise", RuntimeError("connection lost"))]] * 4)
        code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 1)
        self.assertEqual(len(sdk.calls), 1)                       # the cap is spent: no second call can start
        result = self.result_of(req)
        self.assertEqual(result["status"], "over-budget")
        self.assertEqual(result["cost_usd"], 2.0)
        self.assertEqual(float(self.row(result["run_id"])["Cost USD"]), 2.0)
        self.assertIn("connection lost", result["error"])

    def test_a_timeout_in_the_session_records_a_cost_above_zero(self):
        brief, req = self.sdk_case(max_cost_usd=2.0)
        sdk = make_fake_sdk([[("init", "sess-1"), ("raise", TimeoutError("the time limit ended"))]])
        code, out, _ = self.go(req, "--apply", sdk=sdk)
        result = self.result_of(req)
        self.assertEqual(result["status"], "timeout")
        self.assertGreater(result["cost_usd"], 0)
        self.assertGreater(float(self.row(result["run_id"])["Cost USD"]), 0)

    def test_every_call_gets_at_most_what_is_left_of_the_cap_across_runs(self):
        brief, req = self.sdk_case(max_cost_usd=3.0)
        first = [("init", "sess-1"), ("write", str(self.report_path(brief)), partial_report(self.ids(brief))),
                 ("result", {"subtype": "error_max_turns", "is_error": True, "total_cost_usd": 1.0, "result": ""})]
        self.go(req, "--apply", sdk=make_fake_sdk([first]))
        sdk = make_fake_sdk([self.ok_steps(brief, total_cost_usd=0.5)])
        self.go(req, "--apply", sdk=sdk)                          # a fresh run of the same task keeps the spent amount
        self.assertEqual(sdk.calls[0]["options"].max_budget_usd, 2.0)
        result = self.result_of(req)
        self.assertAlmostEqual(result["cost_usd"], 1.5)

    def test_the_provider_lane_is_cumulative_per_task_too(self):
        brief = self.brief("look", "searcher")
        ids = self.ids(brief)
        req = self.request_file(brief, "provider:openai", max_cost_usd=0.05)
        self.go(req, "--apply", tr=FakeTransport([openai_reply(good_report(ids), 100, 4000)]))      # 0.040125 USD
        first = self.result_of(req)["cost_usd"]
        t = FakeTransport([openai_reply(good_report(ids), 100, 50)])
        self.go(req, "--apply", tr=t)
        body = json.loads(t.requests[0]["body"])
        self.assertLessEqual(body["max_completion_tokens"], 1000)                # what 0.05 minus 0.04 still buys
        result = self.result_of(req)
        self.assertAlmostEqual(result["cost_usd"], first + 0.000625, places=6)
        self.assertEqual(result["tokens_in"], 200)

    def test_a_provider_call_that_may_have_billed_without_usage_charges_its_allowed_budget(self):
        brief = self.brief("look", "searcher")
        req = self.request_file(brief, "provider:openai", max_cost_usd=0.5)
        t = FakeTransport([transport.TransportError("read timed out")] * 8)
        code, out, _ = self.go(req, "--apply", tr=t)
        result = self.result_of(req)
        self.assertEqual(result["status"], "error")
        self.assertGreater(result["cost_usd"], 0)
        self.assertIn("allowed budget", result["error"])

    def test_a_429_storm_is_not_charged_because_the_provider_refused_every_call(self):
        brief = self.brief("look", "searcher")
        req = self.request_file(brief, "provider:openai")
        self.go(req, "--apply", tr=FakeTransport([FakeResponse(429)] * 20))
        self.assertEqual(self.result_of(req)["cost_usd"], 0)


class F2Redaction(Base):
    def test_a_key_in_a_successful_answer_reaches_no_file_and_no_output(self):
        brief = self.brief("look", "searcher")
        ids = self.ids(brief)
        key = ENV["OPENAI_API_KEY"]
        rows = [(i, "PARTIAL", f"half done, key {key}") for i in ids]
        text = report_text(rows) + f"\n```diff\ndiff --git a/src/area/a.py b/src/area/a.py\n--- a/src/area/a.py\n+++ b/src/area/a.py\n@@ -1 +1 @@\n-x\n+token = '{key}'\n```\n"
        req = self.request_file(brief, "provider:openai")
        code, out, err = self.go(req, "--apply", tr=FakeTransport([openai_reply(text, 100, 100)]))
        self.assertNotIn(key, self.everything(out, err))
        self.assertTrue(self.report_path(brief).is_file())                   # the report and the patch were written, redacted
        self.assertTrue(list(self.root.rglob("*.patch")))

    def test_the_result_and_ledger_are_redacted_before_they_are_written(self):
        brief = self.brief("look", "searcher")
        req = self.request_file(brief, "provider:openai")
        key = ENV["OPENAI_API_KEY"]
        t = FakeTransport([FakeResponse(200, {"choices": [{"message": {"content": f"x {key}"}}], "usage": "broken " + key})])
        code, out, err = self.go(req, "--apply", tr=t)
        self.assertNotIn(key, self.everything(out, err))

    def test_a_sdk_session_error_with_the_key_reaches_no_file_and_no_output(self):
        brief, req = self.sdk_case()
        key = ENV["ANTHROPIC_API_KEY"]
        sdk = make_fake_sdk([[("init", "s"), ("result", {"is_error": True, "subtype": "error_during_execution", "result": f"bad {key}",
                                                         "api_error_status": 400})]])
        code, out, err = self.go(req, "--apply", sdk=sdk)
        self.assertNotIn(key, self.everything(out, err))


class F3F4F6F10F11Policy(unittest.TestCase):
    def policy(self, answers, ids, **kw):
        self.seen = []

        def launcher(gid, payload, env, timeout=None):
            self.seen.append((gid, threading.current_thread() is threading.main_thread(), timeout))
            return answers[gid]

        return lanes.make_policy(ids, launcher, cwd="/w", env={}, **kw)

    def decide(self, policy, tool="Bash", tool_input=None):
        return asyncio.run(policy({"tool_name": tool, "tool_input": tool_input or {"command": "ls"}}, "t", None))

    ASK = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "sure?"}})

    def test_f3_an_ask_never_hides_a_later_deny(self):
        out = self.decide(self.policy({"g1": (0, self.ASK, ""), "g2": (2, "", "no")}, ["g1", "g2"]))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual([s[0] for s in self.seen], ["g1", "g2"])         # every configured guard is evaluated

    def test_f3_ask_beats_allow_and_all_allow_is_empty(self):
        out = self.decide(self.policy({"g1": (0, "", ""), "g2": (0, self.ASK, "")}, ["g1", "g2"]))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertEqual(self.decide(self.policy({"g1": (0, "", "")}, ["g1"])), {})

    def test_f3_a_fail_closed_failure_denies_even_after_an_ask(self):
        out = self.decide(self.policy({"g1": (0, self.ASK, ""), "g2": (1, "", "boom")}, ["g1", "g2"], fail_closed={"g2"}))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_f4_the_default_guard_set_equals_the_guard_area_handler_ids(self):
        self.assertEqual(lanes.default_guards(), list(guard_area.HOOKS))
        self.assertIn("guard-require-brief", lanes.default_guards())
        ids, closed = lanes.guard_ids_from_registry(Path("no-such-hooks.json"))
        self.assertEqual(ids, list(guard_area.HOOKS))

    def test_f10_the_guards_run_off_the_event_loop_thread(self):
        self.decide(self.policy({"g1": (0, "", "")}, ["g1"]))
        self.assertFalse(self.seen[0][1])

    def test_f11_registry_matcher_and_timeout_are_honoured(self):
        import tempfile
        hooks = {"hooks": {"PreToolUse": [
            {"matcher": "Bash|PowerShell", "hooks": [{"type": "command", "command": "py", "args": ["hook.py", "guard-destructive"], "timeout": 7}]},
            {"hooks": [{"type": "command", "command": "py", "args": ["hook.py", "guard-secrets"]}]}]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hooks.json"
            path.write_text(json.dumps(hooks), encoding="utf-8")
            entries = lanes.guard_entries_from_registry(path)
        self.assertEqual([(e["id"], e["matcher"], e["timeout"]) for e in entries],
                         [("guard-destructive", "Bash|PowerShell", 7), ("guard-secrets", None, None)])
        pol = self.policy({"guard-destructive": (0, "", ""), "guard-secrets": (0, "", "")}, [e["id"] for e in entries], entries=entries)
        self.decide(pol, tool="Read", tool_input={"file_path": "a"})
        self.assertEqual([s[0] for s in self.seen], ["guard-secrets"])    # the Bash guard does not see a Read
        self.seen.clear()
        self.decide(pol, tool="Bash")
        self.assertEqual([(s[0], s[2]) for s in self.seen], [("guard-destructive", 7), ("guard-secrets", None)])

    DENIED = ["env", "printenv", "printenv ANTHROPIC_API_KEY", "set", "Get-ChildItem env:", "gci Env:", "dir env:", "echo $env:ANTHROPIC_API_KEY",
              "echo ${env:HOME}", "cat /proc/self/environ", "cat /proc/1234/environ", "python -c \"import os; print(os.environ)\"",
              "echo $ANTHROPIC_API_KEY", "e\"\"nv", "ENV", "git push origin main", "git push origin HEAD:develop", "git push --force origin x",
              "git push -f", "git push", "git push origin +feature", "gh pr merge 7 --merge", "gh api repos/o/r/merges -X POST",
              "gh repo delete o/r", "gh secret set X", "git checkout main", "git switch develop", "docker system prune -af"]
    ALLOWED = ["ls -la", "git status --short", "git push -u origin task/u13-fix", "echo environment", "git commit -m \"set up the env\"",
               "python -m unittest", "grep -n setup file.py"]

    def test_f6_the_orchestrator_denies_are_ported(self):
        for command in self.DENIED:
            self.assertIsNotNone(lanes.deny_reason("Bash", {"command": command}), command)
            self.assertIsNotNone(lanes.deny_reason("PowerShell", {"command": command}), command)

    def test_f6_ordinary_commands_pass(self):
        for command in self.ALLOWED:
            self.assertIsNone(lanes.deny_reason("Bash", {"command": command}), command)

    def test_f6_reading_the_process_environment_file_is_denied_for_the_read_tool_too(self):
        self.assertIsNotNone(lanes.deny_reason("Read", {"file_path": "/proc/self/environ"}))
        self.assertIsNone(lanes.deny_reason("Read", {"file_path": "src/a.py"}))

    def test_f6_the_policy_denies_before_any_guard_runs(self):
        out = self.decide(self.policy({"g1": (0, "", "")}, ["g1"]), tool_input={"command": "printenv"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.seen, [])


class F4NoGuards(Base):
    def test_f4_an_sdk_run_with_no_guard_to_run_is_refused(self):
        brief, req = self.sdk_case()
        with mock.patch.object(lanes, "guard_ids_from_registry", return_value=([], set())):
            code, out, _ = self.go(req, "--apply", sdk=make_fake_sdk([self.ok_steps(brief)]))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*guard")


class F5ChecksInsideTheTimeLimit(Base):
    def test_the_remaining_time_bounds_each_check_and_an_expired_limit_ends_as_timeout(self):
        brief = self.brief("work", "implementer", checks=["python -m unittest", "git status --short"])
        req = self.request_file(brief, "sdk", timeout_s=100)
        now = [1000.0]
        seen = []

        def command(cmd, cwd, timeout):
            seen.append((cmd, timeout))
            now[0] += 150.0                                       # the first check runs past the whole limit
            return 124, "timed out"

        sdk = make_fake_sdk([self.ok_steps(brief)] * 2)
        with mock.patch.object(area, "_monotonic", side_effect=lambda: now[0]), mock.patch.object(area, "_run_command", side_effect=command):
            code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(len(seen), 1)                            # the second check never started
        self.assertLessEqual(seen[0][1], 100)
        self.assertEqual(self.result_of(req)["status"], "timeout")
        self.assertEqual(len(sdk.calls), 1)


class F7ProviderChecks(Base):
    def test_the_briefs_checks_run_and_a_failing_check_leaves_the_result_incomplete(self):
        brief = self.brief("look", "searcher", checks=["python -m unittest"])
        req = self.request_file(brief, "provider:openai")
        ran = []
        with mock.patch.object(area, "_run_command", side_effect=lambda c, cwd, t: (ran.append(c), (1, "FAILED test_x"))[1]):
            code, out, _ = self.go(req, "--apply", tr=FakeTransport([openai_reply(good_report(self.ids(brief)), 10, 10)]))
        self.assertEqual(ran, ["python -m unittest"])
        self.assertEqual(code, 2)
        result = self.result_of(req)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("python -m unittest", result["error"])

    def test_passing_checks_make_it_complete(self):
        brief = self.brief("look", "searcher", checks=["python -m unittest"])
        req = self.request_file(brief, "provider:openai")
        code, out, _ = self.go(req, "--apply", tr=FakeTransport([openai_reply(good_report(self.ids(brief)), 10, 10)]))
        self.assertEqual((code, self.result_of(req)["status"]), (0, "complete"))

    def test_with_a_patch_the_result_is_incomplete_because_the_checks_wait_for_it(self):
        brief = self.brief("look", "searcher", checks=["python -m unittest"])
        req = self.request_file(brief, "provider:openai")
        diff = "diff --git a/src/area/a.py b/src/area/a.py\n--- a/src/area/a.py\n+++ b/src/area/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        ran = []
        with mock.patch.object(area, "_run_command", side_effect=lambda c, cwd, t: (ran.append(c), (0, "ok"))[1]):
            code, out, _ = self.go(req, "--apply", tr=FakeTransport([openai_reply(good_report(self.ids(brief)) + f"\n```diff\n{diff}```\n", 10, 10)]))
        self.assertEqual(ran, [])
        result = self.result_of(req)
        self.assertEqual((code, result["status"]), (2, "incomplete"))
        self.assertIn("wait for the patch", result["error"])
        self.assertIn("patch", result)


class F8BilledParseErrors(Base):
    def test_a_2xx_answer_with_usage_but_no_text_records_the_cost_of_that_usage(self):
        brief = self.brief("look", "searcher")
        req = self.request_file(brief, "provider:openai")
        t = FakeTransport([FakeResponse(200, {"usage": {"prompt_tokens": 100, "completion_tokens": 50}})])
        code, out, _ = self.go(req, "--apply", tr=t)
        result = self.result_of(req)
        self.assertEqual((result["status"], result["tokens_in"], result["tokens_out"]), ("error", 100, 50))
        self.assertAlmostEqual(result["cost_usd"], 0.000625, places=6)

    def test_a_2xx_answer_without_usage_records_the_upper_bound_never_zero(self):
        brief = self.brief("look", "searcher")
        req = self.request_file(brief, "provider:openai", max_cost_usd=0.5)
        t = FakeTransport([FakeResponse(200, {"choices": [{"message": {"content": "x"}}]})])
        code, out, _ = self.go(req, "--apply", tr=t)
        result = self.result_of(req)
        self.assertEqual(result["status"], "error")
        self.assertGreater(result["cost_usd"], 0)
        self.assertGreater(result["tokens_out"], 0)
        self.assertIn("upper bound", result["error"])
        self.assertGreater(float(self.row(result["run_id"])["Cost USD"]), 0)

    def test_a_4xx_answer_is_not_charged(self):
        brief = self.brief("look", "searcher")
        req = self.request_file(brief, "provider:openai")
        self.go(req, "--apply", tr=FakeTransport([FakeResponse(401, {"error": "no"})]))
        self.assertEqual(self.result_of(req)["cost_usd"], 0)


class F9Transport(unittest.TestCase):
    def test_a_trickling_server_cannot_hold_the_call_past_its_time_budget(self):
        clock = [0.0]

        class Slow:
            status, headers = 200, {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                clock[0] += 4.0                       # four seconds a chunk, however short the socket timeout is
                return b"x" * 10

        with mock.patch("urllib.request.urlopen", return_value=Slow()), mock.patch.object(transport.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(transport.TransportError) as cm:
                transport.UrllibTransport().send("POST", "https://h.example/x", {}, b"{}", 10)
        self.assertIn("time budget", str(cm.exception))
        self.assertLessEqual(clock[0], 20.0)


class F12KeyFile(Base):
    def test_the_key_file_path_expands_variables_and_a_file_without_a_key_is_refused(self):
        folder = self.root / "keys"
        folder.mkdir()
        (folder / "a.key").write_text("# note\n" + fake_key() + "\n", encoding="utf-8")
        self.config(sdk={"key_file": "$KEYDIR/a.key"})
        env = {k: v for k, v in ENV.items() if k != "ANTHROPIC_API_KEY"}
        env["KEYDIR"] = folder.as_posix()
        brief, req = self.sdk_case()
        sdk = make_fake_sdk([self.ok_steps(brief)])
        code, out, err = self.go(req, "--apply", sdk=sdk, env=env)
        self.assertEqual(code, 0, (out, err))
        (folder / "a.key").write_text("# note\nnot-a-key-at-all\n", encoding="utf-8")
        code, out, _ = self.go(req, "--apply", sdk=make_fake_sdk([self.ok_steps(brief)]), env=env)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*key")


class F13ResumeTimeLimit(Base):
    def test_resume_counts_the_time_already_used_and_refuses_when_it_is_spent(self):
        brief, req = self.sdk_case(max_cost_usd=3.0, timeout_s=600)
        first = [("init", "sess-9"), ("write", str(self.report_path(brief)), partial_report(self.ids(brief))),
                 ("result", {"subtype": "error_max_turns", "is_error": True, "total_cost_usd": 0.5, "session_id": "sess-9", "result": ""})]
        self.go(req, "--apply", sdk=make_fake_sdk([first]))
        state = req.with_name(req.name.replace("-request.json", "-state.json"))
        data = json.loads(state.read_text(encoding="utf-8"))
        self.assertIn("elapsed_s", data)
        data["elapsed_s"] = 600
        state.write_text(json.dumps(data), encoding="utf-8")
        res = req.with_name(req.name.replace("-request", "-result"))
        code, out, _ = run("dispatch", "resume", "--result", res, "--root", self.root, "--apply", env=ENV)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*time limit")


class F14ApiKeySource(Base):
    def test_a_session_that_is_not_using_the_api_key_is_refused_not_retried(self):
        brief, req = self.sdk_case()
        sdk = make_fake_sdk([[("init", "sess-1", "claude.ai login"), ("result", {})]] * 4)
        code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 1)
        self.assertEqual(len(sdk.calls), 1)
        self.assertIn("apiKeySource", self.result_of(req)["error"])


class F16RequestMatchesBrief(Base):
    def test_a_request_whose_scope_or_report_differs_from_the_brief_is_refused(self):
        brief = self.brief("look", "searcher")
        req = self.request_file(brief, "provider:openai", write_scope=["src/", "docs/"])
        code, out, _ = self.go(req, "--apply", tr=FakeTransport([]))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*write_scope")
        req = self.request_file(brief, "provider:openai", report=".batuta/delegation/other.report.md")
        code, out, _ = self.go(req, "--apply", tr=FakeTransport([]))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*report")


class F17Patch(unittest.TestCase):
    def test_git_c_quoted_paths_are_decoded(self):
        patch = ('diff --git "a/sp ace/\\303\\251.py" "b/sp ace/\\303\\251.py"\n--- "a/sp ace/\\303\\251.py"\n+++ "b/sp ace/\\303\\251.py"\n'
                 '@@ -1 +1 @@\n-x\n+y\ndiff --git "a/t\\tab.py" "b/t\\tab.py"\n--- "a/t\\tab.py"\n+++ "b/t\\tab.py"\n')
        files = lanes.patch_files(patch)
        self.assertEqual(files, ["sp ace/é.py", "t\tab.py"])

    def test_a_decoded_path_is_still_checked_against_the_scope(self):
        patch = 'diff --git "a/\\056\\056/x.py" "b/\\056\\056/x.py"\n--- "a/\\056\\056/x.py"\n+++ "b/\\056\\056/x.py"\n'
        self.assertEqual(lanes.scope_violations(lanes.patch_files(patch), ["src/"]), ["../x.py"])


class RunCommandIsReal(unittest.TestCase):
    def test_a_check_command_runs_and_reports_its_exit_code_and_output(self):
        code, output = area._run_command(f'"{sys.executable.replace(chr(92), "/")}" -c "import sys; print(7); sys.exit(3)"', str(Path.cwd()), 60)
        self.assertEqual(code, 3)
        self.assertIn("7", output)


class Prices(unittest.TestCase):
    def test_vertex_and_bedrock_rows_stay_unknown_until_a_primary_page_confirms_them(self):
        for model in ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1"):
            self.assertIsNone(prices.lookup("vertex", model), model)
        for model in ("global.anthropic.claude-sonnet-5-5", "us.anthropic.claude-sonnet-5-5", "anthropic.claude-sonnet-5-5"):
            self.assertIsNone(prices.lookup("bedrock", model), model)

    def test_the_long_context_tier_applies_above_the_threshold(self):
        for model, standard, long_ in (("gpt-5.4", (2.5, 15.0), (5.0, 22.5)), ("gpt-5.5", (5.0, 30.0), (10.0, 45.0))):
            price = prices.lookup("openai", model)
            self.assertAlmostEqual(prices.cost_usd(price, 272_000, 1000), (272_000 * standard[0] + 1000 * standard[1]) / 1e6)
            self.assertAlmostEqual(prices.cost_usd(price, 272_001, 1000), (272_001 * long_[0] + 1000 * long_[1]) / 1e6)

    def test_gpt_5_has_no_unconfirmed_tier_note_and_every_entry_keeps_source_and_date(self):
        entry = prices.load_prices()["prices"]["openai"]["gpt-5"]
        self.assertNotIn("272000", entry["note"])
        self.assertEqual(entry["read"], "2026-10-15")

    def test_the_output_budget_uses_the_long_tier_when_the_input_is_long(self):
        price = prices.lookup("openai", "gpt-5.4")
        short = lanes.plan_output_budget(price, 1000, 1.0)
        long_ = lanes.plan_output_budget(price, 300_000, 3.0)
        self.assertEqual(short, lanes.DEFAULT_MAX_OUT)
        self.assertEqual(long_, min(lanes.DEFAULT_MAX_OUT, int((3.0 - 300_000 * 5.0 / 1e6) * 1e6 / 22.5)))

    def test_bedrock_inference_profile_ids_build_the_converse_url(self):
        from batuta_lib.dispatch import adapters
        for model in ("global.anthropic.claude-sonnet-5-5", "us.anthropic.claude-sonnet-5-5"):
            url, _h, _b = adapters.request_for("bedrock", model=model, system="s", prompt="p", max_tokens=5, credential="K" * 12,
                                               endpoint="https://bedrock-runtime.us-east-1.example.org")
            self.assertEqual(url, f"https://bedrock-runtime.us-east-1.example.org/model/{model}/converse")


if __name__ == "__main__":
    unittest.main()
