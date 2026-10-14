"""Guard `guard-approvals`: an agent never writes under an `approvals/` folder of a spec (C06 records)."""
import pathlib
import tempfile
import unittest

from test_guard_common import GuardCase, bash, isolated_env, pre, reason_of

from batuta_lib.areas import guard


def handler(payload):
    return guard.HOOKS["guard-approvals"](payload)


class ApprovalsGuard(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)

    BLOCKED_PATHS = [
        "specs/001-guards/approvals/001-guards.json",
        "specs/012-x/approvals/approval.json",
        "docs/specs/003-y/approvals/a.json",
        "./specs/001-guards/approvals/a.json",
        "specs\\001-guards\\approvals\\a.json",
        "C:/work/proj/specs/001-guards/approvals/a.json",
        "SPECS/001-GUARDS/APPROVALS/A.JSON",
        "specs/001-guards/approvals",
        "specs/001-guards/approvals/nested/deep/a.json",
    ]
    ALLOWED_PATHS = [
        "specs/001-guards/spec.md",
        "docs/approvals/process.md",
        "src/approvals/handler.py",
        "specs/001-guards/approvals-notes.md",
        "approvals/readme.md",
    ]

    def test_edit_and_write_tools(self):
        for tool, extra in (("Edit", {"old_string": "a", "new_string": "b"}), ("Write", {"content": "x"}),
                            ("MultiEdit", {"edits": []}), ("NotebookEdit", {"new_source": "x"})):
            for path in self.BLOCKED_PATHS:
                with self.subTest(tool=tool, path=path):
                    self.denies(handler(pre(tool, file_path=path, **extra)), "approval")
        for path in self.ALLOWED_PATHS:
            with self.subTest(allowed=path):
                self.allows(handler(pre("Write", file_path=path, content="x")))

    def test_reading_an_approval_is_allowed(self):
        self.allows(handler(pre("Read", file_path="specs/001-guards/approvals/a.json")))

    SHELL_BLOCKED = [
        "echo {} > specs/001-guards/approvals/a.json",
        "echo {} >> specs/001-guards/approvals/a.json",
        "tee specs/001-guards/approvals/a.json",
        "cp x.json specs/001-guards/approvals/a.json",
        "mv x.json specs/001-guards/approvals/",
        "rm specs/001-guards/approvals/a.json",
        "rm -rf specs/001-guards/approvals",
        "mkdir specs/001-guards/approvals",
        "touch specs/001-guards/approvals/a.json",
        "Set-Content specs\\001-guards\\approvals\\a.json '{}'",
        "Out-File -FilePath specs/001-guards/approvals/a.json",
        "New-Item -Path specs/001-guards/approvals/a.json -Force",
        "python -c \"open('specs/001-guards/approvals/a.json','w').write('{}')\"",
        "bash -c 'echo {} > specs/001-guards/approvals/a.json'",
        "echo ok && echo {} > specs/001-guards/approvals/a.json",
        "cd specs/001-guards/approvals && echo {} > a.json",
        "sed -i s/a/b/ specs/001-guards/approvals/a.json",
    ]
    SHELL_ALLOWED = [
        "cat specs/001-guards/approvals/a.json",
        "ls specs/001-guards/approvals",
        "git diff specs/001-guards/approvals/a.json",
        "echo x > specs/001-guards/spec.md",
        "python -m unittest",
        "echo approvals > notes.txt",
        "cp specs/001-guards/approvals/a.json /tmp/a.json",
    ]

    def test_shell_writes(self):
        self.table(handler, self.SHELL_BLOCKED, self.SHELL_ALLOWED)

    def test_the_typed_phrase_is_never_written_by_an_agent(self):
        result = handler(pre("Write", file_path="specs/001-guards/approvals/a.json", content="x"))
        reason = reason_of(result)
        self.assertIn("approve <spec id> <first 12 hex", reason)
        self.assertIn("human", reason.lower())

    def test_the_approve_command_is_denied_to_an_agent(self):
        for command in ("python plugins/batuta/scripts/batuta.py spec approve 001-guards --apply",
                        "python batuta.py spec approve 001-guards --phrase 'approve 001-guards abcdef012345' --apply",
                        "batuta spec approve 001-guards --apply"):
            with self.subTest(command=command):
                self.denies(handler(bash(command)), "human")

    def test_other_spec_commands_are_allowed(self):
        self.allows(handler(bash("python batuta.py spec show 001-guards")))
        self.allows(handler(bash("python batuta.py spec lint 001-guards --apply")))

    def test_no_approvals_folder_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.allows(handler(bash("echo x > a.txt", pathlib.Path(tmp))))
        self.assertIn("no approvals folder", guard.explain("approvals").lower())

    def test_odd_payloads_are_allowed(self):
        for payload in ({}, {"tool_name": "Write"}, {"tool_name": "Write", "tool_input": {"file_path": 5}},
                        {"tool_name": "Bash", "tool_input": {}}):
            self.allows(handler(payload))


if __name__ == "__main__":
    unittest.main()
