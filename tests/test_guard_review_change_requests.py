"""Plan decision 31 (U4 review): an agent never decides a test change request and never writes a `test-change-requests.md`
table by hand; `tdd change-request new` (it appends only `open` rows) stays allowed."""
import pathlib
import tempfile
import unittest

from test_guard_common import GuardCase, bash, isolated_env, pre, reason_of

from batuta_lib.areas import guard


def approvals(payload):
    return guard.HOOKS["guard-approvals"](payload)


def locked(payload):
    return guard.HOOKS["guard-locked-tests"](payload)


DECIDE = [
    "python plugins/batuta/scripts/batuta.py tdd change-request decide CR-001 --approve",
    "python batuta.py tdd change-request decide CR-001 --reject --apply",
    "batuta tdd change-request decide CR-001",
    "py -3 batuta.py tdd change-request decide CR-001 --approve",
    "python -m batuta tdd change-request decide CR-001",
    "./batuta.py tdd change-request decide CR-001",
    "C:/work/plugins/batuta/scripts/batuta.py tdd change-request decide CR-001",
    "python C:\\work\\batuta\\scripts\\batuta.py tdd   change-request   decide CR-001",
    "python batuta.py --json tdd change-request decide CR-001",
    "python batuta.py --config x.json tdd change-request decide CR-001",
    "cd plugins/batuta && python scripts/batuta.py tdd change-request decide CR-001 --approve",
    "true && python batuta.py tdd change-request decide CR-001",
    "echo ok; python batuta.py tdd change-request decide CR-001",
    "bash -c 'python batuta.py tdd change-request decide CR-001'",
    "cmd /c python batuta.py tdd change-request decide CR-001",
    "pwsh -c python batuta.py tdd change-request decide CR-001",
    "FOO=1 python batuta.py tdd change-request decide CR-001",
    "echo $(python batuta.py tdd change-request decide CR-001)",
    "PYTHONPATH=. python -B batuta.py TDD CHANGE-REQUEST DECIDE CR-001",
    "python batuta.py tdd change-request \\\ndecide CR-001",
    "python batuta\u200b.py tdd change-request decide CR-001",
    "python \uff42\uff41\uff54\uff55\uff54\uff41.py tdd change-request decide CR-001",
    "python batuta.py td^d change-re^quest decide CR-001",
]
DECIDE_POWERSHELL = [
    "$r = python batuta.py tdd change-request decide CR-001 --approve",
    "$null = & python plugins/batuta/scripts/batuta.py tdd change-request decide CR-001",
    "if ($true) { python batuta.py tdd change-request decide CR-001 }",
    "python plugins\\batuta\\scripts\\batuta.py tdd change-request decide CR-001",
]
ALLOWED = [
    "python batuta.py tdd change-request new --test tests/test_a.py --reason x",
    "python plugins/batuta/scripts/batuta.py tdd change-request new",
    "python batuta.py tdd change-request list",
    "python batuta.py tdd change-request show CR-001",
    "python batuta.py tdd lock --apply",
    "python batuta.py spec show 001-guards",
    "echo tdd change-request decide is for humans",
    "grep -rn decide docs",
    "cat specs/f/test-change-requests.md",
]
TABLE = "specs/001-guards/test-change-requests.md"


class DecideIsDenied(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)

    def test_every_spelling_of_decide_is_denied(self):
        for tool in ("Bash", "Monitor"):
            for command in DECIDE:
                with self.subTest(tool=tool, command=command):
                    self.denies(approvals(pre(tool, command=command)), msg=f"expected deny: {command!r}")
        for command in DECIDE_POWERSHELL:
            with self.subTest(command=command):
                self.denies(approvals(pre("PowerShell", command=command)), msg=command)

    def test_the_reason_says_the_decision_belongs_to_the_human(self):
        reason = reason_of(approvals(bash("python batuta.py tdd change-request decide CR-001 --approve")))
        self.assertIn("human", reason.lower())
        self.assertIn("own terminal", reason)
        self.assertIn("change-request new", reason)

    def test_new_and_the_reads_stay_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.allows(approvals(bash(command)), command)


class TableWritesAreDenied(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        (self.root / "specs" / "001-guards").mkdir(parents=True)
        (self.root / TABLE).write_text("| Id |\n", encoding="utf-8")

    def test_every_writing_tool_is_denied(self):
        for tool, extra in (("Write", {"content": "x"}), ("Edit", {"old_string": "a", "new_string": "b"}),
                            ("MultiEdit", {"edits": [{"old_string": "a", "new_string": "b"}]}),
                            ("NotebookEdit", {"new_source": "x"})):
            for path in (TABLE, str(self.root / TABLE), TABLE.replace("/", "\\"), "docs/other/test-change-requests.md",
                         "TEST-CHANGE-REQUESTS.MD", TABLE + "::$DATA"):
                with self.subTest(tool=tool, path=path):
                    self.denies(approvals(pre(tool, self.root, file_path=path, **extra)), "change request")

    def test_shell_writers_links_and_inline_code_are_denied(self):
        for command in (f"echo '| CR-001 | approved |' >> {TABLE}", f"echo x > {TABLE}", f"printf x | tee {TABLE}",
                        f"cp /tmp/forged.md {TABLE}", f"sed -i s/open/approved/ {TABLE}", f"mv forged.md {TABLE}",
                        f"rm {TABLE}", f"ln -s {TABLE} t", f"cmd /c mklink t specs\\001-guards\\test-change-requests.md",
                        f"cd specs/001-guards && echo x >> test-change-requests.md", f"bash -c \"echo x > {TABLE}\"",
                        f"python -c \"open('{TABLE}','a').write('x')\"", "echo x > specs/*/test-change-requests.md",
                        f"cat forged.md > {TABLE}", f"truncate -s 0 {TABLE}"):
            with self.subTest(command=command):
                self.denies(approvals(pre("Bash", self.root, command=command)), msg=command)
        for command in (f"Add-Content -Path {TABLE} -Value x", f"Set-Content {TABLE} x", f"Remove-Item {TABLE}",
                        f"[IO.File]::AppendAllText('{TABLE}', 'x')", f"New-Item -ItemType SymbolicLink -Path t -Target {TABLE}"):
            with self.subTest(command=command):
                self.denies(approvals(pre("PowerShell", self.root, command=command)), msg=command)
        self.denies(approvals(pre("Monitor", self.root, command=f"echo x > {TABLE}")))

    def test_reads_and_other_spec_files_are_allowed(self):
        self.allows(approvals(pre("Read", self.root, file_path=TABLE)))
        self.allows(approvals(pre("Bash", self.root, command=f"cat {TABLE}")))
        self.allows(approvals(pre("Bash", self.root, command=f"cp {TABLE} /tmp/copy.md")))
        self.allows(approvals(pre("Write", self.root, file_path="specs/001-guards/spec.md", content="x")))
        self.allows(approvals(pre("Write", self.root, file_path="docs/test-change-requests-notes.md", content="x")))

    def test_the_locked_test_reason_points_to_the_command_not_to_a_hand_edit(self):
        import json
        (self.root / ".batuta").mkdir()
        (self.root / ".batuta" / "test-locks.json").write_text(json.dumps({"contract_version": "1.0", "entries": [
            {"path": "tests/test_a.py", "sha256": "a" * 64, "task_id": "T-001", "req_ids": ["REQ-A-001"],
             "locked_commit": "abc", "locked_at": "2026-10-13T10:00:00Z"}]}), encoding="utf-8")
        reason = reason_of(locked(pre("Write", self.root, file_path="tests/test_a.py", content="x")))
        self.assertIn("tdd change-request new", reason)
        self.assertIn("test-change-requests.md", reason)
        self.assertNotIn("add a row to", reason)


if __name__ == "__main__":
    unittest.main()
