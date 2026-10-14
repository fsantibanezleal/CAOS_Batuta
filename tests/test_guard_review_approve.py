"""U3 review F-01 and F-02: an agent never runs the approval commands and never forges an approvals/ record."""
import pathlib
import tempfile
import unittest

from test_guard_common import GuardCase, bash, isolated_env, pre, reason_of

from batuta_lib.areas import guard


def handler(payload):
    return guard.HOOKS["guard-approvals"](payload)


DENIED = [
    "python plugins/batuta/scripts/batuta.py spec approve 001-guards --apply",
    "python batuta.py spec approve 001-guards",
    "python batuta.py spec approve 001-guards --phrase 'approve 001-guards abcdef012345' --apply",
    "batuta spec approve 001-guards --apply",
    "py -3 batuta.py spec approve 001-guards --apply",
    "py -3.12 plugins/batuta/scripts/batuta.py spec approve 001-guards",
    "python3 -I -B scripts/batuta.py spec approve x",
    "python -m batuta spec approve 001-guards --apply",
    "./batuta.py spec approve 001-guards",
    "C:/work/plugins/batuta/scripts/batuta.py spec approve 001-guards",
    "python C:\\work\\batuta\\scripts\\batuta.py spec   approve 001-guards",
    "python batuta.py --json spec approve 001-guards",
    "python batuta.py --config x.json spec approve 001-guards",
    "python batuta.py spec hook-approval",
    "python batuta.py spec hook-approval --apply",
    "echo '{}' | python batuta.py spec hook-approval",
    "python plugins/batuta/scripts/hook.py spec-approval",
    "echo '{}' | python scripts/hook.py spec-approval",
    "py -3 hook.py spec-approval",
    "cd plugins/batuta && python scripts/batuta.py spec approve 001-guards --apply",
    "true && python batuta.py spec approve 001-guards",
    "echo ok; python batuta.py spec approve 001-guards",
    "python batuta.py spec approve 001-guards | cat",
    "bash -c 'python batuta.py spec approve 001-guards --apply'",
    "sh -c \"python batuta.py spec approve 001-guards\"",
    "cmd /c python batuta.py spec approve 001-guards",
    "pwsh -c python batuta.py spec approve 001-guards",
    "powershell -Command \"python batuta.py spec approve 001-guards\"",
    "FOO=1 python batuta.py spec approve 001-guards",
    "echo $(python batuta.py spec approve 001-guards)",
    "PYTHONPATH=. python -B batuta.py SPEC APPROVE 001-guards",
    "python batuta.py spec \\\napprove 001-guards",
    "python batuta\u200b.py spec approve 001-guards",
    "python \uff42\uff41\uff54\uff55\uff54\uff41.py spec approve 001-guards",
    "python batuta.py sp^ec appr^ove 001-guards",
]
DENIED_POWERSHELL = [
    "$r = python batuta.py spec approve 001-guards --apply",
    "$null = & python plugins/batuta/scripts/batuta.py spec approve 001-guards",
    "[string]$x = python batuta.py spec hook-approval",
    "if ($true) { python batuta.py spec approve 001-guards }",
    "python plugins\\batuta\\scripts\\batuta.py spec approve 001-guards",
]
ALLOWED = [
    "python batuta.py spec show 001-guards",
    "python batuta.py spec freeze --check 001-guards",
    "python batuta.py spec lint 001-guards --apply",
    "python batuta.py spec new 001-guards",
    "python batuta.py contract validate C06 specs/001-guards/approvals/a.json",
    "grep -rn approve docs",
    "echo spec approve is for humans",
    "git log --oneline",
    "python run_tests.py spec approve",
]


class ApprovalCommands(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)

    def test_every_spelling_of_the_approval_commands_is_denied(self):
        for tool in ("Bash", "Monitor", "SomeFutureShell"):
            for command in DENIED:
                with self.subTest(tool=tool, command=command):
                    self.denies(handler(pre(tool, command=command)), msg=f"expected deny: {command!r}")

    def test_powershell_spellings_are_denied(self):
        for command in DENIED_POWERSHELL:
            with self.subTest(command=command):
                self.denies(handler(pre("PowerShell", command=command)), msg=command)

    def test_the_reason_says_the_approval_belongs_to_the_human(self):
        reason = reason_of(handler(bash("python batuta.py spec approve 001-guards --apply")))
        self.assertIn("human", reason.lower())
        self.assertIn("type", reason.lower())
        self.assertIn("own terminal", reason)
        self.assertIn("approve <spec id> <first 12 hex", reason)

    def test_show_and_freeze_check_stay_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.allows(handler(bash(command)), command)

    def test_the_decision_is_a_deny_not_an_ask(self):
        self.assertEqual(handler(bash("python batuta.py spec approve 001-guards --apply"))["output"]
                         ["hookSpecificOutput"]["permissionDecision"], "deny")


class ForgedRecords(GuardCase):
    """The U3 waiver of F-02 rests on this: a forged approvals/ record is denied through every writing tool."""

    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        (self.root / "specs" / "001-guards" / "approvals").mkdir(parents=True)
        self.record = "specs/001-guards/approvals/001-guards.json"
        self.body = '{"contract_version": "1.0", "spec_id": "001-guards"}'

    def test_write_edit_multiedit_and_notebookedit_are_denied(self):
        for tool, extra in (("Write", {"content": self.body}), ("Edit", {"old_string": "a", "new_string": "b"}),
                            ("MultiEdit", {"edits": [{"old_string": "a", "new_string": "b"}]}),
                            ("NotebookEdit", {"new_source": "x"})):
            for path in (self.record, str(self.root / self.record), self.record.replace("/", "\\")):
                with self.subTest(tool=tool, path=path):
                    self.denies(handler(pre(tool, self.root, file_path=path, **extra)), "approval")

    def test_shell_redirects_and_writers_are_denied(self):
        for command in (f"echo '{self.body}' > {self.record}", f"echo '{self.body}' >> {self.record}",
                        f"printf '%s' '{self.body}' | tee {self.record}", f"cp /tmp/forged.json {self.record}",
                        f"cat forged.json > {self.record}", f"cd specs/001-guards/approvals && echo '{self.body}' > 001-guards.json",
                        f"bash -c \"echo '{self.body}' > {self.record}\"",
                        f"python -c \"open('{self.record}','w').write('{{}}')\""):
            with self.subTest(command=command):
                self.denies(handler(pre("Bash", self.root, command=command)), msg=command)
        self.denies(handler(pre("PowerShell", self.root, command=f"Set-Content -Path {self.record} -Value '{self.body}'")))
        self.denies(handler(pre("Monitor", self.root, command=f"echo x > {self.record}")))


if __name__ == "__main__":
    unittest.main()
