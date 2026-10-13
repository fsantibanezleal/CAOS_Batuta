"""tdd lock and tdd change-request: contract conformance first, then behaviour (D1)."""
import json
import sys
import unittest
from pathlib import Path

from _support import SCRIPTS
from test_tdd_fixtures import LOCK, TEST_CALC, TddCase, run_cli

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib import config  # noqa: E402
from batuta_lib import contract as core  # noqa: E402
from batuta_lib import test_markers as tm  # noqa: E402

CONTRACTS = config.contracts_dir()


def schema(cid):
    return core.load_schema(core.find_schema(CONTRACTS, cid))


class ContractFixtures(unittest.TestCase):
    """Every invalid fixture of the contracts this unit reads and writes is rejected for its stated reason."""

    def test_c07_c32_c33_invalid_fixtures_are_rejected_with_their_reason(self):
        for cid in ("C07", "C32", "C33"):
            sp = core.find_schema(CONTRACTS, cid)
            for fx in sorted((CONTRACTS / "fixtures" / cid).glob("invalid-*")):
                with self.subTest(fixture=f"{cid}/{fx.name}"):
                    why, expect = core.fixture_meta(fx)
                    self.assertTrue(why)
                    out = core.validate_file(fx, sp)
                    self.assertTrue(out)
                    if expect:
                        self.assertTrue(any(expect in e for e in out), out)

    def test_c07_c32_c33_valid_fixtures_are_accepted(self):
        for cid in ("C07", "C32", "C33"):
            sp = core.find_schema(CONTRACTS, cid)
            for fx in sorted((CONTRACTS / "fixtures" / cid).glob("valid-*")):
                with self.subTest(fixture=f"{cid}/{fx.name}"):
                    self.assertEqual(core.validate_file(fx, sp), [])


class LockWrites(TddCase):
    def setUp(self):
        self.repo = self.fresh(self.id().rsplit(".", 1)[-1])
        self.repo.write("README.md", "x\n")
        self.repo.commit("init", "README.md")
        self.repo.write("tests/test_calc.py", TEST_CALC)

    def lock_doc(self):
        return json.loads((self.repo.root / LOCK).read_text(encoding="utf-8"))

    def test_written_entries_validate_against_c07(self):
        code, out = self.lock(self.repo, "T-001", "tests/test_calc.py")
        self.assertEqual(code, 0, out)
        doc = self.lock_doc()
        self.assertEqual(core.validate_instance("C07", doc, schema("C07")), [])
        e = doc["entries"][0]
        self.assertEqual(e["path"], "tests/test_calc.py")
        self.assertEqual(e["task_id"], "T-001")
        self.assertEqual(e["req_ids"], ["REQ-CALC-001"])
        self.assertEqual(e["sha256"], tm.normalized_sha256(TEST_CALC.encode()))
        self.assertEqual(e["locked_commit"], self.repo.head())
        self.assertIn("NEW", out)

    def test_dry_run_writes_nothing(self):
        code, out = run_cli("--config", self.cfg, "tdd", "lock", "--repo", self.repo.root, "--task", "T-001", "tests/test_calc.py")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.repo.root / LOCK).exists())
        self.assertIn("NEW", out)

    def test_a_second_apply_is_same_and_changes_no_byte(self):
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        before = (self.repo.root / LOCK).read_bytes()
        code, out = self.lock(self.repo, "T-001", "tests/test_calc.py")
        self.assertEqual(code, 0, out)
        self.assertIn("SAME", out)
        self.assertEqual((self.repo.root / LOCK).read_bytes(), before)

    def test_the_hash_ignores_crlf(self):
        self.repo.write("tests/test_calc.py", data=TEST_CALC.replace("\n", "\r\n").encode())
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        self.assertEqual(self.lock_doc()["entries"][0]["sha256"], tm.normalized_sha256(TEST_CALC.encode()))

    def test_a_file_without_a_requirement_marker_locks_with_a_warning(self):
        self.repo.write("tests/test_plain.py", "import unittest\n")
        code, out = self.lock(self.repo, "T-002", "tests/test_plain.py")
        self.assertEqual(code, 2, out)
        self.assertIn("WARN", out)
        self.assertEqual(self.lock_doc()["entries"][0]["req_ids"], [])

    def test_unsafe_or_missing_paths_are_refused(self):
        for path in ("../outside.py", "/abs/test_x.py", "tests\\test_calc.py", "tests/missing.py"):
            with self.subTest(path=path):
                code, out = self.lock(self.repo, "T-001", path)
                self.assertEqual(code, 1, out)
                self.assertIn("REFUSED", out)
        self.assertFalse((self.repo.root / LOCK).exists())

    def test_a_task_id_that_is_not_t_nnn_is_refused(self):
        code, out = self.lock(self.repo, "task-1", "tests/test_calc.py")
        self.assertEqual(code, 1, out)
        self.assertFalse((self.repo.root / LOCK).exists())

    def test_a_changed_hash_needs_a_supersede_and_a_change_request(self):
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        self.repo.write("tests/test_calc.py", TEST_CALC + "\n# edit\n")
        code, out = self.lock(self.repo, "T-001", "tests/test_calc.py")
        self.assertEqual(code, 1, out)
        self.assertIn("REFUSED", out)
        self.assertEqual(len(self.lock_doc()["entries"]), 1)


def request_file(rows):
    head = ("# Test change requests: calc\n\n| Id | Date | Test path | Requirement | Reason | Proposed change | Status | Decided by |\n"
            "|---|---|---|---|---|---|---|---|\n")
    return head + "".join(f"| {' | '.join(r)} |\n" for r in rows)


def row(rid="CR-001", path="tests/test_calc.py", status="approved", by="felipe"):
    return [rid, "2026-10-12", path, "REQ-CALC-001", "the oracle was wrong", "fix the expected value", status, by]


class LockSupersede(TddCase):
    def setUp(self):
        self.repo = self.fresh(self.id().rsplit(".", 1)[-1])
        self.repo.write("README.md", "x\n")
        self.repo.commit("init", "README.md")
        self.repo.write("tests/test_calc.py", TEST_CALC)
        self.lock(self.repo, "T-001", "tests/test_calc.py")
        self.old = json.loads((self.repo.root / LOCK).read_text(encoding="utf-8"))["entries"][0]["sha256"]
        self.repo.write("tests/test_calc.py", TEST_CALC.replace("5)", "6)"))

    def supersede(self, cr="CR-001"):
        return self.lock(self.repo, "T-001", "tests/test_calc.py", extra=("--supersedes", "--change-request", cr))

    def test_no_request_file_refuses(self):
        code, out = self.supersede()
        self.assertEqual(code, 1, out)
        self.assertIn("REFUSED", out)

    def test_an_open_or_rejected_request_refuses(self):
        for status, by in (("open", ""), ("rejected", "felipe")):
            with self.subTest(status=status):
                self.repo.write("specs/calc/test-change-requests.md", request_file([row(status=status, by=by)]))
                code, out = self.supersede()
                self.assertEqual(code, 1, out)
                self.assertIn(status, out)

    def test_an_approved_request_for_another_test_path_refuses(self):
        self.repo.write("specs/calc/test-change-requests.md", request_file([row(path="tests/test_other.py")]))
        code, out = self.supersede()
        self.assertEqual(code, 1, out)
        self.assertIn("Test path", out)

    def test_an_unknown_request_id_refuses(self):
        self.repo.write("specs/calc/test-change-requests.md", request_file([row()]))
        code, out = self.supersede("CR-009")
        self.assertEqual(code, 1, out)

    def test_an_approved_request_writes_a_superseding_entry_and_keeps_the_old_one(self):
        self.repo.write("specs/calc/test-change-requests.md", request_file([row()]))
        code, out = self.supersede()
        self.assertEqual(code, 0, out)
        doc = json.loads((self.repo.root / LOCK).read_text(encoding="utf-8"))
        self.assertEqual(core.validate_instance("C07", doc, schema("C07")), [])
        self.assertEqual(len(doc["entries"]), 2)
        self.assertEqual(doc["entries"][0]["sha256"], self.old)
        new = doc["entries"][1]
        self.assertEqual(new["supersedes"], self.old)
        self.assertEqual(new["change_request"], "CR-001")
        self.assertEqual(new["sha256"], tm.normalized_sha256(TEST_CALC.replace("5)", "6)").encode()))
        self.assertIn("CHANGED", out)

    def test_superseding_a_path_that_is_not_locked_refuses(self):
        self.repo.write("tests/test_new.py", "import unittest\n")
        self.repo.write("specs/calc/test-change-requests.md", request_file([row(path="tests/test_new.py")]))
        code, out = self.lock(self.repo, "T-001", "tests/test_new.py", extra=("--supersedes", "--change-request", "CR-001"))
        self.assertEqual(code, 1, out)

    def test_change_request_without_supersedes_is_refused(self):
        code, out = self.lock(self.repo, "T-001", "tests/test_calc.py", extra=("--change-request", "CR-001"))
        self.assertEqual(code, 1, out)


class ChangeRequestNew(TddCase):
    def setUp(self):
        self.repo = self.fresh(self.id().rsplit(".", 1)[-1])
        self.repo.write("README.md", "x\n")
        self.repo.commit("init", "README.md")

    def new(self, *extra, apply=True, test="tests/test_calc.py"):
        args = ["--config", self.cfg, "tdd", "change-request", "new", "--repo", self.repo.root, "--test", test,
                "--requirement", "REQ-CALC-001", "--reason", "the oracle was wrong", "--proposed", "expect 6, not 5",
                "--feature", "calc", *extra]
        if apply:
            args.append("--apply")
        return run_cli(*args)

    def path(self):
        return self.repo.root / "specs" / "calc" / "test-change-requests.md"

    def test_creates_a_file_that_validates_against_c33_with_an_open_row(self):
        code, out = self.new()
        self.assertEqual(code, 0, out)
        sp = core.find_schema(CONTRACTS, "C33")
        self.assertEqual(core.validate_file(self.path(), sp), [])
        rows = core.read_table(self.path().read_text(encoding="utf-8"), core.load_sections_spec(sp)["tables"][0])[0]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Id"], "CR-001")
        self.assertEqual(rows[0]["Status"], "open")
        self.assertEqual(rows[0]["Decided by"], "")
        self.assertEqual(rows[0]["Test path"], "tests/test_calc.py")

    def test_a_second_request_gets_the_next_free_id_across_features(self):
        self.new()
        other = self.repo.root / "specs" / "web" / "test-change-requests.md"
        other.parent.mkdir(parents=True)
        other.write_text(request_file([row("CR-007", "tests/test_web.py", "open", "")]), encoding="utf-8")
        code, out = self.new()
        self.assertEqual(code, 0, out)
        text = self.path().read_text(encoding="utf-8")
        self.assertIn("CR-008", text)
        self.assertEqual(core.validate_file(self.path(), core.find_schema(CONTRACTS, "C33")), [])

    def test_dry_run_writes_nothing(self):
        code, out = self.new(apply=False)
        self.assertEqual(code, 0, out)
        self.assertFalse(self.path().exists())
        self.assertIn("CR-001", out)

    def test_it_never_writes_an_approved_status(self):
        self.new()
        self.new()
        text = self.path().read_text(encoding="utf-8")
        self.assertNotIn("approved", text)
        self.assertEqual(text.count("| open |"), 2)

    def test_pipes_and_newlines_in_text_do_not_break_the_table(self):
        code, out = run_cli("--config", self.cfg, "tdd", "change-request", "new", "--repo", self.repo.root, "--test",
                            "tests/test_calc.py", "--requirement", "REQ-CALC-001", "--reason", "a | b\nsecond line",
                            "--proposed", "x", "--feature", "calc", "--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(core.validate_file(self.path(), core.find_schema(CONTRACTS, "C33")), [])

    def test_a_bad_requirement_id_or_test_path_is_refused(self):
        code, out = run_cli("--config", self.cfg, "tdd", "change-request", "new", "--repo", self.repo.root, "--test",
                            "tests/test_calc.py", "--requirement", "REQ", "--reason", "r", "--proposed", "p", "--apply")
        self.assertEqual(code, 1, out)
        code, out = self.new(test="../x.py")
        self.assertEqual(code, 1, out)
        self.assertFalse(self.path().exists())

    def test_without_a_feature_the_flat_file_is_used(self):
        code, out = run_cli("--config", self.cfg, "tdd", "change-request", "new", "--repo", self.repo.root, "--test",
                            "tests/test_calc.py", "--requirement", "REQ-CALC-001", "--reason", "r", "--proposed", "p", "--apply")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.repo.root / "specs" / "test-change-requests.md").is_file())


if __name__ == "__main__":
    unittest.main()
