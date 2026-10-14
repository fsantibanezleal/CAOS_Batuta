"""The Opus review of U4 (findings C-01 to C-05, M-01 to M-03, m-01 to m-03): each reproduction as a test on scratch git
repositories built here, every one run through the public CLI under the configured temp root."""
import json
import os
import sys
import unittest
from unittest import mock

from _support import SCRIPTS
from test_tdd_check import EDITED, EXTRA_OK, REQUESTS, CheckBase, commit_request_open_first, requests
from test_tdd_fixtures import CALC, LOCK, SPEC, TEST_CALC, message, run_cli, write_config

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib import config  # noqa: E402
from batuta_lib import contract as core  # noqa: E402
from batuta_lib import test_markers as tm  # noqa: E402
from batuta_lib.areas import tdd as tdd_area  # noqa: E402


class ReviewBase(CheckBase):
    def plain(self, *argv):
        """Run the CLI with no --config at all: the project file of the repository is what the area would find."""
        env = {k: v for k, v in os.environ.items() if k != "BATUTA_CONFIG"}
        env["BATUTA_HOME"] = str(self.tmp / "home")
        with mock.patch.dict(os.environ, env, clear=True):
            return run_cli(*argv)

    def commit_project_config(self, repo, **tdd):
        cfg = config.default_config({})
        cfg["roots"] = {"temp": str(self.tmp / "ptemp"), "data": str(self.tmp / "pdata"), "worktrees": str(self.tmp / "pwt")}
        cfg["tdd"] = tdd
        repo.write(".batuta/batuta.json", json.dumps(cfg, indent=2) + "\n")
        repo.commit("chore: project configuration", ".batuta/batuta.json")


class C01MergeCommits(ReviewBase):
    def merge_with(self, repo, resolve):
        repo.git("checkout", "-q", "-b", "side")
        repo.write("notes.txt", "side\n")
        repo.commit("docs: side", "notes.txt")
        repo.git("checkout", "-q", "main")
        repo.write("README.md", "main\n")
        repo.commit("docs: main", "README.md")
        repo.git("merge", "-q", "--no-ff", "--no-commit", "side")
        paths = resolve(repo)
        repo.commit("Merge side", *paths)

    def test_a_merge_that_rewrites_a_locked_test_and_its_lock_entry_fails(self):
        repo = self.clone()

        def resolve(r):
            r.write("tests/test_calc.py", EDITED)
            doc = json.loads((r.root / LOCK).read_text(encoding="utf-8"))
            doc["entries"][0]["sha256"] = tm.normalized_sha256(EDITED.encode())
            r.write(LOCK, json.dumps(doc, indent=2) + "\n")
            return ["tests/test_calc.py", LOCK]

        self.merge_with(repo, resolve)
        self.failing(repo, "merge")

    def test_a_merge_that_adds_a_skip_marker_of_its_own_fails(self):
        repo = self.clone()

        def resolve(r):
            r.write("tests/test_extra.py", EXTRA_OK.replace("class E", "@unittest.skip('later')\nclass E"))
            return ["tests/test_extra.py"]

        self.merge_with(repo, resolve)
        self.failing(repo, "weakening marker")

    def test_a_clean_merge_passes(self):
        repo = self.clone()
        self.merge_with(repo, lambda r: [])
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)


class C02ConfigFromTheBaseCommit(ReviewBase):
    def test_a_committed_config_cannot_move_the_lock_file(self):
        repo = self.clone()
        self.commit_project_config(repo, lock_file=".batuta/other-locks.json")
        repo.write("tests/test_calc.py", EDITED)
        code, out = self.plain("tdd", "lock", "--repo", repo.root, "--task", "T-001", "tests/test_calc.py", "--apply")
        self.assertEqual(code, 0, out)
        repo.commit(message("refactor", "T-001", "move the lock"), "tests/test_calc.py", ".batuta/other-locks.json")
        code, out = self.plain("tdd", "check", "--repo", repo.root)
        self.assertEqual(code, 1, out)
        self.assertIn("touches locked test", out)
        self.assertIn("tdd settings", out)

    def test_a_committed_config_cannot_empty_the_marker_list(self):
        repo = self.clone()
        self.commit_project_config(repo, markers=["nothing.matches"])
        repo.write("tests/test_extra.py", EXTRA_OK.replace("class E", "@unittest.skip('later')\nclass E"))
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
        code, out = self.plain("tdd", "check", "--repo", repo.root)
        self.assertEqual(code, 1, out)
        self.assertIn("weakening marker", out)

    def test_a_committed_config_cannot_replace_the_replay_command(self):
        repo = self.fresh("replay-command")
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        self.commit_project_config(repo, test_command='python -c "raise SystemExit(1)"')
        repo.write("tests/test_calc.py", TEST_CALC)
        repo.write("calc.py", CALC)
        code, out = self.plain("tdd", "lock", "--repo", repo.root, "--task", "T-001", "tests/test_calc.py", "--apply")
        self.assertEqual(code, 0, out)
        repo.commit(message("red", "T-001", "red that carries the code"), "tests/test_calc.py", "calc.py", ".batuta/test-locks.json")
        code, out = self.plain("tdd", "check", "--repo", repo.root, "--replay")
        self.assertEqual(code, 1, out)
        self.assertIn("pass at the red commit", out)

    def test_the_config_at_the_base_commit_is_honoured(self):
        repo = self.fresh("base-config")
        repo.write("README.md", "x\n")
        repo.write(".batuta/batuta.json", self._config_text(lock_file=".batuta/custom-locks.json"))
        repo.commit("init", "README.md", ".batuta/batuta.json")
        repo.write("tests/test_calc.py", TEST_CALC)
        code, out = self.plain("tdd", "lock", "--repo", repo.root, "--task", "T-001", "tests/test_calc.py", "--apply")
        self.assertEqual(code, 0, out)
        self.assertTrue((repo.root / ".batuta" / "custom-locks.json").is_file())
        code, out = self.plain("tdd", "commit", "--repo", repo.root, "--red", "T-001", "-m", "calc", "tests/test_calc.py", "--apply")
        self.assertEqual(code, 0, out)
        repo.write("tests/test_calc.py", EDITED)
        repo.commit(message("refactor", "T-001", "edit a locked test"), "tests/test_calc.py")
        code, out = self.plain("tdd", "check", "--repo", repo.root)
        self.assertEqual(code, 1, out)
        self.assertIn("touches locked test", out)

    def _config_text(self, **tdd):
        cfg = config.default_config({})
        cfg["roots"] = {"temp": str(self.tmp / "ptemp"), "data": str(self.tmp / "pdata"), "worktrees": str(self.tmp / "pwt")}
        cfg["tdd"] = tdd
        return json.dumps(cfg, indent=2) + "\n"

    def test_an_explicit_config_still_overrides(self):
        folder = self.tmp / "override"
        folder.mkdir()
        cfg = write_config(folder, self.temp_root, markers=["wip"])
        repo = self.clone()
        repo.write("tests/test_extra.py", "import unittest\n\n\n@wip\nclass E(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n")
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
        code, out = self.check(repo, cfg=cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("'wip'", out)


class C03RedTestsAreLocked(ReviewBase):
    def test_a_red_test_that_was_never_locked_fails_the_static_check(self):
        repo = self.clone()
        repo.write("tests/test_sub.py", "# REQ: REQ-CALC-002\nimport unittest\n\n\nclass S(unittest.TestCase):\n    def test_s(self):\n"
                                        "        self.assertEqual(1, 2)\n")
        repo.commit(message("red", "T-002", "sub"), "tests/test_sub.py")
        self.failing(repo, "not locked", "tests/test_sub.py")

    def test_a_red_test_locked_with_another_content_fails(self):
        repo = self.clone()
        repo.write("tests/test_sub.py", "# REQ: REQ-CALC-002\nimport unittest\n\n\nclass S(unittest.TestCase):\n    def test_s(self):\n"
                                        "        self.assertEqual(1, 2)\n")
        code, out = self.lock(repo, "T-002", "tests/test_sub.py")
        self.assertEqual(code, 0, out)
        repo.write("tests/test_sub.py", "import unittest\n\n\nclass S(unittest.TestCase):\n    def test_s(self):\n        self.assertEqual(3, 3)\n")
        repo.commit(message("red", "T-002", "sub"), "tests/test_sub.py", LOCK)
        self.failing(repo, "not locked", "tests/test_sub.py")


class C04RedHasFailingTests(ReviewBase):
    def test_a_red_without_a_test_file_fails_the_static_check(self):
        repo = self.clone()
        repo.write("notes.md", "nothing here\n")
        repo.commit(message("red", "T-002", "notes only"), "notes.md")
        self.failing(repo, "red", "test")

    def test_a_red_whose_test_file_holds_no_test_fails_the_replay(self):
        repo = self.fresh("empty-red")
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        repo.write("tests/test_calc.py", "# REQ: REQ-CALC-001\nimport unittest\n")
        code, out = self.lock(repo, "T-001", "tests/test_calc.py")
        self.assertEqual(code, 0, out)
        code, out = run_cli("--config", self.cfg, "tdd", "commit", "--repo", repo.root, "--red", "T-001", "-m", "empty", "tests/test_calc.py", "--apply")
        self.assertEqual(code, 0, out)
        self.failing(repo, "no test", extra=("--replay",))


class C05ReplayUsesTheProjectsOwnCommand(ReviewBase):
    FILES = {
        "tests/__init__.py": "",
        "tests/unit/__init__.py": "",
        "tests/unit/helpers.py": "EXPECTED = 5\n",
        "tests/unit/test_add.py": "# REQ: REQ-CALC-001\nimport unittest\n\nimport calc\n\nfrom .helpers import EXPECTED\n\n\n"
                                  "class AddTests(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(calc.add(2, 3), EXPECTED)\n",
    }

    def red_repo(self, name, with_code):
        repo = self.fresh(name)
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        for path, text in self.FILES.items():
            repo.write(path, text)
        if with_code:
            repo.write("calc.py", CALC)
        code, out = self.lock(repo, "T-001", "tests/unit/test_add.py")
        self.assertEqual(code, 0, out)
        repo.commit(message("red", "T-001", "package test"), "tests/__init__.py", "tests/unit/__init__.py", "tests/unit/helpers.py",
                    "tests/unit/test_add.py", LOCK, *(["calc.py"] if with_code else []))
        return repo

    def test_a_red_that_carries_the_code_does_not_pass_the_replay_through_a_changed_import_root(self):
        repo = self.red_repo("pkg-carries-code", True)
        self.failing(repo, "pass at the red commit", extra=("--replay",))

    def test_a_package_relative_test_that_fails_for_want_of_the_code_is_a_red(self):
        repo = self.red_repo("pkg-red", False)
        code, out = self.check(repo, "--replay")
        self.assertEqual(code, 0, out)
        self.assertIn("fails at the red commit", out)


class M01SelfApproval(ReviewBase):
    def commit_request(self, repo, text):
        commit_request_open_first(repo, text)

    def edit_with_trailer(self, repo):
        repo.write("specs/calc/spec.md", SPEC)
        repo.write("tests/test_calc.py", EDITED)
        code, out = run_cli("--config", self.cfg, "tdd", "lock", "--repo", repo.root, "--task", "T-001", "tests/test_calc.py",
                            "--apply", "--supersedes", "--change-request", "CR-001")
        return code, out

    def test_flipping_the_open_row_to_approved_in_the_commit_that_uses_it_fails(self):
        repo = self.clone()
        self.commit_request(repo, requests(status="open", by=""))
        repo.write(REQUESTS, requests(status="approved", by="felipe"))
        code, out = self.edit_with_trailer(repo)
        self.assertEqual(code, 0, out)
        repo.commit(message("green", "T-001", "fix the oracle", "CR-001"), REQUESTS, "specs/calc/spec.md", "tests/test_calc.py", LOCK)
        self.failing(repo, "Test-Change-Approved", "CR-001")

    def test_a_row_approved_in_an_earlier_commit_exempts(self):
        repo = self.clone()
        self.commit_request(repo, requests())
        repo.write("specs/calc/spec.md", SPEC)
        repo.commit("docs: spec", "specs/calc/spec.md")
        code, out = self.edit_with_trailer(repo)
        self.assertEqual(code, 0, out)
        repo.commit(message("green", "T-001", "fix the oracle", "CR-001"), "tests/test_calc.py", LOCK)
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_a_commit_that_decides_a_request_and_changes_another_path_fails(self):
        repo = self.clone()
        self.commit_request(repo, requests(status="open", by=""))
        repo.write(REQUESTS, requests(status="approved", by="felipe"))
        repo.write("specs/calc/spec.md", SPEC)
        repo.commit("docs: approve and spec", REQUESTS, "specs/calc/spec.md")
        self.failing(repo, "decides request CR-001")

    def test_a_commit_that_only_decides_a_request_is_fine(self):
        repo = self.clone()
        self.commit_request(repo, requests(status="open", by=""))
        repo.write(REQUESTS, requests(status="approved", by="felipe"))
        repo.commit("docs: approve", REQUESTS)
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)


class M01Decide(ReviewBase):
    """`tdd change-request decide <id> approve|reject` reads the person's confirmation from the console."""

    def setUp(self):
        self.repo = self.fresh(self.id().rsplit(".", 1)[-1])
        self.repo.write("README.md", "x\n")
        self.repo.commit("init", "README.md")
        code, out = run_cli("--config", self.cfg, "tdd", "change-request", "new", "--repo", self.repo.root, "--test", "tests/test_calc.py",
                            "--requirement", "REQ-CALC-001", "--reason", "wrong oracle", "--proposed", "expect 6", "--feature", "calc", "--apply")
        self.assertEqual(code, 0, out)
        self.file = self.repo.root / REQUESTS

    def decide(self, verb, typed, rid="CR-001", apply=True, reader=None):
        args = ["--config", self.cfg, "tdd", "change-request", "decide", "--repo", self.repo.root, rid, verb]
        if apply:
            args.append("--apply")
        patched = reader or mock.Mock(return_value=typed)
        with mock.patch.object(tdd_area, "read_console", patched):
            return run_cli(*args), patched

    def rows(self):
        sp = core.find_schema(config.contracts_dir(), "C33")
        return core.read_table(self.file.read_text(encoding="utf-8"), core.load_sections_spec(sp)["tables"][0])[0]

    def test_the_typed_phrase_approves_and_records_who_decided(self):
        (code, out), reader = self.decide("approve", "approve CR-001")
        self.assertEqual(code, 0, out)
        row = self.rows()[0]
        self.assertEqual(row["Status"], "approved")
        self.assertNotIn(row["Decided by"].strip(), ("", "-"))
        self.assertEqual(core.validate_file(self.file, core.find_schema(config.contracts_dir(), "C33")), [])
        self.assertIn("CR-001", reader.call_args[0][0])

    def test_the_typed_phrase_rejects(self):
        (code, out), _ = self.decide("reject", "reject CR-001")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.rows()[0]["Status"], "rejected")

    def test_a_wrong_phrase_is_refused_and_nothing_changes(self):
        before = self.file.read_bytes()
        for typed in ("approve", "yes", "approve CR-002", "reject CR-001", ""):
            with self.subTest(typed=typed):
                (code, out), _ = self.decide("approve", typed)
                self.assertEqual(code, 1, out)
                self.assertIn("REFUSED", out)
        self.assertEqual(self.file.read_bytes(), before)

    def test_without_a_console_it_refuses(self):
        before = self.file.read_bytes()
        (code, out), _ = self.decide("approve", None, reader=mock.Mock(side_effect=tdd_area.ConsoleUnavailable("no console")))
        self.assertEqual(code, 1, out)
        self.assertIn("console", out)
        self.assertEqual(self.file.read_bytes(), before)

    def test_a_decided_or_unknown_request_is_refused(self):
        self.decide("approve", "approve CR-001")
        (code, out), _ = self.decide("reject", "reject CR-001")
        self.assertEqual(code, 1, out)
        (code, out), _ = self.decide("approve", "approve CR-009", rid="CR-009")
        self.assertEqual(code, 1, out)

    def test_a_dry_run_asks_nothing_and_changes_nothing(self):
        before = self.file.read_bytes()
        (code, out), reader = self.decide("approve", "approve CR-001", apply=False)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.file.read_bytes(), before)
        reader.assert_not_called()


class M03RangeArgument(ReviewBase):
    def test_a_range_that_looks_like_a_git_option_is_refused_and_writes_nothing(self):
        repo = self.clone()
        code, out = self.check(repo, "--range=--output=INJECTED..HEAD")
        self.assertEqual(code, 1, out)
        self.assertFalse((repo.root / "INJECTED").exists())
        self.assertFalse((repo.root / "INJECTED..HEAD").exists())

    def test_a_range_without_commits_is_a_failure_not_a_pass(self):
        repo = self.clone()
        code, out = self.check(repo, "--range", "HEAD..HEAD")
        self.assertEqual(code, 1, out)
        self.assertIn("no commits", out)


class MinorFindings(ReviewBase):
    def test_m01_a_red_may_hold_tests_and_the_lock_only(self):
        repo = self.clone()
        repo.write("tests/test_sub.py", "# REQ: REQ-CALC-002\nimport unittest\n\n\nclass S(unittest.TestCase):\n    def test_s(self):\n"
                                        "        self.assertEqual(1, 2)\n")
        code, out = self.lock(repo, "T-002", "tests/test_sub.py")
        self.assertEqual(code, 0, out)
        repo.write("calc.py", CALC + "\n")
        repo.commit(message("red", "T-002", "sub plus code"), "tests/test_sub.py", LOCK, "calc.py")
        self.failing(repo, "calc.py")

    def test_m02_a_line_ending_change_of_a_locked_test_is_not_a_change(self):
        repo = self.clone()
        repo.write("tests/test_calc.py", data=TEST_CALC.replace("\n", "\r\n").encode())
        repo.commit(message("refactor", "T-001", "line endings"), "tests/test_calc.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_m03_a_green_may_not_add_lock_entries(self):
        repo = self.clone()
        repo.write("tests/test_sub.py", "# REQ: REQ-CALC-002\nimport unittest\n\n\nclass S(unittest.TestCase):\n    def test_s(self):\n"
                                        "        self.assertEqual(1, 1)\n")
        code, out = self.lock(repo, "T-001", "tests/test_sub.py")
        self.assertEqual(code, 0, out)
        repo.commit(message("green", "T-001", "lock a test that never had a red"), "tests/test_sub.py", LOCK)
        self.failing(repo, "lock file")

    def test_m02_review_conftest_that_skips_every_test_fails(self):
        repo = self.clone()
        repo.write("tests/conftest.py", "import pytest\n\n\ndef pytest_collection_modifyitems(items):\n    for item in items:\n"
                                        "        item.add_marker(pytest.mark.skip(reason='x'))\n")
        repo.commit(message("refactor", "T-001", "conftest"), "tests/conftest.py")
        self.failing(repo, "weakening marker")

    def test_c07_a_test_renamed_to_a_name_that_is_no_longer_discovered_drops_its_assertions(self):
        repo = self.clone()
        repo.write("tests/test_a.py", EXTRA_OK)
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_a.py")
        repo.git("mv", "tests/test_a.py", "tests/helper_a.py")
        repo.commit(message("refactor", "T-001", "rename"), "tests/test_a.py", "tests/helper_a.py")
        self.failing(repo, "assertion count dropped")

    def test_c06_an_aliased_skip_in_a_refactor_fails_through_the_cli(self):
        repo = self.clone()
        repo.write("tests/test_extra.py", "import unittest as u\n\n\n@u.skip('later')\nclass E(u.TestCase):\n    def test_a(self):\n"
                                          "        self.assertTrue(True)\n")
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
        self.failing(repo, "weakening marker")


if __name__ == "__main__":
    unittest.main()
