"""gate promote: merge only on green for the exact head SHA; local evidence for repositories without CI; never override."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import Case, run  # noqa: E402

HEAD = "a" * 40


def pr_json(checks, head=HEAD, mergeable="MERGEABLE"):
    return json.dumps({"headRefOid": head, "mergeable": mergeable, "statusCheckRollup": checks})


def check(name="ci", status="COMPLETED", conclusion="SUCCESS"):
    return {"name": name, "status": status, "conclusion": conclusion}


class FakeGh:
    """Stands in for the gh CLI: answers `pr view` with a JSON text and records every call."""

    def __init__(self, view_text, view_rc=0, merge_rc=0):
        self.calls, self.view_text, self.view_rc, self.merge_rc = [], view_text, view_rc, merge_rc

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["pr", "view"]:
            return self.view_rc, self.view_text
        if args[:2] == ["pr", "merge"]:
            return self.merge_rc, "merged" if self.merge_rc == 0 else "merge refused"
        return 1, "unexpected call"

    def merged(self):
        return [c for c in self.calls if c[:2] == ["pr", "merge"]]


class PullRequestMode(Case):
    def promote(self, gh, *extra):
        with mock.patch("batuta_lib.promote.run_gh", gh):
            return run("gate", "promote", "--repo", "owner/repo", "--pr", "7", *extra)

    def test_green_checks_dry_run_prints_the_merge_command_and_does_not_merge(self):
        gh = FakeGh(pr_json([check("ci"), check("lint")]))
        code, out = self.promote(gh)
        self.assertEqual(0, code, out)
        self.assertIn("gh pr merge 7 --repo owner/repo --merge --match-head-commit " + HEAD, out)
        self.assertEqual([], gh.merged())

    def test_apply_merges_pinned_to_the_checked_head(self):
        gh = FakeGh(pr_json([check()]))
        code, out = self.promote(gh, "--apply")
        self.assertEqual(0, code, out)
        self.assertEqual([["pr", "merge", "7", "--repo", "owner/repo", "--merge", "--match-head-commit", HEAD]], gh.merged())

    def test_a_failed_merge_command_is_a_failure(self):
        gh = FakeGh(pr_json([check()]), merge_rc=1)
        code, out = self.promote(gh, "--apply")
        self.assertEqual(1, code, out)

    def test_a_pending_check_is_never_green(self):
        for status in ("IN_PROGRESS", "QUEUED", "PENDING", "WAITING"):
            gh = FakeGh(pr_json([check("ci"), {"name": "slow", "status": status, "conclusion": ""}]))
            code, out = self.promote(gh, "--apply")
            self.assertEqual(2, code, (status, out))
            self.assertEqual([], gh.merged(), status)
            self.assertIn("pending", out)

    def test_a_failed_check_refuses_even_with_a_green_one_beside_it(self):
        gh = FakeGh(pr_json([check("ci"), check("tests", conclusion="FAILURE")]))
        code, out = self.promote(gh, "--apply")
        self.assertEqual(1, code, out)
        self.assertEqual([], gh.merged())
        self.assertIn("REFUSED", out)

    def test_other_non_success_conclusions_are_failures(self):
        for conclusion in ("CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE", "WHATEVER"):
            gh = FakeGh(pr_json([check(conclusion=conclusion)]))
            self.assertEqual(1, self.promote(gh, "--apply")[0], conclusion)
            self.assertEqual([], gh.merged(), conclusion)

    def test_a_skipped_required_check_is_not_evidence(self):
        gh = FakeGh(pr_json([check("ci"), check("gates", conclusion="SKIPPED")]))
        code, out = self.promote(gh, "--apply")
        self.assertEqual(1, code, out)
        self.assertEqual([], gh.merged())
        self.assertIn("SKIPPED", out)
        self.assertIn("not evidence", out)

    def test_a_neutral_check_is_not_evidence_either(self):
        gh = FakeGh(pr_json([check(conclusion="NEUTRAL")]))
        self.assertEqual(1, self.promote(gh, "--apply")[0])

    def test_a_status_context_is_classified_like_a_check(self):
        gh = FakeGh(pr_json([{"context": "ci/legacy", "state": "SUCCESS"}]))
        self.assertEqual(0, self.promote(gh)[0])
        gh = FakeGh(pr_json([{"context": "ci/legacy", "state": "PENDING"}]))
        self.assertEqual(2, self.promote(gh)[0])
        gh = FakeGh(pr_json([{"context": "ci/legacy", "state": "FAILURE"}]))
        self.assertEqual(1, self.promote(gh)[0])

    def test_a_required_check_that_never_ran_is_refused(self):
        gh = FakeGh(pr_json([check("lint")]))
        code, out = self.promote(gh, "--require", "batuta-gates", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("batuta-gates", out)
        self.assertEqual([], gh.merged())

    def test_a_required_check_that_is_green_is_accepted(self):
        gh = FakeGh(pr_json([check("lint"), check("batuta-gates")]))
        self.assertEqual(0, self.promote(gh, "--require", "batuta-gates")[0])

    def test_a_pull_request_without_checks_is_refused(self):
        gh = FakeGh(pr_json([]))
        code, out = self.promote(gh, "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("no checks", out)
        self.assertEqual([], gh.merged())

    def test_without_checks_local_evidence_for_the_exact_head_is_the_path(self):
        ev = self.tmp / "evidence.txt"
        ev.write_text(f"head {HEAD}\nRan 12 tests in 0.1s\n\nOK\n", encoding="utf-8")
        gh = FakeGh(pr_json([]))
        code, out = self.promote(gh, "--local-evidence", str(ev), "--apply")
        self.assertEqual(0, code, out)
        self.assertIn("local evidence", out)
        self.assertEqual(1, len(gh.merged()))

    def test_local_evidence_for_another_head_is_refused(self):
        ev = self.tmp / "evidence.txt"
        ev.write_text(f"head {'b' * 40}\nOK\n", encoding="utf-8")
        gh = FakeGh(pr_json([]))
        code, out = self.promote(gh, "--local-evidence", str(ev), "--apply")
        self.assertEqual(1, code, out)
        self.assertEqual([], gh.merged())

    def test_local_evidence_that_reports_a_failure_is_refused(self):
        ev = self.tmp / "evidence.txt"
        ev.write_text(f"head {HEAD}\nFAILED (failures=1)\n", encoding="utf-8")
        self.assertEqual(1, self.promote(FakeGh(pr_json([])), "--local-evidence", str(ev))[0])

    def test_local_evidence_never_overrides_a_failed_check(self):
        ev = self.tmp / "evidence.txt"
        ev.write_text(f"head {HEAD}\nOK\n", encoding="utf-8")
        gh = FakeGh(pr_json([check(conclusion="FAILURE")]))
        code, out = self.promote(gh, "--local-evidence", str(ev), "--apply")
        self.assertEqual(1, code, out)
        self.assertEqual([], gh.merged())

    def test_local_evidence_never_overrides_a_pending_check(self):
        ev = self.tmp / "evidence.txt"
        ev.write_text(f"head {HEAD}\nOK\n", encoding="utf-8")
        gh = FakeGh(pr_json([{"name": "ci", "status": "IN_PROGRESS", "conclusion": ""}]))
        code, out = self.promote(gh, "--local-evidence", str(ev), "--apply")
        self.assertEqual(2, code, out)
        self.assertEqual([], gh.merged())

    def test_a_head_that_moved_since_the_review_is_refused(self):
        gh = FakeGh(pr_json([check()], head="c" * 40))
        code, out = self.promote(gh, "--sha", "aaaaaaa", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("head moved", out)

    def test_a_conflicting_pull_request_is_refused_and_an_unknown_one_waits(self):
        self.assertEqual(1, self.promote(FakeGh(pr_json([check()], mergeable="CONFLICTING")))[0])
        code, out = self.promote(FakeGh(pr_json([check()], mergeable="UNKNOWN")))
        self.assertEqual(2, code, out)

    def test_gh_missing_or_failing_points_to_local_evidence(self):
        gh = FakeGh("gh could not run: not found", view_rc=1)
        code, out = self.promote(gh)
        self.assertEqual(1, code, out)
        self.assertIn("--local-evidence", out)

    def test_invalid_json_from_gh_is_a_failure(self):
        self.assertEqual(1, self.promote(FakeGh("not json"))[0])
        self.assertEqual(1, self.promote(FakeGh("[]"))[0])

    def test_json_output(self):
        gh = FakeGh(pr_json([check()]))
        code, out = self.promote(gh, "--json")
        doc = json.loads(out)
        self.assertEqual("promote", doc["verb"])
        self.assertEqual(0, doc["exit_code"])


class LocalMode(Case):
    """A repository without CI: a local branch promoted with evidence recorded for its exact head."""

    def setUp(self):
        super().setUp()
        self.proj = self.project()
        self.proj.write("a.txt", "a\n")
        self.proj.commit("base")
        self.proj.fake.checkout("task/x", create=True)
        self.proj.write("b.txt", "b\n")
        self.proj.commit("work")
        self.head = self.proj.head()
        self.proj.fake.checkout("develop")
        self.ev = self.tmp / "evidence.txt"
        self.ev.write_text(f"head {self.head}\nRan 3 tests in 0.1s\n\nOK\n", encoding="utf-8")

    def promote(self, *extra, evidence=True):
        args = ["gate", "promote", "--root", str(self.proj.root), "--branch", "task/x", "--into", "develop"]
        if evidence:
            args += ["--local-evidence", str(self.ev)]
        return run(*args, *extra)

    def test_dry_run_prints_the_merge_command_and_changes_nothing(self):
        before = self.proj.head()
        code, out = self.promote()
        self.assertEqual(0, code, out)
        self.assertIn("git merge --no-ff", out)
        self.assertIn(self.head, out)
        self.assertEqual(before, self.proj.head())

    def test_apply_merges_the_branch_when_the_target_is_checked_out(self):
        code, out = self.promote("--apply")
        self.assertEqual(0, code, out)
        sha, message, merged = self.proj.fake.merges[0]
        self.assertEqual(self.head, sha)
        self.assertEqual(2, len(self.proj.fake.commits[merged]["parents"]))
        self.assertEqual(merged, self.proj.head())

    def test_apply_never_switches_branches(self):
        self.proj.fake.checkout("task/x")
        code, out = self.promote("--apply")
        self.assertEqual(1, code, out)
        self.assertEqual([], self.proj.fake.merges)
        self.assertEqual("task/x", self.proj.fake.current)

    def test_evidence_for_another_commit_is_refused(self):
        self.ev.write_text(f"head {'d' * 40}\nOK\n", encoding="utf-8")
        before = self.proj.head()
        code, out = self.promote("--apply")
        self.assertEqual(1, code, out)
        self.assertEqual(before, self.proj.head())

    def test_evidence_that_names_an_abbreviated_sha_is_not_the_exact_head(self):
        self.ev.write_text(f"head {self.head[:10]}\nOK\n", encoding="utf-8")
        self.assertEqual(1, self.promote()[0])

    def test_evidence_with_a_failure_is_refused(self):
        self.ev.write_text(f"head {self.head}\nOK\nERROR: 2 tests failed\n", encoding="utf-8")
        self.assertEqual(1, self.promote()[0])

    def test_without_evidence_or_a_pull_request_nothing_is_promoted(self):
        code, out = self.promote(evidence=False)
        self.assertEqual(1, code, out)
        self.assertIn("--local-evidence", out)

    def test_a_missing_evidence_file_is_refused(self):
        self.ev.unlink()
        self.assertEqual(1, self.promote()[0])

    def test_a_dirty_working_tree_is_refused(self):
        self.proj.write("a.txt", "changed\n")
        code, out = self.promote("--apply")
        self.assertEqual(1, code, out)
        self.assertIn("uncommitted", out)

    def test_the_pinned_sha_must_be_the_head(self):
        self.assertEqual(1, self.promote("--sha", "1234567")[0])
        self.assertEqual(0, self.promote("--sha", self.head[:12])[0])

    def test_an_unknown_branch_is_refused(self):
        code, out = run("gate", "promote", "--root", str(self.proj.root), "--branch", "nope", "--into", "develop",
                        "--local-evidence", str(self.ev))
        self.assertEqual(1, code, out)


if __name__ == "__main__":
    unittest.main()
