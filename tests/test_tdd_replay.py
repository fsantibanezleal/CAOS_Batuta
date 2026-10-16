"""tdd check --replay: each red commit is checked out in a temporary worktree and its new tests must fail (D4)."""
import sys
import unittest
from pathlib import Path

from _support import SCRIPTS
from test_tdd_fixtures import CALC, TEST_CALC, TddCase, run_cli, shared_base, write_config

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

PASSING = "# REQ: REQ-CALC-002\nimport unittest\n\n\nclass P(unittest.TestCase):\n    def test_p(self):\n        self.assertEqual(1, 1)\n"
SLOW = "# REQ: REQ-CALC-003\nimport time\nimport unittest\n\n\nclass S(unittest.TestCase):\n    def test_s(self):\n        time.sleep(30)\n        self.assertEqual(1, 2)\n"


class ReplayBase(TddCase):
    def red_commit(self, repo, name, text, task="T-002", cfg=None):
        repo.write(f"tests/{name}", text)
        code, out = self.lock(repo, task, f"tests/{name}", cfg=cfg)
        self.assertEqual(code, 0, out)
        code, out = run_cli("--config", cfg or self.cfg, "tdd", "commit", "--repo", repo.root, "--red", task, "-m", "new tests",
                            f"tests/{name}", "--apply")
        self.assertEqual(code, 0, out)

    def assert_clean(self, repo, root=None):
        listing = repo.git("worktree", "list", "--porcelain")
        self.assertEqual(listing.count("worktree "), 1, listing)
        left = [p for p in (root or self.temp_root).iterdir()]
        self.assertEqual(left, [], f"leftover in the temp root: {left}")


class Replay(ReplayBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        shared = shared_base()
        cls.base, cls.shas = shared["repo"], shared["shas"]

    def clone(self):
        return self.base.clone_to(self.tmp / self.id().rsplit(".", 1)[-1])

    def test_the_compliant_history_replays_and_leaves_nothing_behind(self):
        code, out = self.check(self.base, "--replay")
        self.assertEqual(code, 0, out)
        self.assertIn(self.shas["red"][:7], out)
        self.assert_clean(self.base)

    def test_a_red_whose_new_tests_already_pass_fails_the_replay(self):
        repo = self.clone()
        self.red_commit(repo, "test_pass.py", PASSING)
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)   # the history rules alone cannot see it
        code, out = self.check(repo, "--replay")
        self.assertEqual(code, 1, out)
        self.assertIn("pass at the red commit", out)
        self.assertIn("tests/test_pass.py", out)
        self.assert_clean(repo)

    def test_the_replay_is_limited_to_the_tests_of_that_red(self):
        # the first red fails at its commit even though a later commit made everything green
        code, out = self.check(self.clone(), "--replay", "--range", f"{self.shas['red']}~1..{self.shas['red']}")
        self.assertEqual(code, 0, out)

    def test_a_replay_without_red_commits_warns_and_runs_nothing(self):
        repo = self.fresh("replay-no-red")
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        code, out = self.check(repo, "--replay")
        self.assertEqual(code, 2, out)
        self.assert_clean(repo)

    def test_a_red_that_adds_no_test_file_fails(self):
        repo = self.clone()
        repo.write("README.md", "changed\n")
        repo.commit("[red] T-003 no tests here\n", "README.md")
        code, out = self.check(repo, "--replay")
        self.assertEqual(code, 1, out)
        self.assertIn("no test file", out)

    def test_a_custom_test_command_with_the_tests_placeholder(self):
        folder = self.tmp / "custom-cmd"
        folder.mkdir()
        cfg = write_config(folder, self.temp_root, test_command="python -m unittest {tests}")
        code, out = self.check(self.base, "--replay", cfg=cfg)
        self.assertEqual(code, 1, out)   # the red fails; the head check wants a command that reports each test, and says so
        self.assertIn("configure tdd.test_command to report each test", out)
        self.assertIn("fails at the red commit", out)
        self.assert_clean(self.base)


class ReplayFailures(ReplayBase):
    def test_a_timed_out_replay_fails_and_removes_the_worktree(self):
        folder = self.tmp / "short"
        folder.mkdir()
        cfg = write_config(folder, self.temp_root, replay_timeout_seconds=2)
        repo = self.fresh("slow")
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        self.red_commit(repo, "test_slow.py", SLOW, cfg=cfg)
        code, out = self.check(repo, "--replay", cfg=cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("timed out", out)
        self.assert_clean(repo)

    def test_a_test_command_that_cannot_start_fails_and_removes_the_worktree(self):
        folder = self.tmp / "nocmd"
        folder.mkdir()
        cfg = write_config(folder, self.temp_root, test_command="no-such-test-runner-xyz")
        repo = self.fresh("nocmd")
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        self.red_commit(repo, "test_calc.py", TEST_CALC, task="T-001", cfg=cfg)
        code, out = self.check(repo, "--replay", cfg=cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("no-such-test-runner-xyz", out)
        self.assert_clean(repo)

    def test_a_red_that_fails_for_a_missing_module_counts_as_failing(self):
        repo = self.fresh("missing-module")
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        self.red_commit(repo, "test_calc.py", TEST_CALC, task="T-001")
        repo.write("calc.py", CALC)
        repo.commit("[green] T-001 implement\n", "calc.py")
        code, out = self.check(repo, "--replay")
        self.assertEqual(code, 0, out)
        self.assert_clean(repo)


if __name__ == "__main__":
    unittest.main()
