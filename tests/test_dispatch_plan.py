"""dispatch plan: the C30 request, lane and credential validation, caps and prices (unit U13, D1)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dispatch_support import ENV, DispatchCase, fake_key  # noqa: E402
from test_brief_support import CONTRACTS, run, run_json  # noqa: E402

from batuta_lib import contract  # noqa: E402


def c30_problems(doc):
    schema = contract.load_schema(contract.find_schema(CONTRACTS, "C30"))
    return contract.validate_instance("C30", doc, schema)


class Plan(DispatchCase):
    def plan(self, brief, *extra, env=None, json_out=False):
        fn = run_json if json_out else run
        return fn("dispatch", "plan", "--brief", brief, "--root", self.root, *extra, env=ENV if env is None else env)

    def written(self, brief):
        ident = brief.name.removesuffix(".brief.md")
        return json.loads((brief.parent / f"{ident}.dispatch-request.json").read_text(encoding="utf-8"))

    def test_the_default_lane_writes_a_valid_subagent_request(self):
        self.config()
        brief = self.brief(agent="searcher")
        code, out, err = self.plan(brief)
        self.assertEqual(code, 0, (out, err))
        req = self.written(brief)
        self.assertEqual(c30_problems(req), [])
        self.assertEqual((req["lane"], req["role"], req["model"], req["kind"]), ("subagent", "searcher", "haiku", "request"))
        self.assertEqual(req["brief"], brief.relative_to(self.root).as_posix())
        self.assertEqual(req["max_turns"], 20)           # from the brief's "about 20 turns"
        self.assertNotIn("provider", req)
        self.assertIn(req["run_id"], out)

    def test_a_provider_lane_carries_the_provider_the_credential_name_and_the_cap(self):
        self.config(cap=5.0)
        brief = self.brief(agent="searcher")
        code, out, err = self.plan(brief, "--lane", "provider:openai", "--model", "gpt-5")
        self.assertEqual(code, 0, (out, err))
        req = self.written(brief)
        self.assertEqual(c30_problems(req), [])
        self.assertEqual((req["provider"], req["credential_env"], req["model"], req["max_cost_usd"]), ("openai", "OPENAI_API_KEY", "gpt-5", 5.0))

    def test_the_sdk_lane_uses_the_role_model_resolved_to_an_id(self):
        self.config()
        brief = self.brief()
        code, out, err = self.plan(brief, "--lane", "sdk")
        self.assertEqual(code, 0, (out, err))
        req = self.written(brief)
        self.assertEqual((req["lane"], req["model"], req["credential_env"]), ("sdk", "claude-sonnet-5-5", "ANTHROPIC_API_KEY"))
        self.assertEqual(c30_problems(req), [])

    def test_write_scope_and_report_come_from_the_brief(self):
        self.config()
        brief = self.brief()
        self.plan(brief)
        req = self.written(brief)
        self.assertEqual(req["write_scope"], ["src/area/", "tests/area/"])
        self.assertTrue(req["report"].endswith(".report.md"))

    def test_an_unknown_provider_is_refused(self):
        self.config()
        code, out, _ = self.plan(self.brief(), "--lane", "provider:nowhere", "--model", "m")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*nowhere")

    def test_a_lane_that_is_not_enabled_is_refused(self):
        self.config(lanes=("subagent",))
        code, out, _ = self.plan(self.brief(), "--lane", "sdk")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*sdk.*not enabled")

    def test_a_missing_credential_variable_is_refused_by_name_never_by_value(self):
        self.config()
        env = dict(ENV)
        del env["OPENAI_API_KEY"]
        code, out, err = self.plan(self.brief(), "--lane", "provider:openai", "--model", "gpt-5", env=env)
        self.assertEqual(code, 1)
        self.assertIn("OPENAI_API_KEY", out)
        env["OPENAI_API_KEY"] = ""      # set but empty counts as missing
        code, out, _ = self.plan(self.brief("beta"), "--lane", "provider:openai", "--model", "gpt-5", env=env)
        self.assertEqual(code, 1)

    def test_the_sdk_lane_accepts_a_key_file_from_the_configuration(self):
        keyfile = self.root / "anthropic.key"
        keyfile.write_text(fake_key() + "\n", encoding="utf-8")
        self.config(sdk={"key_file": keyfile.as_posix()})
        env = dict(ENV)
        del env["ANTHROPIC_API_KEY"]
        code, out, err = self.plan(self.brief(), "--lane", "sdk", env=env)
        self.assertEqual(code, 0, (out, err))
        self.assertNotIn(fake_key(), out + err)

    def test_the_sdk_lane_without_any_key_is_refused(self):
        self.config()
        env = dict(ENV)
        del env["ANTHROPIC_API_KEY"]
        code, out, _ = self.plan(self.brief(), "--lane", "sdk", env=env)
        self.assertEqual(code, 1)
        self.assertIn("ANTHROPIC_API_KEY", out)

    def test_a_budget_above_the_cap_is_refused(self):
        self.config(cap=5.0)
        code, out, _ = self.plan(self.brief(), "--lane", "provider:openai", "--model", "gpt-5", "--max-cost", "50")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*50.*5")

    def test_a_billed_lane_without_any_cap_is_refused(self):
        self.config(cap=None)
        code, out, _ = self.plan(self.brief(), "--lane", "sdk")
        self.assertEqual(code, 1)
        self.assertIn("max_cost_usd_per_task", out)
        code, out, _ = self.plan(self.brief("beta"), "--lane", "sdk", "--max-cost", "2")
        self.assertEqual(code, 0, out)

    def test_an_unpriced_model_refuses_the_paid_lane_unless_allowed(self):
        self.config()
        code, out, _ = self.plan(self.brief(agent="searcher"), "--lane", "provider:openai", "--model", "mystery-1")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*no verified price.*mystery-1")
        code, out, _ = self.plan(self.brief("beta", "searcher"), "--lane", "provider:openai", "--model", "mystery-1", "--allow-unpriced")
        self.assertIn(code, (0, 2), out)
        self.assertIn("WARN", out)

    def test_a_provider_lane_needs_a_model(self):
        self.config()
        code, out, _ = self.plan(self.brief(), "--lane", "provider:openai")
        self.assertEqual(code, 1)
        self.assertIn("--model", out)

    def test_an_implement_brief_on_a_tool_less_lane_is_refused_unless_report_only(self):
        self.config()
        brief = self.brief(agent="implementer")
        code, out, _ = self.plan(brief, "--lane", "provider:openai", "--model", "gpt-5")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED.*implement.*tools")
        code, out, _ = self.plan(brief, "--lane", "provider:openai", "--model", "gpt-5", "--report-only")
        self.assertEqual(code, 0, out)

    def test_a_lookup_brief_runs_on_a_provider_lane(self):
        self.config()
        code, out, _ = self.plan(self.brief(agent="searcher"), "--lane", "provider:gemini", "--model", "gemini-2.5-flash")
        self.assertEqual(code, 0, out)

    def test_a_brief_that_fails_its_lint_is_refused(self):
        self.config()
        brief = self.new_brief("gamma", "searcher")      # unfilled slots
        code, out, _ = self.plan(brief)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL|REFUSED")

    def test_a_missing_brief_is_a_failure(self):
        self.config()
        code, out, _ = run("dispatch", "plan", "--brief", self.root / "nope.brief.md", "--root", self.root, env=ENV)
        self.assertEqual(code, 1)

    def test_json_output_is_the_c20_object_and_carries_the_request(self):
        self.config()
        code, data, _ = self.plan(self.brief(agent="searcher"), json_out=True)
        self.assertEqual((code, data["area"], data["verb"]), (0, "dispatch", "plan"))
        self.assertIn("alpha-", json.dumps(data))

    def test_no_output_or_file_ever_holds_a_key_value(self):
        self.config()
        brief = self.brief(agent="searcher")
        _c, out, err = self.plan(brief, "--lane", "provider:openai", "--model", "gpt-5")
        blob = out + err + "".join(p.read_text(encoding="utf-8", errors="ignore") for p in self.root.rglob("*") if p.is_file())
        for value in ENV.values():
            if "://" not in value:
                self.assertNotIn(value, blob)

    def test_out_and_no_write(self):
        self.config()
        brief = self.brief(agent="searcher")
        target = self.root / "somewhere" / "req.json"
        code, _o, _e = self.plan(brief, "--out", target)
        self.assertEqual(code, 0)
        self.assertTrue(target.is_file())
        code, out, _ = self.plan(self.brief("beta", "searcher"), "--no-write")
        self.assertEqual(code, 0)
        self.assertFalse((brief.parent / "beta-2026-10-10.dispatch-request.json").exists())


class RequestContract(unittest.TestCase):
    """Every fixture of C30 the contract ships still behaves as its name says, and the plan's requests are among the valid."""

    def test_invalid_request_fixtures_are_rejected_and_valid_ones_pass(self):
        folder = CONTRACTS / "fixtures" / "C30"
        for path in sorted(folder.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            problems = c30_problems(doc)
            if path.name.startswith("valid-"):
                self.assertEqual(problems, [], path.name)
            else:
                self.assertTrue(problems, path.name)


if __name__ == "__main__":
    unittest.main()
