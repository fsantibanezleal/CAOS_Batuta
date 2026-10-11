"""The content-standards script flags an em-dash, an emoji and a user path, and passes on this repository."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import ROOT, load_module

SCRIPT = ROOT / "scripts" / "check_content_standards.py"

# Fixtures are built from code points and pieces so this file itself stays clean.
EM_DASH = chr(0x2014)
EMOJI = chr(0x1F33A)
WIN_PATH = "C:" + chr(92) + "Users" + chr(92) + "someone" + chr(92) + "repo"
POSIX_PATH = "/ho" + "me/someone/repo"


class ScanTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module("check_content_standards_under_test", SCRIPT)

    def kinds(self, text):
        return [h.kind for h in self.mod.scan_text("f.md", text)]

    def test_flags_em_dash(self):
        self.assertEqual(self.kinds(f"a {EM_DASH} b"), ["em-dash"])

    def test_flags_emoji(self):
        self.assertEqual(self.kinds(f"hello {EMOJI}"), ["emoji"])

    def test_flags_windows_user_path(self):
        self.assertEqual(self.kinds(f"see {WIN_PATH}"), ["user-path"])
        self.assertEqual(self.kinds("see C:/" + "Users/someone/x"), ["user-path"])

    def test_flags_posix_user_path(self):
        self.assertEqual(self.kinds(f"see {POSIX_PATH}"), ["user-path"])

    def test_reports_file_line_and_column(self):
        hit = self.mod.scan_text("docs/x.md", f"ok\nab{EM_DASH}")[0]
        self.assertEqual((hit.path, hit.line, hit.col), ("docs/x.md", 2, 3))

    def test_clean_text_and_allowed_glyphs_pass(self):
        text = "plain -- text, en-dash \u2013, middot \u00b7, placeholder /home/<name>/x, $HOME/x"
        self.assertEqual(self.kinds(text), [])


class RunOnFixtureRepoTests(unittest.TestCase):
    def run_in_repo(self, content: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "note.md").write_text(content, encoding="utf-8")
            subprocess.run(["git", "add", "note.md"], cwd=repo, check=True)
            return subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(repo)],
                capture_output=True, text=True, encoding="utf-8",
            )

    def test_exit_1_with_file_and_line_on_hit(self):
        result = self.run_in_repo(f"line one\nbad {EM_DASH} line\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("note.md:2:", result.stdout)

    def test_exit_0_on_clean_repo(self):
        self.assertEqual(self.run_in_repo("all fine\n").returncode, 0)


class RepositoryIsCleanTests(unittest.TestCase):
    def test_this_repository_passes(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
