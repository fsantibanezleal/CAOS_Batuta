"""tdd commit: the red, green and refactor helpers write C32 messages and refuse a staging that breaks the rule (D2)."""
import sys
import unittest

from _support import SCRIPTS
from test_tdd_fixtures import CALC, LOCK, TEST_CALC, TddCase, message, run_cli

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib import config  # noqa: E402
from batuta_lib import contract as core  # noqa: E402

C32 = core.load_schema(core.find_schema(config.contracts_dir(), "C32"))


class CommitHelpers(TddCase):
    def setUp(self):
        self.repo = self.fresh(self.id().rsplit(".", 1)[-1])
        self.repo.write("README.md", "x\n")
        self.repo.commit("init", "README.md")
        self.repo.write("tests/test_calc.py", TEST_CALC)

    def commit(self, kind, title, *paths, task="T-001", extra=(), apply=True):
        args = ["--config", self.cfg, "tdd", "commit", "--repo", self.repo.root, f"--{kind}", task, "-m", title, *paths, *extra]
        if apply:
            args.append("--apply")
        return run_cli(*args)

    def red(self):
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        return self.commit("red", "calc adds numbers", "tests/test_calc.py")

    def subject(self):
        return self.repo.git("log", "-1", "--format=%B").rstrip("\n")

    def committed_files(self):
        return set(self.repo.git("show", "--name-only", "--format=", "HEAD").split())

    def test_red_commits_the_tests_and_the_lock_with_a_c32_message(self):
        code, out = self.red()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.subject(), "[red] T-001 calc adds numbers")
        self.assertEqual(core.check_commit_message(self.subject(), C32), [])
        self.assertEqual(self.committed_files(), {"tests/test_calc.py", LOCK})

    def test_dry_run_does_not_commit_or_stage(self):
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        before = self.repo.head()
        code, out = self.commit("red", "calc adds numbers", "tests/test_calc.py", apply=False)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.repo.head(), before)
        self.assertEqual(self.repo.git("diff", "--cached", "--name-only").strip(), "")
        self.assertIn("[red] T-001 calc adds numbers", out)

    def test_red_refuses_a_path_that_is_not_a_test(self):
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        self.repo.write("calc.py", CALC)
        before = self.repo.head()
        code, out = self.commit("red", "calc adds numbers", "tests/test_calc.py", "calc.py")
        self.assertEqual(code, 1, out)
        self.assertIn("REFUSED", out)
        self.assertEqual(self.repo.head(), before)

    def test_red_refuses_without_the_lock_entry_of_each_test(self):
        before = self.repo.head()
        code, out = self.commit("red", "calc adds numbers", "tests/test_calc.py")
        self.assertEqual(code, 1, out)
        self.assertIn("lock", out)
        self.assertEqual(self.repo.head(), before)

    def test_red_refuses_when_something_else_is_already_staged(self):
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        self.repo.write("calc.py", CALC)
        self.repo.git("add", "calc.py")
        code, out = self.commit("red", "calc adds numbers", "tests/test_calc.py")
        self.assertEqual(code, 1, out)
        self.assertIn("staged", out)

    def test_green_commits_implementation_files(self):
        self.red()
        self.repo.write("calc.py", CALC)
        code, out = self.commit("green", "implement add", "calc.py")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.subject(), "[green] T-001 implement add")
        self.assertEqual(self.committed_files(), {"calc.py"})

    def test_green_refuses_a_locked_test(self):
        self.red()
        self.repo.write("tests/test_calc.py", TEST_CALC.replace("5)", "6)"))
        before = self.repo.head()
        code, out = self.commit("green", "make it pass", "tests/test_calc.py")
        self.assertEqual(code, 1, out)
        self.assertIn("locked", out)
        self.assertEqual(self.repo.head(), before)

    def test_green_and_refactor_refuse_the_lock_file(self):
        self.red()
        for kind in ("green", "refactor"):
            with self.subTest(kind=kind):
                code, out = self.commit(kind, "touch the lock", LOCK)
                self.assertEqual(code, 1, out)

    def test_green_without_an_earlier_red_for_the_task_is_refused(self):
        self.repo.write("calc.py", CALC)
        code, out = self.commit("green", "implement add", "calc.py")
        self.assertEqual(code, 1, out)
        self.assertIn("[red]", out)

    def test_refactor_commits_and_refuses_a_locked_test(self):
        self.red()
        self.repo.write("calc.py", CALC)
        self.commit("green", "implement add", "calc.py")
        self.repo.write("calc.py", CALC + "\n")
        code, out = self.commit("refactor", "tidy", "calc.py")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.subject(), "[refactor] T-001 tidy")
        self.repo.write("tests/test_calc.py", TEST_CALC + "\n")
        code, out = self.commit("refactor", "tidy tests", "tests/test_calc.py")
        self.assertEqual(code, 1, out)

    def test_a_title_that_makes_the_subject_longer_than_72_is_refused(self):
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        code, out = self.commit("red", "x" * 70, "tests/test_calc.py")
        self.assertEqual(code, 1, out)
        self.assertIn("72", out)

    def test_a_bad_task_id_is_refused(self):
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        code, out = self.commit("red", "calc", "tests/test_calc.py", task="T-1")
        self.assertEqual(code, 1, out)

    def test_the_approval_trailer_is_written_in_the_last_paragraph(self):
        self.red()
        self.repo.write("calc.py", CALC)
        code, out = self.commit("green", "implement add", "calc.py", extra=("--approved", "CR-001", "--body", "why not"))
        self.assertEqual(code, 0, out)
        text = self.subject()
        self.assertEqual(core.check_commit_message(text, C32), [])
        self.assertTrue(text.endswith("\n\nTest-Change-Approved: CR-001"), text)
        self.assertIn("why not", text)

    def test_a_malformed_approval_id_is_refused(self):
        self.red()
        self.repo.write("calc.py", CALC)
        code, out = self.commit("green", "implement add", "calc.py", extra=("--approved", "bad id"))
        self.assertEqual(code, 1, out)

    def test_exactly_one_kind_is_required(self):
        code, out = run_cli("--config", self.cfg, "tdd", "commit", "--repo", self.repo.root, "-m", "x", "calc.py")
        self.assertNotEqual(code, 0, out)


class MessageShape(unittest.TestCase):
    def test_the_fixture_message_helper_matches_c32(self):
        self.assertEqual(core.check_commit_message(message("red", "T-001", "t"), C32), [])
        self.assertEqual(core.check_commit_message(message("green", "T-001", "t", "CR-001"), C32), [])


if __name__ == "__main__":
    unittest.main()
