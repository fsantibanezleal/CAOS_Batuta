"""Plan decision 33: an agent never runs the hook launcher `hook.py` directly (any handler id or none); the harness runs
hooks itself, never through an agent's tool call. Reads of the file, and tests that only name it, stay allowed."""
import unittest

from test_guard_common import GuardCase, isolated_env, pre, reason_of

from batuta_lib.areas import guard


def approvals(payload):
    return guard.HOOKS["guard-approvals"](payload)


RUNS = [
    "python plugins/batuta/scripts/hook.py guard-automation",
    "python hook.py",
    "python scripts/hook.py spec-approval",
    "python scripts/hook.py tdd-change-request",
    "python3 scripts/hook.py session-check",
    "python3.12 -I -B scripts/hook.py guard-secrets",
    "py -3 hook.py guard-secrets",
    "py -3.12 plugins/batuta/scripts/hook.py x",
    "pythonw hook.py x",
    "C:/Python314/python.exe C:/work/plugins/batuta/scripts/hook.py guard-destructive",
    "\"C:\\Program Files\\Python\\python.exe\" \"C:\\work\\batuta\\scripts\\hook.py\" any-id",
    "./hook.py guard-automation",
    "./plugins/batuta/scripts/hook.py",
    "plugins/batuta/scripts/hook.py guard-secrets",
    "echo '{}' | python scripts/hook.py guard-automation",
    "cat payload.json | python scripts/hook.py guard-locked-tests",
    "python scripts/hook.py guard-automation < payload.json",
    "cd plugins/batuta && python scripts/hook.py guard-automation",
    "true && python scripts/hook.py guard-automation",
    "echo ok; python scripts/hook.py guard-automation",
    "python scripts/hook.py guard-automation | cat",
    "bash -c 'python scripts/hook.py guard-automation'",
    "sh -c \"python scripts/hook.py x\"",
    "cmd /c python scripts/hook.py x",
    "pwsh -c python scripts/hook.py x",
    "powershell -Command \"python scripts/hook.py x\"",
    "FOO=1 python scripts/hook.py x",
    "PYTHONPATH=. python -B scripts/HOOK.PY x",
    "env PYTHONIOENCODING=utf-8 python scripts/hook.py x",
    "sudo python scripts/hook.py x",
    "echo $(python scripts/hook.py x)",
    "python scripts/hook.py \\\n  guard-automation",
    "python scripts\\\\hook.py x",
    "python scripts/ho^ok.py x",
    "python scripts/hook\u200b.py x",
    "python scripts/\uff48\uff4f\uff4f\uff4b.py x",
    "uv run scripts/hook.py x",
    "pipx run scripts/hook.py x",
    "python -c \"exec(open('scripts/hook.py').read())\"",
    "python -c \"import runpy; runpy.run_path('scripts/hook.py')\"",
    "xargs python scripts/hook.py",
    "python -u -X utf8 scripts/hook.py guard-automation",
]
RUNS_POWERSHELL = [
    "$r = python scripts/hook.py guard-automation",
    "$null = & python plugins/batuta/scripts/hook.py x",
    "Start-Process python -ArgumentList 'scripts/hook.py x'",
    "saps python scripts\\hook.py",
    "& python scripts/hook.py x",
    "[string]$x = python scripts/hook.py x",
    "if ($true) { python scripts/hook.py x }",
    "python .\\scripts\\hook.py x",
    "Get-Content p.json | python scripts/hook.py x",
]
ALLOWED = [
    "cat plugins/batuta/scripts/hook.py",
    "grep -n handler plugins/batuta/scripts/hook.py",
    "git diff plugins/batuta/scripts/hook.py",
    "git log --oneline -- plugins/batuta/scripts/hook.py",
    "python -m unittest discover -s tests -p test_hook_launcher.py",
    "python -m pytest tests/test_hook_launcher.py",
    "python -m py_compile plugins/batuta/scripts/hook.py",
    "python plugins/batuta/scripts/batuta.py guard automation --payload p.json",
    "python plugins/batuta/scripts/batuta.py contract validate C31 f.json",
    "wc -l scripts/hook.py",
    "ls scripts",
    "echo hook.py is run by the harness",
    "python run_hook_tests.py",
    "python notes_hook.py",
    "python scripts/webhook.py",
]


class LauncherRunsAreDenied(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)

    def test_every_spelling_of_a_direct_launcher_run_is_denied(self):
        for tool in ("Bash", "Monitor", "SomeFutureShell"):
            for command in RUNS:
                with self.subTest(tool=tool, command=command):
                    self.denies(approvals(pre(tool, command=command)), msg=f"expected deny: {command!r}")

    def test_powershell_spellings_are_denied(self):
        for command in RUNS_POWERSHELL:
            with self.subTest(command=command):
                self.denies(approvals(pre("PowerShell", command=command)), msg=command)

    def test_the_reason_says_the_harness_runs_hooks(self):
        reason = reason_of(approvals(pre("Bash", command="python scripts/hook.py guard-automation")))
        self.assertIn("harness", reason)
        self.assertIn("guard <name> --payload", reason)

    def test_reads_tests_and_other_scripts_stay_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.allows(approvals(pre("Bash", command=command)), command)

    def test_the_specific_denials_for_approve_and_decide_remain(self):
        self.denies(approvals(pre("Bash", command="python batuta.py spec approve 001-x --apply")), "approval")
        self.denies(approvals(pre("Bash", command="python batuta.py tdd change-request decide CR-001")), "change request")


if __name__ == "__main__":
    unittest.main()
