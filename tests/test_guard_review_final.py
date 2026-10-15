"""Final re-check findings: F-33 (headless claude with a model name that contains `claude`), the rule-table regression guard,
F-34 (two brief paths joined by a comma), F-35 (a copy into an existing folder whose name has a dot)."""
import json
import pathlib
import tempfile
import time
import unittest

import test_guard_automation as automation_cases
import test_guard_review as review_cases
from test_guard_common import GuardCase, isolated_env, pre

from batuta_lib.areas import guard
from batuta_lib.guards import require_brief

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "batuta" / "contracts" / "fixtures" / "C02"
SHA = "a" * 64


def handler(name, payload):
    return guard.HOOKS[f"guard-{name}"](payload)


HEADLESS = [
    'claude --model claude-sonnet-4-5 -p "x"',
    'claude --model claude-opus-4-1 --print "x"',
    'claude --model claude-haiku-4-5 --max-turns 3 -p "do it"',
    'claude --append-system-prompt "you are claude" -p x',
    "claude --model claude-sonnet-4-5 --output-format json -p x",
    '/usr/local/bin/claude --model claude-sonnet-4-5 -p "x"',
    'C:/tools/claude.exe --model claude-sonnet-4-5 -p "x"',
    'C:\\tools\\claude.cmd --model claude-opus-4-1 --print "x"',
    '"claude" --model claude-sonnet-4-5 -p x',
    "'claude.exe' --model claude-sonnet-4-5 -p x",
    "sudo claude --model claude-sonnet-4-5 -p x",
    "env FOO=1 claude --model claude-sonnet-4-5 -p x",
    "FOO=1 claude --model claude-sonnet-4-5 -p x",
    "nohup claude --model claude-sonnet-4-5 -p x",
    "cat prompt.txt | claude --model claude-sonnet-4-5 -p",
    "true && claude --model claude-sonnet-4-5 -p x",
    "echo ok; claude --model claude-sonnet-4-5 -p x",
    "(claude --model claude-sonnet-4-5 -p x)",
    "bash -c 'claude --model claude-sonnet-4-5 -p x'",
    'sh -c "claude --model claude-opus-4-1 --print x"',
    "cmd /c claude --model claude-sonnet-4-5 -p x",
    "pwsh -c claude --model claude-sonnet-4-5 -p x",
    'powershell -Command "claude --model claude-sonnet-4-5 -p x"',
    "echo $(claude --model claude-sonnet-4-5 -p x)",
    "claude --model claude-sonnet-4-5 \\\n  -p x",
    "claude --model claude-sonnet-4-5 --dangerously-skip-permissions",
]
HEADLESS_POWERSHELL = [
    'claude --model claude-sonnet-4-5 -p "x"',
    '& claude --model claude-opus-4-1 --print "x"',
    '& "C:\\tools\\claude.exe" --model claude-sonnet-4-5 -p x',
    '$r = claude --model claude-sonnet-4-5 -p x',
    '$null = & claude.cmd --model claude-opus-4-1 --print x',
    "Start-Process claude -ArgumentList '--model claude-sonnet-4-5 -p x'",
    "if ($true) { claude --model claude-sonnet-4-5 -p x }",
]
HEADLESS_ALLOWED = [
    "claude --model claude-sonnet-4-5",
    "claude --version",
    "claude mcp list",
    "claude --model claude-opus-4-1 mcp add x",
    'echo "run claude -p later"',
    "git commit -m 'document claude --model claude-sonnet-4-5 -p'",
    "grep -rn 'run claude' docs",
    "cat claude-notes.md",
    "ls ~/.claude",
    "python tools/claude_helper.py -p x",
]


class HeadlessClaudeModelNames(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)

    def test_a_model_name_that_contains_claude_does_not_hide_the_flag(self):
        for tool in ("Bash", "Monitor"):
            for command in HEADLESS:
                with self.subTest(tool=tool, command=command):
                    self.denies(handler("automation", pre(tool, command=command)), "headless", msg=f"expected deny: {command}")

    def test_powershell_spellings(self):
        for command in HEADLESS_POWERSHELL:
            with self.subTest(command=command):
                self.denies(handler("automation", pre("PowerShell", command=command)), "headless", msg=command)

    def test_the_word_claude_in_an_argument_or_a_name_is_not_a_command(self):
        for command in HEADLESS_ALLOWED:
            with self.subTest(command=command):
                self.allows(handler("automation", pre("Bash", command=command)), command)

    def test_the_rule_is_fast_on_a_hostile_input_with_model_names(self):
        for text in ("claude --model claude-x " * 2200, "(claude -x " * 4500, "; claude --model claude-y " * 2000,
                     "claude " * 7000, "claude-sonnet-4-5 -p " * 2500):
            start = time.perf_counter()
            handler("automation", pre("Bash", command=text[:50000]))
            self.assertLess(time.perf_counter() - start, 2.0)


class RuleTableRegression(GuardCase):
    """The rule table at 4f7d63b (82 cases of the first table and 38 of the review table) must never lose a case to a
    performance rewrite: every case is still denied, and the table has not shrunk."""

    FIRST = ("SCHEDULED", "RUN_KEYS", "STARTUP", "SERVICES", "WMI", "WSL", "LINUX", "HEADLESS", "DETACH", "LOOPS", "OBFUSCATED")

    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)

    def cases(self):
        first = [c for name in self.FIRST for c in getattr(automation_cases, name)]
        return first, list(review_cases.F10Spellings.BLOCKED)

    def test_the_tables_have_not_shrunk(self):
        first, review = self.cases()
        self.assertGreaterEqual(len(first), 82)
        self.assertGreaterEqual(len(review), 38)

    def test_every_case_of_the_table_is_still_denied(self):
        first, review = self.cases()
        for command in first + review:
            with self.subTest(command=command[:80]):
                self.denies(handler("automation", pre("Bash", command=command)), msg=command)

    def test_every_allowed_case_is_still_allowed(self):
        self.assertGreaterEqual(len(automation_cases.ALLOWED), 25)
        for command in automation_cases.ALLOWED:
            with self.subTest(command=command[:80]):
                self.allows(handler("automation", pre("Bash", command=command)), command)


class BriefPathsJoinedByAComma(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        self.good = self.root / "ok.brief.md"
        self.good.write_text((FIXTURES / "valid-implement-from-delegation-new.md").read_text(encoding="utf-8"), encoding="utf-8")
        self.bad = self.root / "bad.brief.md"
        self.bad.write_text((FIXTURES / "invalid-no-deliverable-line.md").read_text(encoding="utf-8"), encoding="utf-8")

    def launch(self, prompt):
        return pre("Agent", self.root, subagent_type="implementer", prompt=prompt, description="x")

    def test_every_path_of_a_field_is_found(self):
        self.assertEqual(require_brief.brief_paths("a.brief.md,b.brief.md"), ["a.brief.md", "b.brief.md"])
        self.assertEqual(require_brief.brief_paths("/x/a.brief.md,/y/b.brief.md;/z/c.brief.md"),
                         ["/x/a.brief.md", "/y/b.brief.md", "/z/c.brief.md"])
        self.assertEqual(require_brief.brief_paths("briefs=/x/a.brief.md,/y/b.brief.md"), ["/x/a.brief.md", "/y/b.brief.md"])
        self.assertEqual(require_brief.brief_paths("C:/w/a.brief.md,D:/w/b.brief.md"), ["C:/w/a.brief.md", "D:/w/b.brief.md"])

    def test_every_path_is_validated(self):
        self.denies(handler("require-brief", self.launch(f"{self.good.as_posix()},{self.bad.as_posix()}")), "C02")
        self.denies(handler("require-brief", self.launch(f"{self.bad.as_posix()},{self.good.as_posix()}")), "C02")
        self.denies(handler("require-brief", self.launch(f"{self.good.as_posix()},{self.root.as_posix()}/missing.brief.md")),
                    "not found")
        self.allows(handler("require-brief", self.launch(f"{self.good.as_posix()},{self.good.as_posix()}")))


class CopyIntoADottedFolder(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        (self.root / "tests" / "v1.2").mkdir(parents=True)
        (self.root / "tests" / "v1.2" / "test_a.py").write_text("x\n", encoding="utf-8")
        (self.root / ".batuta").mkdir()
        (self.root / ".batuta" / "test-locks.json").write_text(json.dumps({"contract_version": "1.0", "entries": [
            {"path": "tests/v1.2/test_a.py", "sha256": SHA, "task_id": "T-001", "req_ids": ["REQ-A-001"],
             "locked_commit": "abc", "locked_at": "2026-10-13T10:00:00Z"}]}), encoding="utf-8")

    def sh(self, command, tool="Bash"):
        return pre(tool, self.root, command=command)

    def test_an_existing_dotted_folder_receives_the_copy_under_the_source_name(self):
        for command in ("cp /tmp/test_a.py tests/v1.2", "cp /tmp/test_a.py tests/v1.2/", "install /tmp/test_a.py tests/v1.2",
                        "mv /tmp/test_a.py tests/v1.2", "rsync -a /tmp/test_a.py tests/v1.2"):
            with self.subTest(command=command):
                self.denies(handler("locked-tests", self.sh(command)), msg=command)
        for command in ("Copy-Item C:\\tmp\\test_a.py tests\\v1.2", "Move-Item C:\\tmp\\test_a.py tests\\v1.2"):
            with self.subTest(command=command):
                self.denies(handler("locked-tests", self.sh(command, "PowerShell")), msg=command)

    def test_a_dotted_destination_that_does_not_exist_is_a_file(self):
        self.allows(handler("locked-tests", self.sh("cp /tmp/test_a.py tests/v2.0")))
        self.allows(handler("locked-tests", self.sh("cp /tmp/other.py tests/v1.2")))   # lands as tests/v1.2/other.py: not locked
        self.allows(handler("locked-tests", self.sh("cp /tmp/test_a.py notes.md")))

    def test_a_trailing_separator_means_a_folder_even_when_it_does_not_exist(self):
        (self.root / "tests" / "v3.0").mkdir()
        (self.root / "tests" / "v3.0" / "test_b.py").write_text("y\n", encoding="utf-8")
        data = json.loads((self.root / ".batuta" / "test-locks.json").read_text(encoding="utf-8"))
        data["entries"].append({"path": "tests/v9.9/test_c.py", "sha256": SHA, "task_id": "T-002", "req_ids": ["REQ-A-001"],
                                "locked_commit": "abc", "locked_at": "2026-10-13T10:00:00Z"})
        (self.root / ".batuta" / "test-locks.json").write_text(json.dumps(data), encoding="utf-8")
        self.denies(handler("locked-tests", self.sh("cp /tmp/test_c.py tests/v9.9/")))


if __name__ == "__main__":
    unittest.main()
