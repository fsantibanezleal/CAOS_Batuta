"""Guard `guard-locked-tests`: edits, writes and shell writes to the paths of the C07 lock file are denied."""
import json
import pathlib
import tempfile
import unittest

from test_guard_common import GuardCase, bash, isolated_env, pre, reason_of, write_json, write_config

from batuta_lib.areas import guard

SHA = "a" * 64
LOCKED = ["tests/test_alpha.py", "tests/unit/test_beta.py", "web/src/gamma.test.ts"]


def handler(payload):
    return guard.HOOKS["guard-locked-tests"](payload)


def entry(path, task="T-001"):
    return {"path": path, "sha256": SHA, "task_id": task, "req_ids": ["REQ-GUARD-001"],
            "locked_commit": "abc1234", "locked_at": "2026-10-13T10:00:00Z"}


class LockedBase(GuardCase):
    lock_name = ".batuta/test-locks.json"

    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / ".git").mkdir()

    def lock(self, paths=LOCKED, name=None):
        write_json(self.root / (name or self.lock_name),
                   {"contract_version": "1.0", "entries": [entry(p, f"T-{i + 1:03d}") for i, p in enumerate(paths)]})

    def b(self, command):
        return bash(command, self.root)

    def w(self, tool, path, **extra):
        return pre(tool, self.root, file_path=path, **extra)


class EditWriteTools(LockedBase):
    def test_edit_and_write_to_a_locked_path_are_denied(self):
        self.lock()
        for tool, extra in (("Edit", {"old_string": "a", "new_string": "b"}), ("Write", {"content": "x"}),
                            ("MultiEdit", {"edits": []}), ("NotebookEdit", {"new_source": "x"})):
            for path in LOCKED:
                with self.subTest(tool=tool, path=path):
                    self.denies(handler(self.w(tool, path, **extra)), "test-change-requests")

    def test_absolute_windows_and_mixed_case_spellings_are_the_same_path(self):
        self.lock()
        base = str(self.root).replace("\\", "/")
        for path in (f"{base}/tests/test_alpha.py", f"{base}/TESTS/Test_Alpha.py", "./tests/test_alpha.py",
                     "tests\\test_alpha.py", f"{base}\\tests\\unit\\test_beta.py"):
            with self.subTest(path=path):
                self.denies(handler(self.w("Write", path, content="x")))

    def test_paths_that_are_not_locked_are_allowed(self):
        self.lock()
        for path in ("tests/test_other.py", "src/app.py", "tests/test_alpha.py.bak", "docs/tests/test_alpha_notes.md"):
            with self.subTest(path=path):
                self.allows(handler(self.w("Write", path, content="x")))

    def test_reading_a_locked_file_is_allowed(self):
        self.lock()
        self.allows(handler(self.w("Read", "tests/test_alpha.py")))

    def test_the_reason_points_to_the_change_request_table_and_the_row(self):
        self.lock()
        reason = reason_of(handler(self.w("Edit", "tests/test_alpha.py", old_string="a", new_string="b")))
        self.assertIn("specs/<feature>/test-change-requests.md", reason)
        for column in ("Id", "Test path", "Requirement", "Reason", "Proposed change", "Status"):
            self.assertIn(column, reason)
        self.assertIn("tests/test_alpha.py", reason)
        self.assertIn("T-001", reason)

    def test_a_path_outside_the_project_is_never_locked(self):
        self.lock()
        self.allows(handler(self.w("Write", "/elsewhere/tests/test_alpha.py", content="x")))


class ShellWrites(LockedBase):
    BLOCKED = [
        "echo x > tests/test_alpha.py",
        "echo x >> tests/test_alpha.py",
        "echo x>tests/test_alpha.py",
        "cat new.py | tee tests/test_alpha.py",
        "sed -i s/a/b/ tests/test_alpha.py",
        "sed -i.bak 's/a/b/' tests/unit/test_beta.py",
        "perl -pi -e s/a/b/ tests/test_alpha.py",
        "cp new.py tests/test_alpha.py",
        "mv new.py tests/test_alpha.py",
        "mv tests/test_alpha.py old.py",
        "rm tests/test_alpha.py",
        "rm -f ./tests/test_alpha.py",
        "truncate -s 0 tests/test_alpha.py",
        "git checkout -- tests/test_alpha.py",
        "git restore tests/unit/test_beta.py",
        "dd if=x of=tests/test_alpha.py",
        "install -m 644 x tests/test_alpha.py",
        "Set-Content -Path tests/test_alpha.py -Value x",
        "Set-Content tests\\test_alpha.py x",
        "Add-Content tests/test_alpha.py x",
        "'x' | Out-File tests/test_alpha.py",
        "Out-File -FilePath tests/test_alpha.py -InputObject x",
        "Remove-Item tests/test_alpha.py",
        "Remove-Item -Force -Path \"tests\\unit\\test_beta.py\"",
        "Copy-Item new.py tests/test_alpha.py",
        "Move-Item new.py tests/test_alpha.py",
        "[IO.File]::WriteAllText('tests/test_alpha.py', 'x')",
        "python -c \"open('tests/test_alpha.py','w').write('x')\"",
        "python3 -c 'import pathlib; pathlib.Path(\"tests/test_alpha.py\").write_text(\"x\")'",
        "node -e \"require('fs').writeFileSync('web/src/gamma.test.ts','x')\"",
        "echo ok && echo x > tests/test_alpha.py",
        "echo ok; rm tests/test_alpha.py",
        "true || echo x >> tests/test_alpha.py",
        "bash -c 'echo x > tests/test_alpha.py'",
        "sh -c \"rm tests/test_alpha.py\"",
        "pwsh -Command \"Set-Content tests/test_alpha.py x\"",
        "echo $(echo x > tests/test_alpha.py)",
        "echo ok\necho x > tests/test_alpha.py",
        "rm -rf tests",
        "rm -rf tests/",
        "rm -rf tests/unit",
        "Remove-Item -Recurse tests",
        "echo x > TESTS/TEST_ALPHA.PY",
        "echo x > \"$PWD/tests/test_alpha.py\"",
        "cd tests && echo x > test_alpha.py",
    ]
    ALLOWED = [
        "cat tests/test_alpha.py",
        "python -m pytest tests/test_alpha.py",
        "python -m unittest tests.test_alpha",
        "git diff tests/test_alpha.py",
        "git log -- tests/test_alpha.py",
        "grep -n assert tests/test_alpha.py",
        "cp tests/test_alpha.py /tmp/copy.py",
        "Copy-Item tests/test_alpha.py backup/",
        "Get-Content tests/test_alpha.py",
        "echo x > tests/test_other.py",
        "echo x > notes.txt",
        "rm -rf build",
        "sed -n 1,5p tests/test_alpha.py",
        "ls tests",
        "echo 'tests/test_alpha.py is locked' > notes.txt",
        "wc -l tests/test_alpha.py > counts.txt",
    ]

    def test_blocked_spellings(self):
        self.lock()
        for command in self.BLOCKED:
            with self.subTest(command=command):
                self.denies(handler(self.b(command)), "test-change-requests")

    def test_allowed_spellings(self):
        self.lock()
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.allows(handler(self.b(command)), command)

    def test_there_are_at_least_three_cases_each_way(self):
        self.assertGreaterEqual(len(self.BLOCKED), 3)
        self.assertGreaterEqual(len(self.ALLOWED), 3)

    def test_lookalike_characters_in_the_command_are_normalized(self):
        self.lock()
        self.denies(handler(self.b("ｒｍ tests/test_alpha.py")))  # fullwidth "rm"
        self.denies(handler(self.b("echo x > tests/test_alpha​.py")))


class LockFile(LockedBase):
    def test_no_lock_file_allows_and_explains(self):
        self.allows(handler(self.w("Write", "tests/test_alpha.py", content="x")))
        self.allows(handler(self.b("rm tests/test_alpha.py")))
        self.assertIn("no lock file", guard.explain("locked-tests", cwd=self.root).lower())

    def test_an_empty_lock_allows(self):
        self.lock(paths=[])
        self.allows(handler(self.w("Write", "tests/test_alpha.py", content="x")))

    def test_a_malformed_lock_raises_with_the_reason(self):
        for text in ("{not json", json.dumps({"entries": []}),
                     json.dumps({"contract_version": "1.0", "entries": [{"path": "../x", "sha256": SHA, "task_id": "T-001",
                                                                          "req_ids": [], "locked_commit": "a",
                                                                          "locked_at": "2026-10-13T10:00:00Z"}]})):
            with self.subTest(text=text[:30]):
                (self.root / ".batuta").mkdir(exist_ok=True)
                (self.root / ".batuta" / "test-locks.json").write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError) as ctx:
                    handler(self.w("Write", "tests/test_alpha.py", content="x"))
                self.assertIn("test-locks.json", str(ctx.exception))

    def test_the_lock_location_comes_from_config(self):
        write_config(self.root, tdd={"lock_file": "locks/custom.json"})
        self.lock(name="locks/custom.json")
        self.denies(handler(self.w("Write", "tests/test_alpha.py", content="x")))

    def test_the_default_location_is_the_tdd_area_default(self):
        self.lock()
        self.assertTrue((self.root / ".batuta" / "test-locks.json").is_file())
        self.denies(handler(self.w("Write", "tests/test_alpha.py", content="x")))

    def test_a_lock_location_that_escapes_the_project_is_refused(self):
        write_config(self.root, tdd={"lock_file": "../outside.json"})
        with self.assertRaises(ValueError):
            handler(self.w("Write", "tests/test_alpha.py", content="x"))

    def test_the_project_root_is_found_above_the_working_directory(self):
        self.lock()
        sub = self.root / "tests" / "unit"
        sub.mkdir(parents=True)
        self.denies(handler(pre("Write", sub, file_path=str(sub / "test_beta.py"), content="x")))

    def test_the_project_dir_variable_is_used_without_a_cwd(self):
        import os
        self.lock()
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.root)
        self.denies(handler(pre("Write", None, file_path="tests/test_alpha.py", content="x")))

    def test_other_tools_and_odd_payloads_are_allowed(self):
        self.lock()
        self.allows(handler({}))
        self.allows(handler({"tool_name": "Write", "tool_input": {}}))
        self.allows(handler({"tool_name": "Bash", "tool_input": {"command": None}}))

    def test_the_lock_file_itself_is_protected_from_shell_and_edit_writes(self):
        self.lock()
        self.denies(handler(self.w("Write", ".batuta/test-locks.json", content="{}")), "lock file")
        self.denies(handler(self.b("echo {} > .batuta/test-locks.json")), "lock file")


if __name__ == "__main__":
    unittest.main()
