"""Re-check of the U3 review at 01b2c29: console probe and timeout (F-01), test-looking Gate files (F-04), Gates that can
never fail (N-1), command spans (N-2), regex literals in the JavaScript marker reader (N-3), capped echoes (N-4)."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import SPEC, SPEC_ID, make_project, messages, prefix_of, run_json, write  # noqa: E402
from batuta_lib import spec_model as sm  # noqa: E402
from batuta_lib import trace  # noqa: E402
from batuta_lib.areas import spec as spec_area  # noqa: E402

GATE1 = "`pytest tests/test_alerts.py`"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_project(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def gate(self, text):
        write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace(GATE1, text))

    def lint(self):
        return run_json("spec", "lint", "--root", self.root)

    def approve(self):
        phrase = f"approve {SPEC_ID} {prefix_of(self.root / 'specs' / SPEC_ID / 'spec.md')}\n"
        with mock.patch.object(spec_area, "_read_console", return_value=phrase):
            return run_json("spec", "approve", SPEC_ID, "--root", self.root)

    def fails(self, doc):
        return " | ".join(messages(doc, "FAIL"))

    def records(self):
        return list((self.root / f"specs/{SPEC_ID}/approvals").glob("*.json"))


class ConsoleProbe(unittest.TestCase):
    def test_windows_stdin_that_passes_isatty_but_is_not_a_console_handle_is_refused(self):
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: True)), \
                mock.patch.object(spec_area, "_console_mode_ok", return_value=False):
            with self.assertRaises(spec_area.ConsoleError) as cm:
                spec_area._read_console()
        self.assertIn("console", str(cm.exception))

    def test_windows_console_handle_is_accepted_and_the_device_is_read(self):
        opened = []

        def fake_open(path, *a, **k):
            opened.append(path)
            return mock.MagicMock(__enter__=lambda s: mock.Mock(readline=lambda: "typed\n"), __exit__=lambda *x: False)

        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: True)), \
                mock.patch.object(spec_area, "_console_mode_ok", return_value=True), mock.patch("builtins.open", fake_open):
            self.assertEqual(spec_area._read_console(), "typed\n")
        self.assertEqual(opened, ["CONIN$"])

    def test_posix_needs_a_tty_and_an_openable_dev_tty(self):
        def no_tty(path, *a, **k):
            raise OSError("no controlling terminal")

        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: True)), \
                mock.patch("builtins.open", no_tty):
            with self.assertRaises(spec_area.ConsoleError):
                spec_area._read_console()
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: False)):
            with self.assertRaises(spec_area.ConsoleError):
                spec_area._read_console()

    def test_the_read_times_out_with_a_refusal_so_nobody_typing_never_hangs(self):
        gate = threading.Event()

        class Blocking:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def readline(self):
                gate.wait(5)
                return ""

        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: True)), \
                mock.patch("builtins.open", lambda *a, **k: Blocking()), mock.patch.object(spec_area, "CONSOLE_TIMEOUT_SECONDS", 0.2):
            with self.assertRaises(spec_area.ConsoleError) as cm:
                spec_area._read_console()
        gate.set()
        self.assertIn("timed out", str(cm.exception))

    def test_the_default_timeout_is_three_hundred_seconds(self):
        self.assertEqual(spec_area.CONSOLE_TIMEOUT_SECONDS, 300)

    def test_a_timeout_makes_spec_approve_refuse_with_exit_one_and_write_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_project(d)
            with mock.patch.object(spec_area, "_read_console", side_effect=spec_area.ConsoleError("timed out after 300 seconds")):
                code, doc, _ = run_json("spec", "approve", SPEC_ID, "--root", root)
            self.assertEqual(code, 1)
            self.assertTrue(any("timed out" in m for m in messages(doc, "REFUSED")))
            self.assertFalse((root / f"specs/{SPEC_ID}/approvals").exists())


class TestLookingGateFile(Base):
    def test_a_gate_naming_only_configuration_or_documentation_fails_and_is_refused(self):
        write(self.root, "pyproject.toml", "[tool.pytest]\n")
        write(self.root, "tox.ini", "[tox]\n")
        write(self.root, "web/package.json", "{}\n")
        write(self.root, "README.md", "readme\n")
        for gate in ("`pytest -c pyproject.toml -k emit`", "`tox -c tox.ini`", "`npm test --prefix web`",
                     "`python -m pytest -k test_emit README.md`", f"`pytest -k emit specs/{SPEC_ID}/spec.md`",
                     "`python checks/verify_alerts.py`"):
            with self.subTest(gate=gate):
                write(self.root, "checks/verify_alerts.py", "print('ok')\n")
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1)
                self.assertIn("hash", self.fails(doc))
                self.assertEqual(self.approve()[0], 1)
                self.assertEqual(self.records(), [])

    def test_a_named_configuration_file_is_still_hashed_next_to_a_test(self):
        write(self.root, "pyproject.toml", "[tool.pytest]\n")
        self.gate("`pytest -c pyproject.toml tests/test_alerts.py`")
        self.assertEqual(self.approve()[0], 0)
        rec = json.loads(self.records()[0].read_text(encoding="utf-8"))
        self.assertIn("pyproject.toml", rec["named_tests_sha256"])
        self.assertIn("tests/test_alerts.py", rec["named_tests_sha256"])


class NeverFails(Base):
    def test_chains_and_no_op_commands_that_can_never_fail_are_refused(self):
        bar = "|" + "|"
        cases = [f"`pytest tests/test_alerts.py {bar} true`", f"`pytest tests/test_alerts.py {bar} :`",
                 "`pytest tests/test_alerts.py; true`", "`pytest tests/test_alerts.py; exit 0`",
                 "`pytest tests/test_alerts.py & exit 0`", "`pytest tests/test_alerts.py && exit 0`",
                 "`/bin/true tests/test_alerts.py`", "`cmd /c exit 0`", "`python -c pass tests/test_alerts.py`",
                 "`python -c \"pass\"`", "`sh -c true tests/test_alerts.py`", "`true`", "`echo ok tests/test_alerts.py`"]
        for gate in cases:
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1, gate)
                self.assertIn("REQ-ALR-001", self.fails(doc))
                self.assertIn("fail", self.fails(doc))

    def test_an_escaped_double_pipe_written_in_the_table_cell_is_refused(self):
        text = SPEC.replace(GATE1, "`pytest tests/test_alerts.py \\|\\| true`")
        write(self.root, f"specs/{SPEC_ID}/spec.md", text)
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)

    def test_real_chains_that_can_fail_are_accepted(self):
        for gate in ("`pytest tests/test_alerts.py -k \"not slow\"`", "`ruff check`; `pytest tests/test_alerts.py`",
                     "`node --test tests/api.test.js`"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 0, messages(doc))


class CommandSpans(Base):
    def test_prose_inside_one_span_is_not_a_command(self):
        write(self.root, "docs/notes.md", "n\n")
        for gate in ("`manually check tests/test_alerts.py`", "`ask QA to look at tests/`", "`review docs`"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1, gate)
                self.assertIn("first word", self.fails(doc))

    def test_a_known_runner_a_path_on_the_path_and_a_repository_script_are_commands(self):
        write(self.root, "checks/run_tests.sh", "echo\n")
        for gate in ("`pytest tests/test_alerts.py`", "`./checks/run_tests.sh tests/test_alerts.py`", "`tox -e unit tests/test_alerts.py`"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 0, messages(doc))

    def test_check_gate_resolves_an_executable_on_the_path(self):
        with mock.patch("shutil.which", return_value="/usr/bin/mytool"):
            self.assertIsNone(sm.check_gate("`mytool tests/test_alerts.py`"))
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNotNone(sm.check_gate("`mytool tests/test_alerts.py`"))


class JsRegexLiterals(unittest.TestCase):
    def read(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.test.js"
            p.write_text(text, encoding="utf-8")
            return trace.scan_markers(p)

    def test_a_quote_inside_a_regex_literal_does_not_shift_the_string_state(self):
        text = "const re = /it's/;\n// REQ: REQ-ALR-003\n"
        self.assertEqual(self.read(text), ["REQ-ALR-003"])

    def test_a_backtick_inside_a_regex_literal_does_not_open_a_template(self):
        text = "const re = /`/;\nconst t = `\n// REQ: REQ-ALR-003\n`;\n"
        self.assertEqual(self.read(text), [])

    def test_division_is_not_a_regex_and_a_class_may_hold_a_slash(self):
        text = "const a = x / 2; const b = y / 3; // REQ: REQ-ALR-001\nconst re = /[/']/;\n// REQ: REQ-ALR-002\n"
        self.assertEqual(self.read(text), ["REQ-ALR-002"])

    def test_regex_after_an_operator_return_and_a_call_paren(self):
        text = "x = a.replace(/'/g, '');\nif (ok) { return /\"/; }\n// REQ: REQ-ALR-001\n"
        self.assertEqual(self.read(text), ["REQ-ALR-001"])


class CappedEcho(Base):
    def hook(self, prompt):
        return spec_area.HOOKS["spec-approval"]({"hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": str(self.root)})

    def test_a_huge_typed_prefix_is_clipped_and_the_output_stays_under_the_c16_limit(self):
        res = self.hook(f"approve {SPEC_ID} " + "a" * 20000)
        ctx = res["output"]["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(ctx), 10000)
        self.assertLessEqual(len(res["output"]["systemMessage"]), 10000)
        self.assertNotIn("a" * 250, ctx)
        self.assertIn("...", ctx)
        self.assertEqual(self.records(), [])

    def test_a_huge_typed_spec_id_is_clipped_too(self):
        res = self.hook("approve 001-" + "b" * 20000 + " " + "a" * 12)
        ctx = res["output"]["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(ctx), 10000)
        self.assertNotIn("b" * 250, ctx)

    def test_the_dry_run_clips_the_same_way(self):
        payload = json.dumps({"prompt": f"approve {SPEC_ID} " + "a" * 20000, "cwd": str(self.root)})
        code, out, _ = __import__("test_spec_project").run("spec", "hook-approval", stdin=payload)
        self.assertEqual(code, 1)
        self.assertNotIn("a" * 250, out)


if __name__ == "__main__":
    unittest.main()
