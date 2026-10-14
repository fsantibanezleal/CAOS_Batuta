"""Re-check at c607823: test-path vocabulary (N-5), Gates that cannot fail on a test (N-6), legitimate forms (N-7), device
independence (N-8), JSX text (N-9), and the case-differing scopes closed by U0r5 (F-09)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import SPEC, SPEC_ID, make_project, messages, run_json, write  # noqa: E402
from batuta_lib import spec_model as sm  # noqa: E402
from batuta_lib import trace  # noqa: E402

GATE1 = "`pytest tests/test_alerts.py`"
BAR = "\\|\\|"   # a double pipe as an author writes it in a table cell


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

    def fails(self, doc):
        return " | ".join(messages(doc, "FAIL"))


class TestPathVocabulary(Base):
    def test_conventions_of_the_common_ecosystems_count(self):
        for path in ("tests/test_alerts.py", "alerts_test.py", "web/__tests__/a.js", "web/a.spec.ts", "web/a.test.tsx",
                     "pipeline/ingest_test.go", "src/test/java/com/x/AlertTest.java", "src/test/kotlin/AlertTests.kt",
                     "Alerts.Tests/AlertTests.cs", "Alerts.UnitTests/Program.cs", "Alerts.Tests/Alerts.Tests.csproj",
                     "Alerts.Tests", "tests/integration.rs", "tests", "spec/alert_spec.rb"):
            with self.subTest(path=path):
                self.assertTrue(sm.is_test_path(path), path)

    def test_support_and_data_files_never_count(self):
        for path in ("tests/conftest.py", "tests/__init__.py", "tests/fixtures/data.json", "tests/data.csv", "README.md",
                     "pyproject.toml", "checks/verify.py", "web/package.json"):
            with self.subTest(path=path):
                self.assertFalse(sm.is_test_path(path), path)

    def test_a_go_gate_naming_its_test_file_passes_and_a_conftest_only_gate_fails(self):
        write(self.root, "pipeline/ingest_test.go", "package pipeline\n")
        self.gate("`go test pipeline/ingest_test.go`")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))
        self.gate("`pytest tests/conftest.py`")
        write(self.root, "tests/conftest.py", "x = 1\n")
        code, doc, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("hash", self.fails(doc))

    def test_a_dotnet_test_folder_passes(self):
        write(self.root, "Alerts.Tests/AlertTests.cs", "class T {}\n")
        self.gate("`dotnet test Alerts.Tests`")
        code, doc, _ = self.lint()
        self.assertEqual(code, 0, messages(doc))

    def test_support_files_are_still_hashed_when_named_next_to_a_test(self):
        self.assertTrue(sm.is_test_path("tests/test_alerts.py"))
        tokens, _ = sm.named_test_tokens("`pytest tests/conftest.py tests/test_alerts.py`")
        files, _, _ = sm.expand_tests(self.root, tokens)
        self.assertIn("tests/test_alerts.py", files)


class CannotFailOnATest(Base):
    def test_commands_that_only_list_or_read_are_refused(self):
        write(self.root, "pipeline/x.txt", "x\n")
        cases = ["`ls tests/test_alerts.py`", "`cat tests/test_alerts.py`", "`git status`", "`git log tests/test_alerts.py`",
                 "`test -f tests/test_alerts.py`", "`type tests\\test_alerts.py`", "`dir tests`",
                 "`pytest --collect-only tests/test_alerts.py`", "`pytest --co tests/test_alerts.py`",
                 "`pytest tests/test_alerts.py --dry-run`", f"`pytest tests/test_alerts.py {BAR} pytest --lf`",
                 f"`pytest tests/test_alerts.py {BAR} printf ok`"]
        for gate in cases:
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1, gate)
                self.assertIn("REQ-ALR-001", self.fails(doc))


class LegitimateForms(Base):
    def test_trailing_echo_leading_cd_and_quoted_pipes_are_accepted(self):
        for gate in ("`pytest tests/test_alerts.py && echo done`", "`cd web && npm test -- tests/api.test.js`",
                     "`pytest tests/test_alerts.py -k \"a\\|b\"`", "`pytest tests/test_alerts.py -k \"a or b\"`",
                     "`pytest tests/test_alerts.py 2>&1`", "`export CI=1; pytest tests/test_alerts.py`"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 0, messages(doc))

    def test_an_unconditional_success_after_the_test_is_still_refused(self):
        for gate in ("`pytest tests/test_alerts.py; true`", "`pytest tests/test_alerts.py && exit 0`",
                     "`pytest tests/test_alerts.py & exit 0`", f"`pytest tests/test_alerts.py {BAR} true`",
                     "`cd web && true`"):
            with self.subTest(gate=gate):
                self.gate(gate)
                code, doc, _ = self.lint()
                self.assertEqual(code, 1, gate)


class DeviceIndependence(Base):
    def test_the_path_is_never_consulted(self):
        with mock.patch("shutil.which", return_value="/usr/bin/mytool"):
            self.assertIsNotNone(sm.check_gate("`mytool tests/test_alerts.py`"))
        self.assertFalse(hasattr(sm, "shutil"))

    def test_the_documented_runner_list_covers_the_common_ecosystems(self):
        for word in ("python", "py", "pytest", "uv", "poetry", "tox", "nox", "hatch", "node", "npm", "npx", "pnpm", "yarn", "bun",
                     "deno", "vitest", "jest", "go", "cargo", "dotnet", "mvn", "gradle", "./gradlew", "java", "make", "bash", "sh",
                     "pwsh", "powershell", "ctest", "cmake", "bazel", "rspec", "bundle", "ruby", "php", "phpunit", "swift", "mix",
                     "R", "Rscript", "julia"):
            with self.subTest(word=word):
                self.assertIsNone(sm.check_gate(f"`{word} tests/test_alerts.py`"), word)

    def test_a_repository_script_counts_when_it_exists(self):
        write(self.root, "tools/run_checks.sh", "echo\n")
        self.assertIsNone(sm.check_gate("`./tools/run_checks.sh tests/test_alerts.py`", self.root))
        self.assertIsNotNone(sm.check_gate("`./tools/missing.sh tests/test_alerts.py`", self.root))


class JsxText(unittest.TestCase):
    def test_an_apostrophe_in_jsx_text_does_not_hide_the_next_marker_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.test.jsx"
            p.write_text("const el = <p>don't</p>;\n// REQ: REQ-ALR-001\n", encoding="utf-8")
            self.assertEqual(trace.scan_markers(p), ["REQ-ALR-001"])


class ScopesThatDifferInCase(Base):
    def edit(self, old, new):
        p = self.root / ".batuta/sizing.md"
        write(self.root, ".batuta/sizing.md", p.read_text(encoding="utf-8").replace(old, new))

    def test_case_differing_and_bare_name_scopes_overlap(self):
        for scope in ("PIPELINE/", "Pipeline/x.py", "pipeline"):
            with self.subTest(scope=scope):
                self.edit("| u-api | api/, tests/api/ |", f"| u-api | {scope}, tests/api/ |")
                code, doc, _ = run_json("size", "lint", "--root", self.root)
                self.assertEqual(code, 1, scope)
                self.assertTrue(any("overlap" in m.lower() for m in messages(doc, "FAIL")), messages(doc))
                self.edit(f"| u-api | {scope}, tests/api/ |", "| u-api | api/, tests/api/ |")

    def test_distinct_folders_do_not_overlap(self):
        self.edit("| u-api | api/, tests/api/ |", "| u-api | pipe/, tests/api/ |")
        code, doc, _ = run_json("size", "lint", "--root", self.root)
        self.assertEqual(code, 0, messages(doc))


if __name__ == "__main__":
    unittest.main()
