"""The real `gate_model.Git` against a real scratch repository. Every other suite uses an in-memory stand-in because a git
process is slow on a loaded machine; this one test proves the real class answers the same questions the same way."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import run  # noqa: E402

from batuta_lib import gate_model  # noqa: E402


def sh(root, *args):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    return p.stdout.strip()


class RealGit(unittest.TestCase):
    def test_every_question_and_a_local_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            git = gate_model.Git()
            self.assertIsNone(git.info(root))                      # not a repository
            sh(root, "init", "-q", "-b", "develop")
            for k, v in (("user.email", "t@example.org"), ("user.name", "T"), ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
                sh(root, "config", k, v)
            (root / "specs").mkdir()
            (root / "specs" / "n.md").write_text("n\n", encoding="utf-8")
            (root / "code.py").write_text("x = 1\n", encoding="utf-8")
            sh(root, "add", "-A")
            sh(root, "commit", "-q", "-m", "one")
            first = sh(root, "rev-parse", "HEAD")
            prefix, head = git.info(root)
            self.assertEqual((prefix, head), ("", first))
            self.assertEqual([first], git.history(root, head))
            self.assertEqual([], git.dirty(root))
            (root / "specs" / "n.md").write_text("changed\n", encoding="utf-8")
            (root / "new.txt").write_text("u\n", encoding="utf-8")
            self.assertEqual(["new.txt", "specs/n.md"], sorted(git.dirty(root)))
            sh(root, "add", "-A")
            sh(root, "commit", "-q", "-m", "two")
            two = sh(root, "rev-parse", "HEAD")
            (root / "specs" / "m.md").write_text("m\n", encoding="utf-8")
            sh(root, "add", "-A")
            sh(root, "commit", "-q", "-m", "three: specs only")
            three = sh(root, "rev-parse", "HEAD")
            self.assertTrue(git.is_ancestor(root, first, three))
            self.assertFalse(git.is_ancestor(root, three, first))
            self.assertEqual(["new.txt", "specs/m.md", "specs/n.md"], sorted(git.changed(root, first, three)))
            self.assertEqual(two, git.last_commit(root, "new.txt"))
            self.assertEqual(0, git.count_since(root, two, three, "specs"))
            self.assertEqual(2, git.count_since(root, first, three, "code"))
            self.assertEqual("x = 1\n", git.show(root, first, "code.py"))
            self.assertIsNone(git.show(root, first, "absent.py"))
            self.assertEqual("develop", git.branch(root))
            self.assertEqual(three, git.rev(root, "HEAD"))
            self.assertIsNone(git.rev(root, "no-such-branch"))
            # a local promotion: a branch ahead of develop, evidence for its exact head, then --apply
            sh(root, "checkout", "-q", "-b", "task/x")
            (root / "b.txt").write_text("b\n", encoding="utf-8")
            sh(root, "add", "-A")
            sh(root, "commit", "-q", "-m", "work")
            tip = sh(root, "rev-parse", "HEAD")
            sh(root, "checkout", "-q", "develop")
            ev = Path(tmp) / "evidence.txt"
            ev.write_text(f"head {tip}\nOK\n", encoding="utf-8")
            gate_model.GIT = git
            code, out = run("gate", "promote", "--root", str(root), "--branch", "task/x", "--into", "develop",
                            "--local-evidence", str(ev), "--apply")
            self.assertEqual(0, code, out)
            self.assertEqual(2, len(sh(root, "log", "-1", "--format=%P").split()))
            self.assertTrue((root / "b.txt").exists())


if __name__ == "__main__":
    unittest.main()
