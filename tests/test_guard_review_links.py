"""Re-check findings F-14 (creating a link to a protected path is denied outright) and F-29 (a self-calling function is an
unbounded loop). Payload cases only; nothing is executed."""
import pathlib
import tempfile
import unittest

from test_guard_common import GuardCase, isolated_env, pre

from batuta_lib.areas import guard

SHA = "a" * 64


def handler(name, payload):
    return guard.HOOKS[f"guard-{name}"](payload)


class Links(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        for rel in ("tests/test_a.py", ".env", "src/app.py", "specs/f/approvals/a.json", "README.md"):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        import json
        (self.root / ".batuta").mkdir()
        (self.root / ".batuta" / "test-locks.json").write_text(json.dumps({"contract_version": "1.0", "entries": [
            {"path": "tests/test_a.py", "sha256": SHA, "task_id": "T-001", "req_ids": ["REQ-A-001"],
             "locked_commit": "abc", "locked_at": "2026-10-13T10:00:00Z"}]}), encoding="utf-8")

    def call(self, guard_name, command, tool="Bash"):
        return handler(guard_name, pre(tool, self.root, command=command))

    def deny_all(self, guard_name, commands, tool="Bash"):
        for command in commands:
            with self.subTest(guard=guard_name, command=command):
                self.denies(self.call(guard_name, command, tool), msg=f"expected deny: {command}")

    def test_a_link_to_a_secret_is_denied_even_with_the_read_in_the_same_command(self):
        self.deny_all("secrets", [
            "ln -s .env notes.txt && cat notes.txt", "ln -s .env notes.txt", "ln .env notes.txt", "ln -sf .env notes.txt",
            "ln -s notes.txt .env", "ln -s .e* notes.txt", "ln -s ./.env n; cat n", "cmd /c mklink notes.txt .env",
            "cmd /c mklink /H notes.txt .env", "cmd /c mklink /J jn .env", "mklink notes.txt .env",
            "ln -s id_rsa k", "ln -s ~/.ssh/id_rsa k", "ln -s secrets/prod.txt p", "bash -c 'ln -s .env n'",
        ])
        self.deny_all("secrets", [
            "New-Item -ItemType SymbolicLink -Path notes.txt -Target .env", "New-Item -ItemType HardLink -Path n -Value .env",
            "New-Item -ItemType Junction -Path jn -Target secrets", "ni -ItemType SymbolicLink -Path n -Target .env",
            "[IO.File]::CreateSymbolicLink('notes.txt', '.env')", "[System.IO.File]::CreateSymbolicLink(\"n\", \".env\")",
            "$null = New-Item -ItemType SymbolicLink -Path n -Target .env",
        ], "PowerShell")

    def test_a_link_to_a_locked_test_the_lock_or_the_batuta_folder_is_denied(self):
        self.deny_all("locked-tests", [
            "ln -s tests/test_a.py n && cat n", "ln -s tests/test_a.py n", "ln tests/test_a.py n", "cmd /c mklink n tests\\test_a.py",
            "cmd /c mklink /J jn tests", "ln -s tests tt", "ln -s .batuta b", "ln -s .batuta/test-locks.json l",
            "ln -s .batuta/batuta.json c", "cmd /c mklink /J jn .batuta", "ln -s tests/test_*.py n",
        ])
        self.deny_all("locked-tests", [
            "New-Item -ItemType SymbolicLink -Path n -Target tests/test_a.py", "New-Item -ItemType Junction -Path j -Target .batuta",
            "New-Item -ItemType HardLink -Path h -Value tests\\test_a.py", "[IO.File]::CreateSymbolicLink('n', 'tests/test_a.py')",
            "[System.IO.File]::CreateSymbolicLink('n', '.batuta/test-locks.json')",
        ], "PowerShell")

    def test_a_link_to_an_approvals_folder_is_denied(self):
        self.deny_all("approvals", [
            "ln -s specs/f/approvals apr && cat apr/a.json", "ln -s specs/f/approvals apr", "cmd /c mklink /J apr specs\\f\\approvals",
            "ln -s specs/f/approvals/a.json a",
        ])
        self.deny_all("approvals", ["New-Item -ItemType Junction -Path apr -Target specs\\f\\approvals",
                                    "[IO.File]::CreateSymbolicLink('a', 'specs/f/approvals/a.json')"], "PowerShell")

    def test_links_between_ordinary_files_stay_allowed(self):
        for guard_name in ("secrets", "locked-tests", "approvals"):
            for command in ("ln -s src/app.py n", "ln -s README.md r", "cmd /c mklink n src\\app.py", "ln -s src srcl"):
                with self.subTest(guard=guard_name, command=command):
                    self.allows(self.call(guard_name, command), command)
            for command in ("New-Item -ItemType SymbolicLink -Path n -Target src/app.py", "New-Item -ItemType Directory tests2",
                            "New-Item -ItemType File -Path src/new.py", "[IO.File]::CreateSymbolicLink('n', 'src/app.py')"):
                with self.subTest(guard=guard_name, command=command):
                    self.allows(self.call(guard_name, command, "PowerShell"), command)

    def test_the_same_payloads_through_monitor(self):
        self.denies(self.call("secrets", "ln -s .env n", "Monitor"))
        self.denies(self.call("locked-tests", "ln -s tests/test_a.py n", "Monitor"))


class SelfCallingFunctions(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)

    BLOCKED = [
        "f(){ sleep 5; f; }; f", "loop() { sleep 5; loop; }; loop", "poll () { check_it; sleep 1; poll; }; poll",
        "function f { sleep 5; f }; f", "function wait-for { Start-Sleep 5; wait-for }; wait-for", "function f() { sleep 5; f; }; f",
        "f(){ f; }; f", "f(){\n  sleep 5\n  f\n}\nf", "bash -c 'f(){ sleep 5; f; }; f'",
    ]
    ALLOWED = [
        "f(){ echo hi; }; f", "function f { echo hi }; f", "f(){ g; }; g(){ echo x; }; f", "f(){ sleep 5; }; f",
        "g(){ timeout 60 bash -c 'until test -f x; do sleep 1; done'; g; }; g", "f(){ sleep 1; f; }  # deadline 60",
        "echo 'f(){ f; }'",
    ]

    def test_a_function_that_calls_itself_is_an_unbounded_loop(self):
        for tool, commands in (("Bash", self.BLOCKED), ("PowerShell", self.BLOCKED[3:5])):
            for command in commands:
                with self.subTest(tool=tool, command=command):
                    result = handler("automation", pre(tool, command=command))
                    self.denies(result, "polling loop", msg=command)

    def test_other_functions_are_fine(self):
        for command in self.ALLOWED[:5]:
            with self.subTest(command=command):
                self.allows(handler("automation", pre("Bash", command=command)), command)

    def test_a_bound_word_exempts_it_like_any_loop(self):
        self.allows(handler("automation", pre("Bash", command=self.ALLOWED[5])))


if __name__ == "__main__":
    unittest.main()
