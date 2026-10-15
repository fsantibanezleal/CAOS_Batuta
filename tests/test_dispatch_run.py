"""dispatch run and resume on every lane with a fake transport and a fake SDK: caps, retries, redaction, ledger records
(unit U13, D1 to D4)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dispatch_support import (ENV, MODELS, REPLIES, DispatchCase, FakeResponse, FakeTransport, fake_key, good_report,  # noqa: E402
                               make_fake_sdk, openai_reply, partial_report)
from test_brief_support import CONTRACTS, run, run_json  # noqa: E402

from batuta_lib import contract, delegation  # noqa: E402
from batuta_lib.areas import dispatch as area  # noqa: E402
from batuta_lib.dispatch import transport  # noqa: E402

DIFF_IN = "diff --git a/src/area/a.py b/src/area/a.py\n--- a/src/area/a.py\n+++ b/src/area/a.py\n@@ -1 +1 @@\n-x\n+y\n"
DIFF_OUT = "diff --git a/elsewhere/z.py b/elsewhere/z.py\n--- a/elsewhere/z.py\n+++ b/elsewhere/z.py\n@@ -1 +1 @@\n-x\n+y\n"


def c30_problems(doc):
    schema = contract.load_schema(contract.find_schema(CONTRACTS, "C30"))
    return contract.validate_instance("C30", doc, schema)


class Base(DispatchCase):
    def setUp(self):
        super().setUp()
        self.config()
        patcher = mock.patch("time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)
        checks = mock.patch.object(area, "_run_command", return_value=(0, "ok"))   # a brief's checks never run for real here
        checks.start()
        self.addCleanup(checks.stop)

    def ids(self, brief):
        return delegation.deliverable_ids(brief.read_text(encoding="utf-8"))

    def row(self, ident):
        columns, rows = delegation.ledger_rows(self.ledger.read_text(encoding="utf-8"))
        return next(r for r in rows if r["ID"] == ident)

    def go(self, request, *extra, transport_obj=None, sdk=None, env=None, json_out=False):
        fn = run_json if json_out else run
        patches = []
        if transport_obj is not None:
            patches.append(mock.patch.object(area, "_transport", return_value=transport_obj))
        if sdk is not None:
            patches.append(mock.patch.object(area, "_load_sdk", return_value=sdk))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return fn("dispatch", "run", "--request", request, "--root", self.root, *extra, env=ENV if env is None else env)

    def all_text(self):
        return "".join(p.read_text(encoding="utf-8", errors="ignore") for p in self.root.rglob("*") if p.is_file())

    def assert_no_key(self, *outputs):
        blob = "".join(outputs) + self.all_text()
        for name, value in ENV.items():
            if "://" not in value:
                self.assertNotIn(value, blob, name)


class SubagentLane(Base):
    def test_run_prints_the_launch_spec_and_never_pretends_to_launch(self):
        brief = self.brief("alpha", "searcher")
        req = self.request_file(brief, "subagent", model="haiku")
        code, out, err = self.go(req, "--apply")
        self.assertEqual(code, 0, (out, err))
        self.assertIn("subagent_type", out)
        self.assertIn("run_in_background", out)
        result = self.result_of(req)
        self.assertEqual((result["lane"], result["status"]), ("subagent", "pending"))
        self.assertEqual(c30_problems(result), [])
        self.assertEqual(self.row(result["run_id"])["Status"], "pending")      # drafted -> pending, never launched
        self.assertNotIn("Provider", delegation.ledger_rows(self.ledger.read_text(encoding="utf-8"))[0])

    def test_dry_run_changes_nothing(self):
        brief = self.brief("alpha", "searcher")
        req = self.request_file(brief, "subagent", model="haiku")
        before = self.ledger.read_bytes()
        code, out, _ = self.go(req)
        self.assertEqual(code, 0)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse(req.with_name(req.name.replace("-request", "-result")).exists())


class ProviderLanes(Base):
    def lookup(self, name="alpha"):
        brief = self.brief(name, "searcher")
        return brief, self.ids(brief)

    def test_every_adapter_returns_a_report_that_passes_the_gates(self):
        for name in ("openai", "gemini", "bedrock", "vertex"):
            with self.subTest(provider=name):
                brief, ids = self.lookup(f"look-{name}")
                req = self.request_file(brief, f"provider:{name}")
                t = FakeTransport([REPLIES[name](good_report(ids), 1000, 400)])
                code, out, err = self.go(req, "--apply", "--allow-unpriced", transport_obj=t)
                self.assertIn(code, (0, 2), (out, err))
                result = self.result_of(req)
                self.assertEqual((result["status"], result["provider"], result["model"]), ("complete", name, MODELS[name]), result)
                self.assertEqual((result["tokens_in"], result["tokens_out"]), (1000, 400))
                self.assertEqual(c30_problems(result), [])
                self.assertTrue(self.report_path(brief).is_file())
                row = self.row(result["run_id"])
                self.assertEqual((row["Provider"], row["Tokens in"], row["Tokens out"], row["Model"], row["Status"]),
                                 (name, "1000", "400", MODELS[name], "complete"))
                self.assertRegex(row["Cost USD"], r"^\d+(\.\d+)?$")
                self.assertEqual(delegation.ledger_problems(self.ledger.read_text(encoding="utf-8")), [])
                self.assert_no_key(out, err)

    def test_cost_is_computed_from_the_price_table(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")          # gpt-5: 1.25 in, 10 out per million tokens
        t = FakeTransport([openai_reply(good_report(ids), 200_000, 10_000)])
        self.go(req, "--apply", transport_obj=t)
        self.assertAlmostEqual(self.result_of(req)["cost_usd"], 0.35, places=6)
        self.assertAlmostEqual(float(self.row(self.result_of(req)["run_id"])["Cost USD"]), 0.35, places=4)

    def test_dry_run_shows_what_would_be_sent_redacted_and_sends_nothing(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        t = FakeTransport([])
        code, out, err = self.go(req, transport_obj=t)
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(t.requests, [])
        self.assertIn("chat/completions", out)
        self.assertIn("gpt-5", out)
        self.assertIn("Bearer", out)
        self.assert_no_key(out, err)
        self.assertFalse(self.report_path(brief).exists())

    def test_the_run_stops_when_the_projected_cost_already_exceeds_the_cap(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai", max_cost_usd=0.000001)
        t = FakeTransport([])
        code, out, _ = self.go(req, "--apply", transport_obj=t)
        self.assertEqual(code, 1)
        self.assertEqual(t.requests, [])
        self.assertEqual(self.result_of(req)["status"], "over-budget")
        self.assertEqual(self.row(self.result_of(req)["run_id"])["Status"], "over-budget")

    def test_max_tokens_is_bounded_by_what_the_cap_still_buys(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai", max_cost_usd=0.01)   # 0.01 USD at 10 USD per million output tokens
        t = FakeTransport([openai_reply(good_report(ids), 100, 50)])
        self.go(req, "--apply", transport_obj=t)
        body = json.loads(t.requests[0]["body"])
        self.assertLessEqual(body["max_completion_tokens"], 1000)

    def test_a_provider_that_returns_more_than_the_cap_allows_is_blocked_with_the_partial_cost(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai", max_cost_usd=0.05)
        t = FakeTransport([openai_reply(good_report(ids), 100, 100_000)])      # 1.00 USD of output
        code, out, _ = self.go(req, "--apply", transport_obj=t)
        self.assertEqual(code, 1)
        result = self.result_of(req)
        self.assertEqual(result["status"], "over-budget")
        self.assertGreater(result["cost_usd"], 0.05)
        self.assertEqual(c30_problems(result), [])
        row = self.row(result["run_id"])
        self.assertEqual((row["Status"], row["Tokens out"]), ("over-budget", "100000"))
        self.assertFalse(self.report_path(brief).exists())          # a run over the cap is never accepted

    def test_a_429_storm_is_bounded_then_blocked(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        t = FakeTransport([FakeResponse(429)] * 20)
        code, out, _ = self.go(req, "--apply", transport_obj=t)
        self.assertEqual(code, 1)
        self.assertLessEqual(len(t.requests), transport.MAX_RETRIES + 1)
        result = self.result_of(req)
        self.assertEqual(result["status"], "error")
        self.assertIn("429", result["error"])
        self.assertEqual(self.row(result["run_id"])["Status"], "error")

    def test_a_provider_error_echoing_the_key_is_redacted_everywhere(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        key = ENV["OPENAI_API_KEY"]
        t = FakeTransport([FakeResponse(401, {"error": {"message": f"Incorrect API key provided: {key}. Check Authorization: Bearer {key}"}})])
        code, out, err = self.go(req, "--apply", transport_obj=t, json_out=False)
        self.assertEqual(code, 1)
        self.assert_no_key(out, err)
        self.assertIn("401", out + self.result_of(req)["error"])

    def test_a_transport_error_is_blocked_and_redacted(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        key = ENV["OPENAI_API_KEY"]
        t = FakeTransport([transport.TransportError(f"connection to https://x/?k={key} refused")] * 10)
        code, out, err = self.go(req, "--apply", transport_obj=t)
        self.assertEqual(code, 1)
        self.assert_no_key(out, err)
        self.assertEqual(self.result_of(req)["status"], "error")

    def test_an_unset_credential_at_run_time_is_refused_by_name(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        env = {k: v for k, v in ENV.items() if k != "OPENAI_API_KEY"}
        code, out, _ = self.go(req, "--apply", transport_obj=FakeTransport([]), env=env)
        self.assertEqual(code, 1)
        self.assertIn("OPENAI_API_KEY", out)

    def test_unpriced_model_is_refused_unless_allowed_and_then_cost_is_zero_with_a_warning(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai", model="mystery-1")
        code, out, _ = self.go(req, "--apply", transport_obj=FakeTransport([]))
        self.assertEqual(code, 1)
        self.assertIn("no verified price", out)
        t = FakeTransport([openai_reply(good_report(ids), 10, 5)])
        code, out, _ = self.go(req, "--apply", "--allow-unpriced", transport_obj=t)
        self.assertEqual(code, 2, out)
        self.assertIn("WARN", out)
        self.assertEqual(self.result_of(req)["cost_usd"], 0)

    def test_a_patch_inside_the_write_scope_is_written_next_to_the_report_and_not_applied(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        text = good_report(ids) + f"\n```diff\n{DIFF_IN}```\n"
        t = FakeTransport([openai_reply(text, 50, 50)])
        code, out, _ = self.go(req, "--apply", transport_obj=t)
        self.assertEqual(code, 0, out)
        result = self.result_of(req)
        patch = self.root / result["patch"]
        self.assertEqual(patch.read_text(encoding="utf-8"), DIFF_IN)
        self.assertNotIn("diff --git", self.report_path(brief).read_text(encoding="utf-8"))
        self.assertIn("after the gates", out)
        self.assertFalse((self.root / "src").exists())

    def test_a_patch_outside_the_write_scope_is_refused(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        t = FakeTransport([openai_reply(good_report(ids) + f"\n```diff\n{DIFF_OUT}```\n", 50, 50)])
        code, out, _ = self.go(req, "--apply", transport_obj=t)
        self.assertEqual(code, 1)
        result = self.result_of(req)
        self.assertEqual(result["status"], "error")
        self.assertIn("elsewhere/z.py", result["error"])
        self.assertNotIn("patch", result)
        self.assertFalse(list(self.root.rglob("*.patch")))
        row = self.row(result["run_id"])
        self.assertEqual((row["Status"], row["Provider"]), ("error", "openai"))     # the tokens were still billed

    def test_an_implement_brief_on_a_provider_lane_is_refused_without_report_only(self):
        brief = self.brief("impl", "implementer")
        req = self.request_file(brief, "provider:openai")
        code, out, _ = self.go(req, "--apply", transport_obj=FakeTransport([]))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*implement.*tools")

    def test_report_only_keeps_the_report_and_drops_the_patch(self):
        brief = self.brief("impl", "implementer")
        ids = self.ids(brief)
        req = self.request_file(brief, "provider:openai")
        t = FakeTransport([openai_reply(good_report(ids) + f"\n```diff\n{DIFF_IN}```\n", 50, 50)])
        code, out, _ = self.go(req, "--apply", "--report-only", transport_obj=t)
        self.assertEqual(code, 0, out)
        self.assertNotIn("patch", self.result_of(req))
        self.assertFalse(list(self.root.rglob("*.patch")))

    def test_a_report_that_fails_the_gates_is_defective_and_kept_for_inspection(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        t = FakeTransport([openai_reply("I did it, trust me.", 50, 50)])
        code, out, _ = self.go(req, "--apply", transport_obj=t)
        self.assertEqual(code, 1)
        self.assertEqual(self.result_of(req)["status"], "defective")
        self.assertEqual(self.row(self.result_of(req)["run_id"])["Status"], "defective")
        self.assertTrue(self.report_path(brief).is_file())

    def test_an_incomplete_report_is_incomplete_exit_2(self):
        from _dispatch_support import report_text
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        rows = [(i, "DONE", "`a`") for i in ids[:-1]] + [(ids[-1], "PARTIAL", "missing the rest")] if len(ids) > 1 else [(ids[0], "PARTIAL", "missing")]
        t = FakeTransport([openai_reply(report_text(rows), 50, 50)])
        code, out, _ = self.go(req, "--apply", transport_obj=t)
        self.assertEqual(code, 2)
        self.assertEqual(self.result_of(req)["status"], "incomplete")

    def test_a_zero_hour_limit_stops_before_any_call(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        t = FakeTransport([])
        code, out, _ = self.go(req, "--apply", "--hours", "0", transport_obj=t)
        self.assertEqual(code, 1)
        self.assertEqual(t.requests, [])
        self.assertEqual(self.result_of(req)["status"], "timeout")

    def test_the_time_limit_uses_the_monotonic_clock(self):
        # wall-clock jumps (skew, a changed system time) never shorten or extend a limit
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        t = FakeTransport([openai_reply(good_report(ids), 10, 10)])
        with mock.patch("time.time", side_effect=AssertionError("wall clock read")):
            code, out, _ = self.go(req, "--apply", transport_obj=t)
        self.assertEqual(code, 0, out)

    def test_an_existing_ledger_keeps_its_rows_and_columns(self):
        other = self.brief("other", "searcher")
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        self.go(req, "--apply", transport_obj=FakeTransport([openai_reply(good_report(ids), 10, 10)]))
        text = self.ledger.read_text(encoding="utf-8")
        self.assertIn("other-2026-10-10", text)
        self.assertEqual(self.row("other-2026-10-10")["Status"], "drafted")
        self.assertEqual(self.row("other-2026-10-10")["Provider"], "")
        # a second run of the same brief updates its row, never adds one
        self.go(req, "--apply", transport_obj=FakeTransport([openai_reply(good_report(ids), 20, 20)]))
        columns, rows = delegation.ledger_rows(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(sum(1 for r in rows if r["ID"] == "alpha-2026-10-10"), 1)
        self.assertEqual(self.row("alpha-2026-10-10")["Tokens in"], "20")

    def test_a_ledger_without_a_row_for_the_brief_gets_one(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        self.ledger.unlink()
        self.go(req, "--apply", transport_obj=FakeTransport([openai_reply(good_report(ids), 10, 10)]))
        self.assertEqual(self.row("alpha-2026-10-10")["Provider"], "openai")
        self.assertEqual(delegation.ledger_problems(self.ledger.read_text(encoding="utf-8")), [])

    def test_provider_lanes_cannot_resume(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        self.go(req, "--apply", transport_obj=FakeTransport([openai_reply(good_report(ids), 10, 10)]))
        res = req.with_name(req.name.replace("-request", "-result"))
        code, out, _ = run("dispatch", "resume", "--result", res, "--root", self.root, env=ENV)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*sdk")

    def test_the_replay_transport_answers_from_a_file_and_never_uses_the_network(self):
        brief, ids = self.lookup()
        req = self.request_file(brief, "provider:openai")
        replay = self.root / "replay.json"
        replay.write_text(json.dumps([{"status": 200, "body": json.loads(openai_reply(good_report(ids), 10, 10).body)}]), encoding="utf-8")
        code, out, err = run("dispatch", "run", "--request", req, "--root", self.root, "--apply", "--transport-fixture", replay, env=ENV)
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(self.result_of(req)["status"], "complete")


class SdkLane(Base):
    def brief_and_request(self, **over):
        brief = self.brief("work", "implementer", checks=over.pop("checks", None))
        return brief, self.request_file(brief, "sdk", **over)

    def agent_steps(self, brief, **result):
        report = self.report_path(brief)
        return [("init", "sess-1"), ("text", "working"), ("write", str(report), good_report(self.ids(brief))), ("result", result)]

    def test_apply_runs_the_session_and_records_the_billed_row(self):
        brief, req = self.brief_and_request()
        sdk = make_fake_sdk([self.agent_steps(brief)])
        code, out, err = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 0, (out, err))
        result = self.result_of(req)
        self.assertEqual((result["status"], result["provider"], result["tokens_in"], result["tokens_out"], result["cost_usd"]),
                         ("complete", "anthropic", 1000, 200, 0.5))
        self.assertEqual(c30_problems(result), [])
        row = self.row(result["run_id"])
        self.assertEqual((row["Provider"], row["Tokens in"], row["Tokens out"], row["Cost USD"], row["Status"]),
                         ("anthropic", "1000", "200", "0.5", "complete"))
        self.assertEqual(delegation.ledger_problems(self.ledger.read_text(encoding="utf-8")), [])
        self.assert_no_key(out, err)

    def test_the_options_carry_model_turns_budget_directory_and_the_policy_hook(self):
        brief, req = self.brief_and_request()
        sdk = make_fake_sdk([self.agent_steps(brief)])
        self.go(req, "--apply", sdk=sdk)
        opts = sdk.calls[0]["options"]
        self.assertEqual((opts.model, opts.max_turns), ("claude-sonnet-5-5", 20))
        self.assertLessEqual(opts.max_budget_usd, 5.0)
        self.assertEqual(Path(opts.cwd).resolve(), self.root.resolve())
        self.assertEqual(opts.env["ANTHROPIC_API_KEY"], ENV["ANTHROPIC_API_KEY"])      # the key travels only in the agent's env
        self.assertTrue(opts.hooks["PreToolUse"][0].hooks)
        self.assertIn(brief.read_text(encoding="utf-8").splitlines()[0], sdk.calls[0]["prompt"])

    def test_the_policy_hook_runs_the_guards_through_the_launcher(self):
        brief, req = self.brief_and_request()
        steps = [("init", "sess-1"), ("tool", "Bash", {"command": "ls"}), ("tool", "Read", {"file_path": "a"}),
                 ("write", str(self.report_path(brief)), good_report(self.ids(brief))), ("result", {})]
        sdk = make_fake_sdk([steps])
        calls = []

        def launcher(guard_id, payload_text, env):
            calls.append(guard_id)
            denied = guard_id == "guard-secrets" and json.loads(payload_text)["tool_name"] == "Read"
            return (2, "", "blocked by a guard") if denied else (0, "", "")

        with mock.patch.object(area, "_launch_guard", side_effect=launcher):
            code, out, err = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 0, (out, err))
        self.assertTrue(calls)
        allowed, denied = sdk.decisions
        self.assertEqual(allowed, {})
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_without_the_sdk_the_lane_refuses_with_the_install_command(self):
        brief, req = self.brief_and_request()
        with mock.patch.object(area, "_load_sdk", side_effect=area.SdkMissing("claude-agent-sdk is not installed")):
            code, out, _ = run("dispatch", "run", "--request", req, "--root", self.root, "--apply", env=ENV)
        self.assertEqual(code, 1)
        self.assertIn("pip install claude-agent-sdk", out)

    def test_a_cost_over_the_cap_is_blocked_and_recorded(self):
        brief, req = self.brief_and_request(max_cost_usd=0.4)
        sdk = make_fake_sdk([self.agent_steps(brief, total_cost_usd=0.9)])
        code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 1)
        result = self.result_of(req)
        self.assertEqual(result["status"], "over-budget")
        self.assertEqual(result["cost_usd"], 0.9)
        self.assertEqual(self.row(result["run_id"])["Status"], "over-budget")

    def test_the_sdk_budget_stop_is_over_budget_and_the_budget_option_is_the_cap(self):
        brief, req = self.brief_and_request(max_cost_usd=0.4)
        sdk = make_fake_sdk([[("init", "sess-1"), ("result", {"subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 0.4, "result": ""})]])
        code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(sdk.calls[0]["options"].max_budget_usd, 0.4)
        self.assertEqual(self.result_of(req)["status"], "over-budget")

    def partial_steps(self, brief, **result):
        return [("init", "sess-1"), ("write", str(self.report_path(brief)), partial_report(self.ids(brief))), ("result", result)]

    def test_the_turn_limit_is_incomplete_with_the_reason_when_a_report_exists(self):
        brief, req = self.brief_and_request()
        sdk = make_fake_sdk([self.partial_steps(brief, subtype="error_max_turns", is_error=True, result="")])
        code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 2)
        result = self.result_of(req)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("turn limit", result["error"])

    def test_a_run_that_ends_without_any_report_is_an_error_never_incomplete(self):
        # C30: incomplete and defective are verdicts on a report, so no report means the run did not produce one
        brief, req = self.brief_and_request()
        sdk = make_fake_sdk([[("init", "sess-1"), ("result", {"subtype": "error_max_turns", "is_error": True, "result": ""})]])
        code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 1)
        result = self.result_of(req)
        self.assertEqual(result["status"], "error")
        self.assertIn("turn limit", result["error"])
        self.assertNotIn("report", result)

    def test_the_briefs_checks_run_before_the_result_is_complete(self):
        brief, req = self.brief_and_request(checks=["python -m unittest", "git status --short"])
        sdk = make_fake_sdk([self.agent_steps(brief)])
        ran = []
        with mock.patch.object(area, "_run_command", side_effect=lambda cmd, cwd, timeout: (ran.append(cmd), (0, "ok"))[1]):
            code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(ran, ["python -m unittest", "git status --short"])
        self.assertEqual(self.result_of(req)["status"], "complete")

    def test_a_failing_check_goes_back_to_the_agent_then_stops_incomplete(self):
        brief, req = self.brief_and_request(checks=["python -m unittest"])
        steps = self.agent_steps(brief)
        sdk = make_fake_sdk([steps, steps, steps])
        with mock.patch.object(area, "_run_command", return_value=(1, "FAILED test_x")):
            code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 2)
        self.assertEqual(len(sdk.calls), 3)                   # the first run and two fix rounds
        self.assertIn("FAILED test_x", sdk.calls[1]["prompt"])
        self.assertEqual(sdk.calls[1]["options"].resume, "sess-1")
        result = self.result_of(req)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("python -m unittest", result["error"])
        self.assertAlmostEqual(result["cost_usd"], 1.5)       # cost accumulates across the rounds

    def test_a_check_that_passes_after_a_fix_round_completes(self):
        brief, req = self.brief_and_request(checks=["python -m unittest"])
        steps = self.agent_steps(brief)
        sdk = make_fake_sdk([steps, steps])
        with mock.patch.object(area, "_run_command", side_effect=[(1, "FAILED"), (0, "ok")]):
            code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.result_of(req)["status"], "complete")

    def test_an_agent_that_ends_blocked_is_reported_as_incomplete(self):
        brief, req = self.brief_and_request()
        sdk = make_fake_sdk([self.partial_steps(brief, result="BLOCKED: need a decision")])
        code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(self.result_of(req)["status"], "incomplete")
        self.assertIn("need a decision", self.result_of(req)["error"])

    def test_api_errors_resume_the_saved_session_a_bounded_number_of_times(self):
        brief, req = self.brief_and_request()
        err = [("init", "sess-1"), ("result", {"is_error": True, "subtype": "error_during_execution", "api_error_status": 529, "result": "overloaded"})]
        sdk = make_fake_sdk([err] * 10)
        code, out, _ = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 1)
        self.assertLessEqual(len(sdk.calls), area.MAX_RESUMES + 1)
        self.assertTrue(all(c["options"].resume == "sess-1" for c in sdk.calls[1:]))
        self.assertEqual(self.result_of(req)["status"], "error")

    def test_an_exception_in_the_session_is_an_error_with_the_message_redacted(self):
        brief, req = self.brief_and_request()
        key = ENV["ANTHROPIC_API_KEY"]
        sdk = make_fake_sdk([[("init", "sess-1"), ("raise", RuntimeError(f"auth failed for {key}"))]] * 10)
        code, out, err = self.go(req, "--apply", sdk=sdk)
        self.assertEqual(code, 1)
        self.assert_no_key(out, err)

    def test_the_time_limit_stops_the_session(self):
        brief, req = self.brief_and_request()
        sdk = make_fake_sdk([self.agent_steps(brief)])
        code, out, _ = self.go(req, "--apply", "--hours", "0", sdk=sdk)
        self.assertEqual(code, 1)
        self.assertEqual(self.result_of(req)["status"], "timeout")
        self.assertEqual(sdk.calls, [])

    def test_resume_continues_the_saved_session_within_the_remaining_cap(self):
        brief, req = self.brief_and_request(max_cost_usd=2.0)
        first = [("init", "sess-9"), ("write", str(self.report_path(brief)), partial_report(self.ids(brief))),
                 ("result", {"subtype": "error_max_turns", "is_error": True, "total_cost_usd": 1.5, "session_id": "sess-9", "result": ""})]
        self.go(req, "--apply", sdk=make_fake_sdk([first]))
        res = req.with_name(req.name.replace("-request", "-result"))
        self.assertEqual(self.result_of(req)["status"], "incomplete")
        sdk = make_fake_sdk([[("init", "sess-9"), ("write", str(self.report_path(brief)), good_report(self.ids(brief))),
                              ("result", {"session_id": "sess-9", "total_cost_usd": 0.3})]])
        with mock.patch.object(area, "_load_sdk", return_value=sdk):
            code, out, err = run("dispatch", "resume", "--result", res, "--root", self.root, "--apply", env=ENV)
        self.assertEqual(code, 0, (out, err))
        opts = sdk.calls[0]["options"]
        self.assertEqual(opts.resume, "sess-9")
        self.assertAlmostEqual(opts.max_budget_usd, 0.5)             # 2.0 minus the 1.5 already spent
        result = self.result_of(req)
        self.assertEqual(result["status"], "complete")
        self.assertAlmostEqual(result["cost_usd"], 1.8)              # the total over both runs
        self.assertAlmostEqual(float(self.row(result["run_id"])["Cost USD"]), 1.8)
        self.assert_no_key(out, err)

    def test_resume_with_the_cap_already_spent_is_refused(self):
        brief, req = self.brief_and_request(max_cost_usd=1.0)
        first = [("init", "sess-9"), ("write", str(self.report_path(brief)), partial_report(self.ids(brief))),
                 ("result", {"subtype": "error_max_turns", "is_error": True, "total_cost_usd": 1.0, "session_id": "sess-9", "result": ""})]
        self.go(req, "--apply", sdk=make_fake_sdk([first]))
        res = req.with_name(req.name.replace("-request", "-result"))
        code, out, _ = run("dispatch", "resume", "--result", res, "--root", self.root, "--apply", env=ENV)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*cap")

    def test_resume_of_a_complete_result_is_refused(self):
        brief, req = self.brief_and_request()
        self.go(req, "--apply", sdk=make_fake_sdk([self.agent_steps(brief)]))
        res = req.with_name(req.name.replace("-request", "-result"))
        code, out, _ = run("dispatch", "resume", "--result", res, "--root", self.root, "--apply", env=ENV)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*complete")

    def test_the_key_comes_from_the_configured_key_file_and_is_not_written_anywhere(self):
        keyfile = self.root / "anthropic.key"
        keyfile.write_text("# key\n" + fake_key() + "\n", encoding="utf-8")
        self.config(sdk={"key_file": keyfile.as_posix()})
        env = {k: v for k, v in ENV.items() if k != "ANTHROPIC_API_KEY"}
        brief, req = self.brief_and_request()
        sdk = make_fake_sdk([self.agent_steps(brief)])
        code, out, err = self.go(req, "--apply", sdk=sdk, env=env)
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(sdk.calls[0]["options"].env["ANTHROPIC_API_KEY"], fake_key())
        blob = out + err + "".join(p.read_text(encoding="utf-8", errors="ignore") for p in self.root.rglob("*")
                                   if p.is_file() and p != keyfile)
        self.assertNotIn(fake_key(), blob)

    def test_dry_run_starts_nothing(self):
        brief, req = self.brief_and_request()
        sdk = make_fake_sdk([self.agent_steps(brief)])
        code, out, _ = self.go(req, sdk=sdk)
        self.assertEqual((code, sdk.calls), (0, []))
        self.assertIn("claude-sonnet-5-5", out)


class NoDetach(unittest.TestCase):
    def test_the_dispatch_code_never_detaches_a_process_or_schedules_anything(self):
        import re
        root = Path(area.__file__).resolve().parents[1]
        text = "".join(p.read_text(encoding="utf-8") for p in [Path(area.__file__), *sorted((root / "dispatch").glob("*.py"))])
        for pattern in (r"Popen", r"start_new_session", r"DETACHED_PROCESS", r"os\.fork", r"daemon\s*=\s*True", r"schtasks", r"crontab", r"nohup"):
            self.assertIsNone(re.search(pattern, text), pattern)


if __name__ == "__main__":
    unittest.main()
