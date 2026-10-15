"""Final check at 1862d0b: a Gate's exit status is the test's (N-10, N-11), POSIX quoting (N-12), test-named files only (N-13)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import SPEC, SPEC_ID, make_project, messages, run_json, write  # noqa: E402
from batuta_lib import spec_model as sm  # noqa: E402

GATE1 = "`pytest tests/test_alerts.py`"
BAR = "\\|\\|"   # a double pipe as an author writes it in a table cell
PIPE = "\\|"


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

    def refused(self, gates):
        for gate in gates:
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1, gate)
                self.assertIn("REQ-ALR-001", " | ".join(messages(doc, "FAIL")))

    def accepted(self, gates):
        for gate in gates:
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 0, f"{gate}: {messages(doc)}")


class ExitStatusIsTheTests(Base):
    def test_a_double_pipe_anywhere_is_refused(self):
        self.refused([f"`pytest tests/test_alerts.py {BAR} pytest tests/test_alerts.py`",
                      f"`ruff check {BAR} true; pytest tests/test_alerts.py`"])

    def test_a_semicolon_chain_must_end_with_a_test_invocation_naming_a_test_path(self):
        self.refused(["`pytest tests/test_alerts.py; python -c 1`", "`pytest tests/test_alerts.py; python -c 0`",
                      "`pytest tests/test_alerts.py; python -m py_compile tests/test_alerts.py`",
                      "`pytest tests/test_alerts.py; echo done`", "`pytest tests/test_alerts.py; ruff check`",
                      "`pytest tests/test_alerts.py; true`", "`pytest tests/test_alerts.py & exit 0`"])
        self.accepted(["`ruff check; pytest tests/test_alerts.py`", "`export CI=1; pytest tests/test_alerts.py`",
                       "`ruff check && pytest tests/test_alerts.py`", "`pytest tests/test_alerts.py && echo done`",
                       "`python -m unittest tests/test_alerts.py`"])

    def test_a_pipe_after_a_test_is_refused_unless_pipefail_comes_first(self):
        self.refused([f"`pytest tests/test_alerts.py {PIPE} tail -5`", f"`pytest tests/test_alerts.py {PIPE} cat`",
                      f"`pytest tests/test_alerts.py {PIPE} tee out.txt`",
                      f"`pwsh -Command \"pytest tests/test_alerts.py {PIPE} Out-Null\"`",
                      f"`powershell pytest tests/test_alerts.py {PIPE} tee x`",
                      f"`set -o pipefail; pwsh -Command \"pytest tests/test_alerts.py {PIPE} tee x\"`"])
        self.accepted([f"`set -o pipefail; pytest tests/test_alerts.py {PIPE} tee out.txt`",
                       f"`bash -c \"set -o pipefail; pytest tests/test_alerts.py {PIPE} tail -5\"`",
                       f"`pytest tests/test_alerts.py -k \"a{PIPE}b\"`"])

    def test_shell_bodies_are_analysed_with_the_same_rules(self):
        self.refused([f"`bash -c \"pytest tests/test_alerts.py; true\"`", f"`sh -c 'pytest tests/test_alerts.py {BAR} true'`",
                      "`cmd /c pytest tests/test_alerts.py & exit 0`", "`cmd /k exit 0`",
                      "`pwsh -Command \"pytest tests/test_alerts.py; echo x\"`",
                      "`powershell -Command \"pytest tests/test_alerts.py; exit 0\"`",
                      f"`bash -c \"pytest tests/test_alerts.py {PIPE} tail -5\"`", "`zsh -c 'true'`"])
        self.accepted(["`bash -c \"pytest tests/test_alerts.py\"`", "`sh -c 'cd web && npm test -- tests/api.test.js'`",
                       "`pwsh -Command \"pytest tests/test_alerts.py\"`"])

    def test_info_and_listing_invocations_do_not_count_as_the_test(self):
        self.refused(["`pytest --version tests/test_alerts.py`", "`pytest -V tests/test_alerts.py`",
                      "`pytest -h tests/test_alerts.py`", "`pytest --help tests/test_alerts.py`",
                      "`make -n tests/test_alerts.py`", "`npm ls tests/test_alerts.py`", "`pip list tests/test_alerts.py`",
                      "`pytest --co tests/test_alerts.py`"])


class PosixQuoting(unittest.TestCase):
    def test_a_backslash_does_not_escape_inside_single_quotes(self):
        chain = sm.split_chain("pytest tests/test_alerts.py -k 'a\\' || true")
        self.assertEqual([op for op, _ in chain], ["", "||"])

    def test_a_backslash_escapes_inside_double_quotes_and_outside_quotes(self):
        self.assertEqual(len(sm.split_chain('pytest -k "a\\" || c"')), 1)
        self.assertEqual(len(sm.split_chain("pytest -k a\\;b")), 1)

    def test_a_gate_hiding_a_semicolon_behind_a_single_quoted_backslash_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_project(d)
            write(root, f"specs/{SPEC_ID}/spec.md", SPEC.replace(GATE1, "`pytest tests/test_alerts.py -k 'x\\' ; true`"))
            code, doc, _ = run_json("spec", "lint", "--root", root)
            self.assertEqual(code, 1)


class TestNamedFilesOnly(Base):
    def test_helpers_fixtures_and_scripts_under_a_test_folder_never_count(self):
        for path in ("tests/helpers.py", "tests/fixtures/builders.py", "tests/run.sh", "tests/conftest.py", "tests/util.js"):
            with self.subTest(path=path):
                self.assertFalse(sm.is_test_path(path), path)

    def test_the_naming_conventions_still_count_and_so_do_rust_integration_tests_and_jest_folders(self):
        for path in ("tests/test_a.py", "tests/a_test.py", "tests/a.test.js", "tests/a.spec.ts", "tests/integration.rs",
                     "web/__tests__/a.js", "src/test/java/AlertTest.java", "Alerts.Tests/AlertTests.cs",
                     "Alerts.Tests/Alerts.Tests.csproj", "pipeline/ingest_test.go"):
            with self.subTest(path=path):
                self.assertTrue(sm.is_test_path(path), path)

    def test_a_gate_naming_only_a_helper_fails_and_a_folder_counts_only_with_a_test_inside(self):
        write(self.root, "helpers/tests/helpers.py", "x = 1\n")
        write(self.root, "onlyhelpers/tests/helpers.py", "x = 1\n")
        self.refused(["`pytest onlyhelpers/tests/helpers.py`", "`pytest onlyhelpers/tests`"])
        self.accepted(["`pytest tests`"])

    def test_a_named_helper_is_still_hashed_next_to_a_test(self):
        tokens, _ = sm.named_test_tokens("`pytest tests/helpers.py tests/test_alerts.py`")
        write(self.root, "tests/helpers.py", "x = 1\n")
        files, _, _ = sm.expand_tests(self.root, tokens)
        self.assertIn("tests/helpers.py", files)


if __name__ == "__main__":
    unittest.main()
