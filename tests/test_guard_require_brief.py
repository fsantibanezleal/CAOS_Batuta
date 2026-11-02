"""Guard `guard-require-brief`: an Agent launch must name a brief that satisfies C02 (ask or deny per config)."""
import pathlib
import tempfile
import unittest

from test_guard_common import GuardCase, isolated_env, pre, reason_of, write_json, write_config

from batuta_lib.areas import guard

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "batuta" / "contracts" / "fixtures" / "C02"


def handler(payload):
    return guard.HOOKS["guard-require-brief"](payload)


def launch(prompt, agent="implementer", tool="Agent", cwd=None):
    return pre(tool, cwd, subagent_type=agent, prompt=prompt, description="x")


class RequireBrief(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / ".git").mkdir()
        self.good = self.root / "ok.brief.md"
        self.good.write_text((FIXTURES / "valid-implement-from-delegation-new.md").read_text(encoding="utf-8"),
                             encoding="utf-8")
        self.bad = self.root / "bad.brief.md"
        self.bad.write_text((FIXTURES / "invalid-no-deliverable-line.md").read_text(encoding="utf-8"), encoding="utf-8")

    def config(self, mode):
        write_config(self.root, guards={"require_brief": mode})

    def test_a_launch_naming_a_valid_brief_is_allowed(self):
        for tool in ("Agent", "Task"):
            self.allows(handler(launch(f"Your brief is {self.good.as_posix()}. Follow it.", tool=tool, cwd=self.root)))

    def test_a_relative_brief_path_resolves_against_the_cwd(self):
        self.allows(handler(launch("Your brief is ok.brief.md", cwd=self.root)))

    def test_a_launch_without_a_brief_path_is_denied_by_default(self):
        self.denies(handler(launch("please implement the thing", cwd=self.root)), "brief")

    def test_a_missing_brief_file_is_denied(self):
        self.denies(handler(launch("brief: /nowhere/x.brief.md", cwd=self.root)), "not found")

    def test_an_invalid_brief_is_denied_with_the_failing_rule(self):
        result = handler(launch(f"brief: {self.bad.as_posix()}", cwd=self.root))
        self.denies(result, "C02")

    def test_every_named_brief_must_pass(self):
        prompt = f"{self.good.as_posix()} and {self.bad.as_posix()}"
        self.denies(handler(launch(prompt, cwd=self.root)))

    def test_a_quick_agent_may_go_without_a_brief_with_the_none_line(self):
        for agent in ("searcher", "runner"):
            self.allows(handler(launch("find x\n\nBRIEF: none", agent=agent, cwd=self.root)))

    def test_the_none_line_does_not_help_an_implementation_agent(self):
        self.denies(handler(launch("do x\n\nBRIEF: none", agent="implementer", cwd=self.root)))

    def test_a_quick_agent_without_the_none_line_is_denied(self):
        self.denies(handler(launch("find x", agent="searcher", cwd=self.root)))

    def test_config_can_ask_instead_of_deny(self):
        self.config("ask")
        self.asks(handler(launch("please implement the thing", cwd=self.root)), "brief")
        self.asks(handler(launch(f"brief: {self.bad.as_posix()}", cwd=self.root)))
        self.allows(handler(launch(f"brief: {self.good.as_posix()}", cwd=self.root)))

    def test_config_can_turn_the_guard_off(self):
        self.config("off")
        self.allows(handler(launch("please implement the thing", cwd=self.root)))

    def test_an_unknown_mode_in_config_falls_back_to_deny(self):
        self.config("shrug")
        self.denies(handler(launch("please implement the thing", cwd=self.root)))

    def test_other_tools_are_never_inspected(self):
        self.allows(handler(pre("Bash", self.root, command="ls")))
        self.allows(handler(pre("Read", self.root, file_path="x")))

    def test_odd_payloads_are_allowed(self):
        for payload in ({}, {"tool_name": None}, {"tool_name": "Bash", "tool_input": "x"}):
            self.allows(handler(payload))

    def test_a_missing_prompt_on_an_agent_launch_is_denied(self):
        self.denies(handler({"tool_name": "Agent", "tool_input": {"subagent_type": "implementer"}, "cwd": str(self.root)}))

    def test_the_reason_says_how_to_fix_it(self):
        reason = reason_of(handler(launch("do it", cwd=self.root)))
        self.assertIn(".brief.md", reason)


if __name__ == "__main__":
    unittest.main()
