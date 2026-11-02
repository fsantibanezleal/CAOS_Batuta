"""Exit code 2 means WARN only: the dispatcher's argument parser exits 1 on a usage error (argparse's own 2 is never used),
so a gate that fails to start cannot be mistaken for a warning by the CI step."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins" / "batuta" / "scripts" / "batuta.py"


def batuta(*args):
    done = subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True, timeout=120)
    return done.returncode, done.stdout, done.stderr


class UsageErrors(unittest.TestCase):
    def test_a_missing_required_argument_exits_1_with_the_usage_on_stderr(self):
        code, out, err = batuta("spec", "trace")
        self.assertEqual(code, 1)
        self.assertIn("usage:", err)
        self.assertIn("spec_id", err)

    def test_an_unknown_flag_an_unknown_area_and_a_missing_verb_exit_1(self):
        for args in (("gate", "check", "--bogus"), ("nosuch", "area"), ("spec",), ("init", "project", "--var")):
            code, out, err = batuta(*args)
            self.assertEqual(code, 1, args)
            self.assertIn("usage:", err, args)

    def test_help_and_version_still_exit_0(self):
        for args in (("--help",), ("spec", "--help"), ("--version",), ("version", "show")):
            self.assertEqual(batuta(*args)[0], 0, args)

    def test_a_warning_still_exits_2(self):
        # `init project` into a folder without git is a WARN (dry run, nothing written)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = batuta("init", "project", "--target", str(Path(tmp) / "p"))
        self.assertEqual(code, 2, out + err)


if __name__ == "__main__":
    unittest.main()
