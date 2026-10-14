"""tdd check: the history rules, each violation as its own commit on a copy of a compliant history (D3)."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import SCRIPTS
from test_tdd_fixtures import CALC, CALC_REFACTORED, LOCK, SPEC, TEST_CALC, TddCase, message, run_cli, shared_base

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib import config  # noqa: E402
from batuta_lib import contract as core  # noqa: E402
from batuta_lib import tdd_history  # noqa: E402

REQUESTS = "specs/calc/test-change-requests.md"
HEADER = ("# Test change requests: calc\n\n| Id | Date | Test path | Requirement | Reason | Proposed change | Status | Decided by |\n"
          "|---|---|---|---|---|---|---|---|\n")


def requests(rid="CR-001", path="tests/test_calc.py", status="approved", by="felipe"):
    return HEADER + f"| {rid} | 2026-10-12 | {path} | REQ-CALC-001 | the oracle was wrong | fix the expected value | {status} | {by} |\n"


def commit_request_open_first(repo, text=None):
    """Commit a request file the way the harness makes one: opened in a commit, decided in a commit of its own (a row that is
    born approved is refused). `text` is the final file; None takes the file already written."""
    if text is None:
        text = (repo.root / REQUESTS).read_text(encoding="utf-8")
    opened = re.sub(r"\| (approved|rejected) \| [^|\n]* \|\n", "| open |  |\n", text)
    if opened != text:
        repo.write(REQUESTS, opened)
        repo.commit("docs: change request", REQUESTS)
    repo.write(REQUESTS, text)
    repo.commit("docs: change request decided" if opened != text else "docs: change request", REQUESTS)


EDITED = TEST_CALC.replace("calc.add(2, 3), 5)", "calc.add(2, 3), 5 + 0)")
EXTRA_OK = "import unittest\n\n\nclass E(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(1, 1)\n        self.assertEqual(2, 2)\n"
EXTRA_ONE = "import unittest\n\n\nclass E(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(1, 1)\n"


class CheckBase(TddCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        shared = shared_base()
        cls.base, cls.shas = shared["repo"], shared["shas"]

    def clone(self):
        return self.base.clone_to(self.tmp / self.id().rsplit(".", 1)[-1])

    def failing(self, repo, *needles, extra=()):
        code, out = self.check(repo, *extra)
        self.assertEqual(code, 1, out)
        low = out.lower()
        for needle in needles:
            self.assertIn(needle.lower(), low, out)
        return out

    def commit_request_then_spec(self, repo):
        commit_request_open_first(repo)
        repo.commit("docs: spec", "specs/calc/spec.md")

    def supersede_flow(self, repo, request_text=None, spec=True, trailer="CR-001", path="tests/test_calc.py"):
        """Commit the request (and spec change) and then the edit of the locked test with a superseding lock entry."""
        if request_text is not None:
            commit_request_open_first(repo, request_text)   # a decision is a commit of its own
        if spec:
            repo.write("specs/calc/spec.md", SPEC)
            repo.commit("docs: spec", "specs/calc/spec.md")
        repo.write(path, EDITED)
        code, out = run_cli("--config", self.cfg, "tdd", "lock", "--repo", repo.root, "--task", "T-001", path, "--apply",
                            "--supersedes", "--change-request", "CR-001")
        if request_text is not None and "approved" in request_text and "CR-001" in request_text and trailer:
            self.assertEqual(code, 0, out)
        return repo.commit(message("green", "T-001", "fix the oracle", trailer), path, LOCK)


class Compliant(CheckBase):
    def test_a_compliant_red_green_refactor_history_passes(self):
        code, out = self.check(self.base)
        self.assertEqual(code, 0, out)
        self.assertIn("OK", out)

    def test_json_output_is_a_c20_object(self):
        code, out = run_cli("--json", "--config", self.cfg, "tdd", "check", "--repo", self.base.root)
        doc = json.loads(out)
        sp = core.find_schema(config.contracts_dir(), "C20")
        self.assertEqual(core.validate_instance("C20", doc, core.load_schema(sp)), [])
        self.assertEqual((doc["area"], doc["verb"], doc["exit_code"]), ("tdd", "check", 0))

    def test_a_range_may_start_after_the_red(self):
        code, out = self.check(self.base, "--range", f"{self.shas['red']}..HEAD")
        self.assertEqual(code, 0, out)

    def test_the_replay_of_the_compliant_history_passes(self):
        code, out = self.check(self.base, "--replay")
        self.assertEqual(code, 0, out)
        self.assertIn("fails at", out)


class GrammarRules(CheckBase):
    def test_green_without_an_earlier_red_fails(self):
        repo = self.fresh("green-first")
        repo.write("calc.py", CALC)
        repo.commit(message("green", "T-001", "implement"), "calc.py")
        self.failing(repo, "no earlier [red]", "T-001")

    def test_a_green_for_another_task_than_the_red_fails(self):
        repo = self.clone()
        repo.write("calc.py", CALC_REFACTORED + "\n")
        repo.commit(message("green", "T-002", "other task"), "calc.py")
        self.failing(repo, "no earlier [red]", "T-002")

    def test_a_malformed_tagged_subject_fails(self):
        repo = self.clone()
        repo.write("calc.py", CALC_REFACTORED + "\n")
        repo.commit("[red] T-1 bad id\n", "calc.py")
        self.failing(repo, "C32")

    def test_untagged_commits_are_not_part_of_the_grammar(self):
        repo = self.clone()
        repo.write("README.md", "changed\n")
        repo.commit("docs: readme", "README.md")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_a_repository_without_a_red_commit_has_nothing_to_verify(self):
        repo = self.fresh("no-red")
        repo.write("calc.py", CALC)
        repo.commit("add calc", "calc.py")
        code, out = self.check(repo)
        self.assertEqual(code, 2, out)
        self.assertIn("WARN", out)
        self.assertIn("nothing to verify", out)
        self.assertNotIn("FAIL", out)

    def test_a_clean_merge_commit_passes_and_its_parents_are_checked(self):
        repo = self.clone()
        repo.git("checkout", "-q", "-b", "side")
        repo.write("notes.txt", "side\n")
        repo.commit("docs: side", "notes.txt")
        repo.git("checkout", "-q", "main")
        repo.write("README.md", "main\n")
        repo.commit("docs: main", "README.md")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge side", "side")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)

    def test_a_merge_does_not_hide_a_violation_on_a_branch(self):
        repo = self.clone()
        repo.git("checkout", "-q", "-b", "side")
        repo.write("tests/test_extra.py", "import unittest\n\n\n@unittest.skip('later')\nclass E(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n")
        repo.commit(message("refactor", "T-001", "add extra"), "tests/test_extra.py")
        repo.git("checkout", "-q", "main")
        repo.write("README.md", "main\n")
        repo.commit("docs: main", "README.md")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge side", "side")
        self.failing(repo, "weakening marker")


class LockedTestRules(CheckBase):
    def test_a_green_that_edits_a_locked_test_fails(self):
        repo = self.clone()
        repo.write("tests/test_calc.py", EDITED)
        repo.commit(message("green", "T-001", "make it pass"), "tests/test_calc.py")
        self.failing(repo, "touches locked test", "tests/test_calc.py")

    def test_a_refactor_that_edits_a_locked_test_fails_too(self):
        repo = self.clone()
        repo.write("tests/test_calc.py", EDITED)
        repo.commit(message("refactor", "T-001", "tidy"), "tests/test_calc.py")
        self.failing(repo, "touches locked test")

    def test_a_locked_test_edited_in_a_commit_with_no_tag_fails(self):
        repo = self.clone()
        repo.write("tests/test_calc.py", EDITED)
        repo.commit("quick fix", "tests/test_calc.py")
        self.failing(repo, "touches locked test")

    def test_a_hash_that_differs_at_head_fails(self):
        repo = self.clone()
        repo.write("tests/test_calc.py", EDITED)
        repo.commit("quick fix", "tests/test_calc.py")
        self.failing(repo, "does not match the lock")

    def test_the_lock_edited_in_place_fails(self):
        repo = self.clone()
        doc = json.loads((repo.root / LOCK).read_text(encoding="utf-8"))
        doc["entries"][0]["sha256"] = "0" * 64
        repo.write(LOCK, json.dumps(doc, indent=2) + "\n")
        repo.commit(message("refactor", "T-001", "adjust the lock"), LOCK)
        self.failing(repo, "append-only")

    def test_a_lock_entry_removed_fails(self):
        repo = self.clone()
        repo.write(LOCK, json.dumps({"contract_version": "1.0", "entries": []}) + "\n")
        repo.commit(message("refactor", "T-001", "drop the lock"), LOCK)
        self.failing(repo, "append-only")

    def test_a_deleted_lock_file_fails(self):
        repo = self.clone()
        repo.remove(LOCK)
        repo.commit(message("refactor", "T-001", "drop the lock"), LOCK)
        self.failing(repo, "lock file")

    def test_an_invalid_lock_file_fails_with_the_contract_reason(self):
        repo = self.clone()
        repo.write(LOCK, json.dumps({"contract_version": "1.0", "entries": [{"path": "x"}]}) + "\n")
        repo.commit(message("refactor", "T-001", "bad lock"), LOCK)
        self.failing(repo, "C07")

    def test_a_locked_test_deleted_fails(self):
        repo = self.clone()
        repo.git("rm", "-q", "tests/test_calc.py")
        repo.commit(message("refactor", "T-001", "drop the test"), "tests/test_calc.py")
        self.failing(repo, "touches locked test", "deleted")

    def test_a_renamed_locked_test_fails_without_an_approval(self):
        repo = self.clone()
        repo.git("mv", "tests/test_calc.py", "tests/test_calc_renamed.py")
        repo.commit(message("refactor", "T-001", "rename the test"), "tests/test_calc.py", "tests/test_calc_renamed.py")
        self.failing(repo, "touches locked test", "tests/test_calc.py")

    def test_crlf_files_hash_equal_on_a_crlf_checkout(self):
        repo = self.fresh("crlf")
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        repo.write("tests/test_calc.py", data=TEST_CALC.replace("\n", "\r\n").encode())
        self.lock(repo, "T-001", "tests/test_calc.py")
        code, out = run_cli("--config", self.cfg, "tdd", "commit", "--repo", repo.root, "--red", "T-001", "-m", "calc", "tests/test_calc.py", "--apply")
        self.assertEqual(code, 0, out)
        repo.write("calc.py", CALC)
        repo.commit(message("green", "T-001", "implement"), "calc.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_without_a_lock_file_nothing_is_locked_but_markers_are_still_checked(self):
        repo = self.fresh("nolock")
        repo.write("tests/test_calc.py", TEST_CALC)
        repo.commit("add the tests", "tests/test_calc.py")
        code, out = self.check(repo)
        self.assertEqual(code, 2, out)
        self.assertIn("nothing is locked", out)
        repo.write("tests/test_extra.py", "import unittest\n\n\n@unittest.skip('x')\nclass E(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n")
        repo.commit(message("refactor", "T-001", "extra"), "tests/test_extra.py")
        self.failing(repo, "weakening marker", "nothing is locked")


class WeakeningRules(CheckBase):
    def test_a_skip_marker_added_in_a_refactor_fails(self):
        repo = self.clone()
        repo.write("tests/test_extra.py", EXTRA_OK.replace("class E", "@unittest.skip('later')\nclass E"))
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
        self.failing(repo, "weakening marker", "unittest.skip")

    def test_an_expected_failure_and_xfail_are_weakening(self):
        for name, src in (("ef", EXTRA_OK.replace("    def test_a", "    @unittest.expectedFailure\n    def test_a")),
                          ("xf", "import pytest\n\n\n@pytest.mark.xfail\ndef test_a():\n    assert 1 == 1\n")):
            with self.subTest(name=name):
                repo = self.clone_named(name)
                repo.write("tests/test_extra.py", src)
                repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
                self.failing(repo, "weakening marker")

    def clone_named(self, name):
        return self.base.clone_to(self.tmp / f"{self.id().rsplit('.', 1)[-1]}-{name}")

    def test_a_skip_inside_a_string_is_not_weakening(self):
        repo = self.clone()
        repo.write("tests/test_extra.py", EXTRA_OK + "        self.assertIn('@unittest.skip', '@unittest.skip')\n")
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_javascript_only_and_skip_markers_fail(self):
        for marker in ("it.only", "xit", "test.todo"):
            with self.subTest(marker=marker):
                repo = self.clone_named(marker.replace(".", "-"))
                repo.write("web/a.test.js", f"{marker}('works', () => {{ expect(1).toBe(1); }});\n")
                repo.commit(message("refactor", "T-001", "web test"), "web/a.test.js")
                self.failing(repo, "weakening marker", marker)

    def test_an_assertion_removed_from_a_test_fails(self):
        repo = self.clone()
        repo.write("tests/test_extra.py", EXTRA_OK)
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)
        repo.write("tests/test_extra.py", EXTRA_ONE)
        repo.commit(message("refactor", "T-001", "trim extra tests"), "tests/test_extra.py")
        self.failing(repo, "assertion count dropped", "tests/test_extra.py")

    def test_a_javascript_assertion_removed_fails(self):
        repo = self.clone()
        repo.write("web/a.test.js", "it('a', () => {\n  expect(1).toBe(1);\n  expect(2).toBe(2);\n});\n")
        repo.commit(message("refactor", "T-001", "web test"), "web/a.test.js")
        repo.write("web/a.test.js", "it('a', () => {\n  expect(1).toBe(1);\n});\n")
        repo.commit(message("refactor", "T-001", "trim"), "web/a.test.js")
        self.failing(repo, "assertion count dropped")

    def test_a_test_file_that_stops_parsing_fails(self):
        repo = self.clone()
        repo.write("tests/test_extra.py", EXTRA_OK)
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
        repo.write("tests/test_extra.py", "def broken(:\n")
        repo.commit(message("refactor", "T-001", "break"), "tests/test_extra.py")
        self.failing(repo, "cannot parse")

    def test_an_added_test_file_with_assertions_is_fine(self):
        repo = self.clone()
        repo.write("tests/test_extra.py", EXTRA_OK)
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_a_renamed_unlocked_test_keeps_its_count(self):
        repo = self.clone()
        repo.write("tests/test_extra.py", EXTRA_OK)
        repo.commit(message("refactor", "T-001", "extra tests"), "tests/test_extra.py")
        repo.git("mv", "tests/test_extra.py", "tests/test_extra2.py")
        repo.commit(message("refactor", "T-001", "rename"), "tests/test_extra.py", "tests/test_extra2.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)


class OverrideRules(CheckBase):
    def test_an_approved_request_with_a_spec_change_exempts_a_locked_test_change(self):
        repo = self.clone()
        self.supersede_flow(repo, requests())
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_the_trailer_without_a_change_request_does_not_exempt(self):
        repo = self.clone()
        repo.write("tests/test_calc.py", EDITED)
        repo.commit(message("green", "T-001", "fix the oracle", "CR-009"), "tests/test_calc.py")
        self.failing(repo, "Test-Change-Approved", "CR-009")

    def test_an_open_or_rejected_request_does_not_exempt(self):
        for status, by in (("open", ""), ("rejected", "felipe")):
            with self.subTest(status=status):
                repo = self.base.clone_to(self.tmp / f"{self.id().rsplit('.', 1)[-1]}-{status}")
                repo.write(REQUESTS, requests(status=status, by=by))
                repo.write("specs/calc/spec.md", SPEC)
                self.commit_request_then_spec(repo)
                repo.write("tests/test_calc.py", EDITED)
                repo.commit(message("green", "T-001", "fix the oracle", "CR-001"), "tests/test_calc.py")
                self.failing(repo, "Test-Change-Approved", status)

    def test_a_request_for_another_test_path_does_not_exempt(self):
        repo = self.clone()
        repo.write(REQUESTS, requests(path="tests/test_other.py"))
        repo.write("specs/calc/spec.md", SPEC)
        self.commit_request_then_spec(repo)
        repo.write("tests/test_calc.py", EDITED)
        repo.commit(message("green", "T-001", "fix the oracle", "CR-001"), "tests/test_calc.py")
        self.failing(repo, "Test-Change-Approved", "tests/test_calc.py")

    def test_an_approved_request_without_a_spec_change_in_the_range_does_not_exempt(self):
        repo = self.clone()
        commit_request_open_first(repo, requests())
        repo.write("tests/test_calc.py", EDITED)
        repo.commit(message("green", "T-001", "fix the oracle", "CR-001"), "tests/test_calc.py")
        self.failing(repo, "spec")

    def test_a_request_file_that_breaks_c33_does_not_exempt(self):
        repo = self.clone()
        repo.write(REQUESTS, requests(by="-"))
        repo.write("specs/calc/spec.md", SPEC)
        self.commit_request_then_spec(repo)
        repo.write("tests/test_calc.py", EDITED)
        repo.commit(message("green", "T-001", "fix the oracle", "CR-001"), "tests/test_calc.py")
        self.failing(repo, "C33")

    def test_an_approved_override_exempts_a_deleted_locked_test(self):
        repo = self.clone()
        repo.write(REQUESTS, requests())
        repo.write("specs/calc/spec.md", SPEC)
        self.commit_request_then_spec(repo)
        repo.git("rm", "-q", "tests/test_calc.py")
        repo.commit(message("refactor", "T-001", "drop the test", "CR-001"), "tests/test_calc.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_an_approved_override_exempts_a_rename_when_the_new_path_is_locked(self):
        repo = self.clone()
        repo.write(REQUESTS, requests())
        repo.write("specs/calc/spec.md", SPEC)
        self.commit_request_then_spec(repo)
        repo.git("mv", "tests/test_calc.py", "tests/test_calc_renamed.py")
        code, out = self.lock(repo, "T-001", "tests/test_calc_renamed.py")
        self.assertEqual(code, 0, out)
        repo.commit(message("refactor", "T-001", "rename the test", "CR-001"), "tests/test_calc.py", "tests/test_calc_renamed.py", LOCK)
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_a_rename_whose_new_path_is_not_locked_fails_even_when_approved(self):
        repo = self.clone()
        repo.write(REQUESTS, requests())
        repo.write("specs/calc/spec.md", SPEC)
        self.commit_request_then_spec(repo)
        repo.git("mv", "tests/test_calc.py", "tests/test_calc_renamed.py")
        repo.commit(message("refactor", "T-001", "rename the test", "CR-001"), "tests/test_calc.py", "tests/test_calc_renamed.py")
        self.failing(repo, "tests/test_calc_renamed.py", "not locked")

    def test_a_superseding_entry_that_names_an_unapproved_request_fails(self):
        repo = self.clone()
        repo.write(REQUESTS, requests(status="open", by=""))
        repo.write("tests/test_calc.py", EDITED)
        doc = json.loads((repo.root / LOCK).read_text(encoding="utf-8"))
        from batuta_lib import test_markers as tm
        doc["entries"].append({"path": "tests/test_calc.py", "sha256": tm.normalized_sha256(EDITED.encode()), "task_id": "T-001",
                               "req_ids": ["REQ-CALC-001"], "locked_commit": repo.head(),
                               "supersedes": doc["entries"][0]["sha256"], "change_request": "CR-001"})
        repo.write(LOCK, json.dumps(doc, indent=2) + "\n")
        repo.commit(message("green", "T-001", "fix the oracle", "CR-001"), "tests/test_calc.py", LOCK, REQUESTS)
        self.failing(repo, "CR-001")


class LogParsing(unittest.TestCase):
    """The shape `git log -z --name-status` really prints: a NUL and a newline between the message and the first status."""

    RAW = ("\x1e" + "a" * 40 + "\x1f\x1f" + "first\n\x1f\0\nA\0a.txt\0"
           "\x1e" + "b" * 40 + "\x1f" + "a" * 40 + "\x1f" + "second\n\nbody\n\x1f\0\nR100\0a.txt\0b.txt\0D\0gone.txt\0"
           "\x1e" + "c" * 40 + "\x1f" + "b" * 40 + " " + "d" * 40 + "\x1fmerge\n\x1f\0")

    def test_statuses_paths_and_renames_are_read_right(self):
        proc = mock.Mock(stdout=self.RAW.encode())
        with mock.patch.object(tdd_history, "run", return_value=proc):
            commits = tdd_history.log(".", "HEAD")
        self.assertEqual([c.message for c in commits], ["first\n", "second\n\nbody\n", "merge\n"])
        self.assertEqual([(c.status, c.path, c.old) for c in commits[0].changes], [("A", "a.txt", None)])
        self.assertEqual([(c.status, c.path, c.old) for c in commits[1].changes], [("R", "b.txt", "a.txt"), ("D", "gone.txt", None)])
        self.assertEqual(commits[2].changes, [])
        self.assertEqual(len(commits[2].parents), 2)


class EnvironmentRules(CheckBase):
    def test_git_missing_from_the_path_exits_one_with_the_reason(self):
        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {"PATH": empty}):
            code, out = self.check(self.base)
        self.assertEqual(code, 1, out)
        self.assertIn("git", out.lower())
        self.assertIn("PATH", out)

    def test_a_git_older_than_2_30_is_refused(self):
        with mock.patch.object(tdd_history, "git_version", return_value=(2, 29, 3)):
            code, out = self.check(self.base)
        self.assertEqual(code, 1, out)
        self.assertIn("2.30", out)

    def test_a_directory_that_is_not_a_repository_fails_honestly(self):
        with tempfile.TemporaryDirectory(dir=self.tmp) as d:
            code, out = run_cli("--config", self.cfg, "tdd", "check", "--repo", d)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL", out)

    def test_a_bad_range_fails_honestly(self):
        code, out = self.check(self.base, "--range", "no-such-rev..HEAD")
        self.assertEqual(code, 1, out)

    def test_the_lock_path_may_come_from_the_configuration(self):
        folder = self.tmp / "cfg2"
        folder.mkdir()
        from test_tdd_fixtures import write_config
        cfg = write_config(folder, self.temp_root, lock_file=".batuta/other-lock.json")
        repo = self.fresh("custom-lock")
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        repo.write("tests/test_calc.py", TEST_CALC)
        code, out = self.lock(repo, "T-001", "tests/test_calc.py", cfg=cfg)
        self.assertEqual(code, 0, out)
        self.assertTrue((repo.root / ".batuta" / "other-lock.json").is_file())
        self.assertFalse((repo.root / LOCK).exists())


if __name__ == "__main__":
    unittest.main()
