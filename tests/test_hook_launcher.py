"""The hook launcher `scripts/hook.py` (contract C31): handler discovery by ast, result validation, exit codes.

Every test runs the launcher from a copy of the scripts folder that holds a fixture area, so the real areas are never
involved; the launcher is also run in process for the timing check."""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REAL_SCRIPTS = ROOT / "plugins" / "batuta" / "scripts"

PAYLOAD = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}

ALLOW = {"contract_version": "1.0", "exit_code": 0, "output": None}
DENY_OUT = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "no"}}

FIXTURE = textwrap.dedent('''
    """A fixture area: one handler per behaviour the launcher must cover."""
    import json
    ALLOW = {"contract_version": "1.0", "exit_code": 0, "output": None}


    def fx_allow(payload):
        return ALLOW


    def fx_deny(payload):
        return {"contract_version": "1.0", "exit_code": 0, "output": {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "no: " + payload["tool_input"]["command"]}}}


    def fx_block(payload):
        return {"contract_version": "1.0", "exit_code": 2, "output": None, "message": "blocked because of the fixture"}


    def fx_raise(payload):
        raise RuntimeError("boom from the fixture")


    def fx_exit_one(payload):
        return {"contract_version": "1.0", "exit_code": 1, "output": None}


    def fx_not_dict(payload):
        return "allow"


    def fx_block_without_message(payload):
        return {"contract_version": "1.0", "exit_code": 2, "output": None}


    def fx_bad_output(payload):
        return {"contract_version": "1.0", "exit_code": 0, "output": {"unexpected": True}}


    def fx_unknown_key(payload):
        return {"contract_version": "1.0", "exit_code": 0, "output": None, "extra": 1}


    def fx_huge(payload):
        return {"contract_version": "1.0", "exit_code": 0, "output": {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "x" * 20000}}}


    def fx_echo_keys(payload):
        return {"contract_version": "1.0", "exit_code": 0, "output": {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": ",".join(sorted(payload))}}}


    HOOKS = {
        "fx-allow": fx_allow,
        "fx-deny": fx_deny,
        "fx-block": fx_block,
        "fx-raise": fx_raise,
        "fx-exit-one": fx_exit_one,
        "fx-not-dict": fx_not_dict,
        "fx-block-without-message": fx_block_without_message,
        "fx-bad-output": fx_bad_output,
        "fx-unknown-key": fx_unknown_key,
        "fx-huge": fx_huge,
        "fx-echo-keys": fx_echo_keys,
    }
''')

SECOND = textwrap.dedent('''
    def other(payload):
        return {"contract_version": "1.0", "exit_code": 0, "output": None}


    HOOKS = {"fx-allow": other}
''')

IMPORT_ERROR = textwrap.dedent('''
    import module_that_does_not_exist

    HOOKS = {"fx-broken": lambda payload: None}
''')


class LauncherCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scripts = pathlib.Path(self.tmp.name) / "scripts"
        areas = self.scripts / "batuta_lib" / "areas"
        areas.mkdir(parents=True)
        (self.scripts / "batuta_lib" / "__init__.py").write_text("", encoding="utf-8")
        (areas / "__init__.py").write_text("", encoding="utf-8")
        (areas / "fixture.py").write_text(FIXTURE, encoding="utf-8")
        # a module that has no HOOKS must never be imported to find a handler (this one would crash on import)
        (areas / "crashes_on_import.py").write_text("raise SystemExit('imported by mistake')\n", encoding="utf-8")
        shutil.copy(REAL_SCRIPTS / "hook.py", self.scripts / "hook.py")
        self.areas = areas

    def run_hook(self, *argv, stdin=None, raw=False):
        data = stdin if raw else json.dumps(PAYLOAD if stdin is None else stdin)
        return subprocess.run([sys.executable, str(self.scripts / "hook.py"), *argv], input=data,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)


class Resolution(LauncherCase):
    def test_a_fixture_handler_resolves_and_allows(self):
        proc = self.run_hook("fx-allow")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_the_handler_receives_the_payload(self):
        proc = self.run_hook("fx-echo-keys")
        out = json.loads(proc.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"], "hook_event_name,tool_input,tool_name")

    def test_a_deny_prints_valid_c16_json_and_exits_zero(self):
        proc = self.run_hook("fx-deny")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"], "no: ls")

    def test_modules_without_hooks_are_not_imported(self):
        self.assertEqual(self.run_hook("fx-allow").returncode, 0)

    def test_an_unknown_id_exits_one_with_the_reason(self):
        proc = self.run_hook("fx-nope")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unknown", proc.stderr.lower())
        self.assertIn("fx-nope", proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_a_missing_id_exits_one(self):
        proc = self.run_hook()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("handler id", proc.stderr.lower())

    def test_an_id_that_is_not_a_valid_id_exits_one(self):
        for bad in ("../x", "FX-ALLOW", "fx allow", ""):
            with self.subTest(bad=bad):
                self.assertEqual(self.run_hook(bad).returncode, 1)

    def test_an_id_defined_twice_exits_one(self):
        (self.areas / "second.py").write_text(SECOND, encoding="utf-8")
        proc = self.run_hook("fx-allow")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("twice", proc.stderr.lower())
        self.assertIn("fixture", proc.stderr)
        self.assertIn("second", proc.stderr)

    def test_a_module_that_fails_to_import_exits_one_with_the_reason(self):
        (self.areas / "broken.py").write_text(IMPORT_ERROR, encoding="utf-8")
        proc = self.run_hook("fx-broken")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("module_that_does_not_exist", proc.stderr)

    def test_a_removed_guard_file_fails_open(self):
        (self.areas / "fixture.py").unlink()
        proc = self.run_hook("fx-allow")
        self.assertEqual(proc.returncode, 1)  # a non-blocking error for Claude Code: the action goes on
        self.assertNotEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout.strip(), "")


class Results(LauncherCase):
    def test_exit_code_two_prints_the_message_on_stderr(self):
        proc = self.run_hook("fx-block")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("blocked because of the fixture", proc.stderr)

    def test_a_handler_that_raises_exits_one_with_the_reason(self):
        proc = self.run_hook("fx-raise")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("RuntimeError", proc.stderr)
        self.assertIn("boom from the fixture", proc.stderr)

    def test_invalid_results_exit_one_and_name_the_problem(self):
        cases = {
            "fx-exit-one": "exit_code",
            "fx-not-dict": "object",
            "fx-block-without-message": "message",
            "fx-bad-output": "output",
            "fx-unknown-key": "extra",
        }
        for hid, word in cases.items():
            with self.subTest(hid=hid):
                proc = self.run_hook(hid)
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn("invalid", proc.stderr.lower())
                self.assertIn(word, proc.stderr)
                self.assertEqual(proc.stdout.strip(), "")

    def test_output_over_the_official_cap_is_refused(self):
        proc = self.run_hook("fx-huge")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("10000", proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_output_is_at_most_ten_thousand_characters(self):
        proc = self.run_hook("fx-deny")
        self.assertLessEqual(len(proc.stdout), 10000)

    def test_invalid_stdin_exits_one(self):
        for raw in ("{not json", "[1, 2]", '"text"', "null"):
            with self.subTest(raw=raw):
                proc = self.run_hook("fx-allow", stdin=raw, raw=True)
                self.assertEqual(proc.returncode, 1)
                self.assertIn("payload", proc.stderr.lower())

    def test_an_empty_stdin_is_an_empty_payload(self):
        proc = self.run_hook("fx-allow", stdin="", raw=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_a_byte_order_mark_on_stdin_is_accepted(self):
        proc = self.run_hook("fx-allow", stdin="﻿" + json.dumps(PAYLOAD), raw=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class Hygiene(LauncherCase):
    def test_no_bytecode_is_written(self):
        self.run_hook("fx-allow")
        self.run_hook("fx-deny")
        self.assertEqual(list(self.scripts.rglob("__pycache__")), [])

    def test_launcher_matches_the_contract_validator_on_every_fixture_result(self):
        sys.path.insert(0, str(REAL_SCRIPTS))
        from batuta_lib import contract
        import importlib.util
        spec = importlib.util.spec_from_file_location("hook_under_test", REAL_SCRIPTS / "hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        schema = contract.load_schema(contract.find_schema(ROOT / "plugins" / "batuta" / "contracts", "C31"))
        fixtures = sorted((ROOT / "plugins" / "batuta" / "contracts" / "fixtures" / "C31").glob("*handler-result*.json"))
        self.assertGreaterEqual(len(fixtures), 4)
        for path in fixtures:
            with self.subTest(fixture=path.name):
                doc = json.loads(path.read_text(encoding="utf-8"))
                official = contract.validate_instance("C31", doc, schema)
                ours = hook.validate_result(doc)
                self.assertEqual(bool(ours), bool(official), (path.name, ours, official))

    def test_the_launcher_answers_quickly_without_io(self):
        spec_path = self.scripts / "hook.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("hook_timed", spec_path)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        import io
        samples = []
        for _ in range(5):
            out, err = io.StringIO(), io.StringIO()
            start = time.perf_counter()
            code = hook.run("fx-allow", json.dumps(PAYLOAD), out, err)
            samples.append(time.perf_counter() - start)
            self.assertEqual(code, 0)
        self.assertLess(sorted(samples)[len(samples) // 2], 0.2, samples)


if __name__ == "__main__":
    unittest.main()
