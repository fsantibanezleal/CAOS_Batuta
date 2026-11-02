"""Final check at eb1e9e1: pipefail only from a real `set` before the pipe, nothing after the test in a `;` chain (R4-01),
shell run-flag clusters and PowerShell prefixes (R4-02), `.rs` only directly under `tests/` (R4-03)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import SPEC, SPEC_ID, make_project, messages, run_json, write  # noqa: E402
from batuta_lib import spec_model as sm  # noqa: E402

GATE1 = "`pytest tests/test_alerts.py`"
PIPE = "\\|"   # a pipe as an author writes it in a table cell


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


class Pipefail(Base):
    def test_pipefail_must_be_a_real_set_option_before_the_pipe(self):
        self.refused([f"`set +o pipefail; pytest tests/test_alerts.py {PIPE} tail -5`",
                      f"`set -o pipefail; set +o pipefail; pytest tests/test_alerts.py {PIPE} tail -5`",
                      f"`pytest tests/test_alerts.py {PIPE} tail -5; set -o pipefail`",
                      f"`set -o pipefailx; pytest tests/test_alerts.py {PIPE} tail -5`",
                      f"`cmd /c \"set -o pipefail & pytest tests/test_alerts.py {PIPE} more\"`",
                      f"`set pipefail; pytest tests/test_alerts.py {PIPE} tail -5`"])

    def test_real_pipefail_forms_are_accepted(self):
        self.accepted([f"`set -o pipefail; pytest tests/test_alerts.py {PIPE} tail -5`",
                       f"`set -eo pipefail; pytest tests/test_alerts.py {PIPE} tail -5`",
                       f"`set -euo pipefail; pytest tests/test_alerts.py {PIPE} tail -5`",
                       f"`set -e -o pipefail; pytest tests/test_alerts.py {PIPE} tail -5`"])

    def test_nothing_may_follow_the_test_in_a_semicolon_or_ampersand_chain_but_and_and(self):
        self.refused(["`pytest tests/test_alerts.py; cd .`", "`pytest tests/test_alerts.py; export X=1`",
                      "`pytest tests/test_alerts.py; set -e`", "`pytest tests/test_alerts.py & cd .`",
                      "`pytest tests/test_alerts.py; pushd .`"])
        self.accepted(["`pytest tests/test_alerts.py && cd .`", "`cd web; pytest tests/test_alerts.py`",
                       "`export X=1; set -e; pytest tests/test_alerts.py`"])


class RunFlags(Base):
    def test_a_short_flag_cluster_with_c_is_the_run_flag_of_posix_shells(self):
        self.refused(["`bash -lc \"pytest tests/test_alerts.py; true\"`", "`bash -ec \"pytest tests/test_alerts.py; true\"`",
                      "`sh -xc 'pytest tests/test_alerts.py; true'`", "`zsh -lc 'pytest tests/test_alerts.py; exit 0'`",
                      "`dash -ec 'true'`"])
        self.accepted(["`bash -lc \"pytest tests/test_alerts.py\"`", "`sh -ec 'pytest tests/test_alerts.py'`"])

    def test_powershell_command_prefixes_are_analysed_and_encoded_commands_refused(self):
        self.refused(["`pwsh -Comm \"pytest tests/test_alerts.py; exit 0\"`", "`pwsh -Co \"pytest tests/test_alerts.py; exit 0\"`",
                      "`pwsh -c \"pytest tests/test_alerts.py; exit 0\"`", "`pwsh -EncodedCommand cGluZw==`",
                      "`powershell -e cGluZw==`", "`pwsh -EncodedC cGluZw==`"])
        self.accepted(["`pwsh -Comm \"pytest tests/test_alerts.py\"`", "`pwsh -c \"pytest tests/test_alerts.py\"`"])


class RustTests(Base):
    def test_a_rust_file_counts_only_directly_under_tests(self):
        self.assertTrue(sm.is_test_path("tests/integration.rs"))
        self.assertTrue(sm.is_test_path("crate/tests/integration.rs"))
        self.assertFalse(sm.is_test_path("tests/common/mod.rs"))
        self.assertFalse(sm.is_test_path("tests/common/helpers.rs"))

    def test_a_gate_naming_only_a_rust_helper_fails(self):
        write(self.root, "tests/common/mod.rs", "pub fn x() {}\n")
        self.refused(["`cargo test --test alerts tests/common/mod.rs`"])


if __name__ == "__main__":
    unittest.main()
