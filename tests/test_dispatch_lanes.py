"""dispatch lanes: the subagent launch spec, the reply and patch handling of provider lanes, the checks of a brief and the
PreToolUse policy of the sdk lane (unit U13, D2)."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dispatch_support import fake_key  # noqa: E402

from batuta_lib.dispatch import lanes  # noqa: E402

REQUEST = {"contract_version": "1.0", "kind": "request", "run_id": "alpha-2026-10-10", "brief": ".batuta/delegation/alpha-2026-10-10.brief.md",
           "report": ".batuta/delegation/alpha-2026-10-10.report.md", "lane": "subagent", "role": "implementer", "model": "sonnet",
           "write_scope": ["src/area/"], "max_turns": 20, "timeout_s": 3600}


class SubagentSpec(unittest.TestCase):
    def test_the_spec_names_the_agent_the_model_and_the_brief_and_runs_in_background(self):
        spec = lanes.subagent_spec(REQUEST)
        self.assertEqual((spec["subagent_type"], spec["model"], spec["run_in_background"]), ("implementer", "sonnet", True))
        self.assertIn(REQUEST["brief"], spec["prompt"])
        self.assertIn(REQUEST["report"], spec["prompt"])

    def test_the_spec_says_it_was_not_launched(self):
        spec = lanes.subagent_spec(REQUEST)
        self.assertIs(spec["launched"], False)
        self.assertIn("main session", spec["note"])


class Reply(unittest.TestCase):
    DIFF = "diff --git a/src/area/a.py b/src/area/a.py\n--- a/src/area/a.py\n+++ b/src/area/a.py\n@@ -1 +1 @@\n-x\n+y\n"

    def test_split_reply_takes_diff_fences_out_of_the_report(self):
        report, patch = lanes.split_reply(f"# Report\n\ntext\n\n```diff\n{self.DIFF}```\n\n## Completeness\n")
        self.assertNotIn("diff --git", report)
        self.assertIn("## Completeness", report)
        self.assertEqual(patch, self.DIFF)

    def test_a_reply_without_a_diff_has_an_empty_patch(self):
        self.assertEqual(lanes.split_reply("# Report\n")[1], "")

    def test_several_diff_blocks_are_joined(self):
        report, patch = lanes.split_reply(f"```diff\n{self.DIFF}```\ntext\n```diff\n{self.DIFF.replace('a.py', 'b.py')}```\n")
        self.assertEqual(patch.count("diff --git"), 2)

    def test_patch_files_lists_every_path_once_and_ignores_dev_null(self):
        patch = self.DIFF + "diff --git a/new.txt b/new.txt\nnew file mode 100644\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+a\n"
        self.assertEqual(lanes.patch_files(patch), ["src/area/a.py", "new.txt"])

    def test_patch_files_sees_renames_and_quoted_paths(self):
        patch = "diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n"
        self.assertEqual(sorted(lanes.patch_files(patch)), ["new.py", "old.py"])

    def test_scope_violations(self):
        scope = ["src/area/", "tests/area/test_x.py", "docs/*.md"]
        ok = ["src/area/a.py", "src/area/deep/b.py", "tests/area/test_x.py", "docs/guide.md"]
        self.assertEqual(lanes.scope_violations(ok, scope), [])
        bad = ["src/other/a.py", "../escape.py", "/abs/path.py", "src/area/../../etc.py", "tests/area/test_y.py", "docs/sub/g.md",
               "src/areaX/a.py", ".git/config"]
        self.assertEqual(lanes.scope_violations(bad, scope), bad)

    def test_an_empty_scope_allows_no_file(self):
        self.assertEqual(lanes.scope_violations(["a.py"], []), ["a.py"])


class Checks(unittest.TestCase):
    def test_extract_checks_reads_the_backticked_command_of_each_item(self):
        text = "## Goal\nx\n\n## Checks\n- C1: `python -m unittest` passes (all suites)\n- C2: `git status --short` is clean\n- C3: the report exists\n\n## Report layout\n- C9: `no`\n"
        self.assertEqual(lanes.extract_checks(text), [("C1", "python -m unittest"), ("C2", "git status --short")])

    def test_a_brief_without_checks_has_none(self):
        self.assertEqual(lanes.extract_checks("## Goal\nx\n"), [])


def run(coro):
    return asyncio.run(coro)


class Policy(unittest.TestCase):
    def policy(self, results, fail_closed=(), ids=("guard-secrets", "guard-destructive")):
        self.calls = []

        def launcher(guard_id, payload_text, env):
            self.calls.append((guard_id, json.loads(payload_text), env))
            return results[guard_id] if isinstance(results, dict) else results.pop(0)

        return lanes.make_policy(ids, launcher, cwd="/work/repo", fail_closed=set(fail_closed), env={"PATH": "x", "ANTHROPIC_API_KEY": fake_key()})

    def decide(self, policy, tool="Bash", tool_input=None):
        return run(policy({"tool_name": tool, "tool_input": tool_input or {"command": "ls"}, "hook_event_name": "PreToolUse"}, "t", None))

    def test_all_guards_allow_returns_an_empty_decision(self):
        out = self.decide(self.policy({"guard-secrets": (0, "", ""), "guard-destructive": (0, "", "")}))
        self.assertEqual(out, {})

    def test_each_guard_gets_the_c16_payload_with_the_cwd(self):
        self.decide(self.policy({"guard-secrets": (0, "", ""), "guard-destructive": (0, "", "")}))
        self.assertEqual([c[0] for c in self.calls], ["guard-secrets", "guard-destructive"])
        payload = self.calls[0][1]
        self.assertEqual((payload["hook_event_name"], payload["tool_name"], payload["cwd"]), ("PreToolUse", "Bash", "/work/repo"))
        self.assertEqual(payload["tool_input"], {"command": "ls"})

    def test_the_guards_do_not_inherit_the_api_key(self):
        self.decide(self.policy({"guard-secrets": (0, "", ""), "guard-destructive": (0, "", "")}))
        self.assertNotIn("ANTHROPIC_API_KEY", self.calls[0][2])

    def test_exit_2_denies_with_the_guard_message(self):
        out = self.decide(self.policy({"guard-secrets": (2, "", "no secrets here\n"), "guard-destructive": (0, "", "")}))
        spec = out["hookSpecificOutput"]
        self.assertEqual((spec["hookEventName"], spec["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn("no secrets here", spec["permissionDecisionReason"])

    def test_a_deny_is_the_answer_but_every_guard_still_runs(self):
        out = self.decide(self.policy({"guard-secrets": (2, "", "x"), "guard-destructive": (0, "", "")}))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_a_guard_decision_on_stdout_is_passed_through_exactly(self):
        decision = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "r"}}
        out = self.decide(self.policy({"guard-secrets": (0, json.dumps(decision), ""), "guard-destructive": (0, "", "")}))
        self.assertEqual(out, decision)

    def test_exit_1_is_a_non_blocking_error_unless_the_guard_fails_closed(self):
        open_ = self.decide(self.policy({"guard-secrets": (1, "", "boom"), "guard-destructive": (0, "", "")}))
        self.assertEqual(open_, {})
        closed = self.decide(self.policy({"guard-secrets": (1, "", "boom"), "guard-destructive": (0, "", "")}, fail_closed=["guard-secrets"]))
        self.assertEqual(closed["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_an_unreadable_launcher_answer_follows_the_failure_mode(self):
        out = self.decide(self.policy({"guard-secrets": (0, "not json", ""), "guard-destructive": (0, "", "")}, fail_closed=["guard-secrets"]))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_fail_closed_ids_come_from_the_hooks_registry(self):
        import tempfile
        hooks = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python", "args": ["-I", "hook.py", "guard-secrets"], "onFailure": "block"},
            {"type": "command", "command": "python", "args": ["-I", "hook.py", "guard-automation"]}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "python", "args": ["hook.py", "report-check"], "onFailure": "continue"}]}]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hooks.json"
            path.write_text(json.dumps(hooks), encoding="utf-8")
            ids, closed = lanes.guard_ids_from_registry(path)
        self.assertEqual((ids, closed), (["guard-secrets", "guard-automation"], {"guard-secrets"}))

    def test_without_a_registry_the_default_guards_apply(self):
        ids, closed = lanes.guard_ids_from_registry(Path("no-such-hooks.json"))
        self.assertEqual(ids, lanes.default_guards())
        self.assertEqual(closed, set())
        self.assertIn("guard-secrets", ids)


if __name__ == "__main__":
    unittest.main()
