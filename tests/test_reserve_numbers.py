"""Area `reserve`: sequence-number reservations (a migration, a numbered document) recorded under a lock before a parallel
launch, so two parallel units never take the same number."""
import json
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_device_support import run  # noqa: E402

from batuta_lib import config  # noqa: E402
from batuta_lib.areas import reserve  # noqa: E402


class ReserveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.file = self.root / ".batuta" / "delegation" / "reservations.md"
        self.env = {"BATUTA_HOME": str(self.root / "bh")}

    def nxt(self, repo, kind, *extra, apply=False):
        code, out, _ = run("reserve", "next", repo, kind, "--root", str(self.root), *extra,
                           *(["--apply"] if apply else []), env=self.env)
        return code, out

    def number(self, repo, kind, *extra, apply=True):
        code, out = self.nxt(repo, kind, *extra, apply=apply)
        self.assertEqual(code, 0, out)
        return int(re.search(r"= (\d+)", out).group(1))

    def test_dry_run_prints_the_number_and_writes_nothing(self):
        code, out = self.nxt("api", "alembic")
        self.assertEqual(code, 0)
        self.assertIn("api:alembic = 1", out)
        self.assertIn("dry run", out)
        self.assertFalse(self.file.exists())

    def test_apply_creates_the_file_with_header_and_row(self):
        self.assertEqual(self.number("api", "alembic"), 1)
        text = self.file.read_text(encoding="utf-8")
        self.assertIn("| Repo | Kind | N |", text)
        self.assertIn("| api | alembic | 1 |", text)

    def test_numbers_increase_per_pair(self):
        self.assertEqual([self.number("api", "alembic") for _ in range(3)], [1, 2, 3])
        self.assertEqual(self.number("web", "alembic"), 1)
        self.assertEqual(self.number("api", "doc"), 1)

    def test_from_sets_the_start_but_never_goes_below_what_is_recorded(self):
        self.assertEqual(self.number("api", "alembic", "--from", "40"), 40)
        self.assertEqual(self.number("api", "alembic", "--from", "5"), 41)

    def test_a_duplicate_row_is_refused(self):
        self.number("api", "alembic")
        with self.assertRaises(reserve.ReserveError):
            reserve.add(self.file, "api", "alembic", 1)
        self.assertEqual(self.file.read_text(encoding="utf-8").count("| api | alembic | 1 |"), 1)

    def test_a_hand_edited_gap_is_respected(self):
        self.number("api", "alembic")
        self.file.write_text(self.file.read_text(encoding="utf-8") + "| api | alembic | 7 | 2026-10-11 |\n",
                             encoding="utf-8")
        self.assertEqual(self.number("api", "alembic"), 8)

    def test_concurrent_reservations_never_share_a_number(self):
        results, errors, lock = [], [], threading.Lock()

        def worker():
            try:
                n = reserve.reserve(self.file, "api", "alembic", None, True)
            except BaseException as exc:      # a worker's exception is reported, never lost with its thread
                with lock:
                    errors.append(repr(exc))
                return
            with lock:
                results.append(n)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), list(range(1, 13)))

    @unittest.skipUnless(sys.platform.startswith("win"), "the pending-deletion denial is a Windows behaviour")
    def test_a_lock_file_still_being_deleted_is_waited_for(self):
        # Windows: creating the lock file while the previous holder's copy is pending deletion fails with access denied
        # (PermissionError), not FileExistsError; the lock waits for it as for a held lock, within the same deadline
        real_open, calls = reserve.os.open, []

        def pending_once(path, flags, *args):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError(13, "Access is denied", str(path))
            return real_open(path, flags, *args)

        with mock.patch.object(reserve.os, "open", pending_once):
            self.assertEqual(reserve.reserve(self.file, "api", "alembic", None, True), 1)
        self.assertEqual(len(calls), 2)

    def test_a_lock_that_stays_denied_is_a_reserve_error(self):
        # Windows waits up to the deadline (a pending deletion clears); elsewhere a denied create is a folder that is not
        # writable, refused at once; either way the error names the lock and nothing else escapes
        def denied(path, flags, *args):
            raise PermissionError(13, "Access is denied", str(path))

        with mock.patch.object(reserve.os, "open", denied), mock.patch.object(reserve, "LOCK_TIMEOUT_S", 0.05):
            with self.assertRaises(reserve.ReserveError) as cm:
                reserve.reserve(self.file, "api", "alembic", None, True)
        self.assertIn("lock", str(cm.exception))
        self.assertIn("access denied", str(cm.exception).lower())
        self.assertFalse(self.file.exists())

    def test_list_prints_the_table_and_a_missing_file_is_empty(self):
        code, out, _ = run("reserve", "list", "--root", str(self.root), env=self.env)
        self.assertEqual(code, 0)
        self.assertIn("no reservations", out)
        self.number("api", "alembic")
        code, out, _ = run("reserve", "list", "--root", str(self.root), env=self.env)
        self.assertEqual(code, 0)
        self.assertIn("api alembic 1", out)

    def test_bad_input_is_refused(self):
        code, out = self.nxt("api", "alembic", "--from", "0")
        self.assertEqual(code, 1)
        self.assertIn("--from", out)
        code, out = self.nxt("a|b", "alembic")
        self.assertEqual(code, 1)
        self.assertFalse(self.file.exists())

    def test_a_stale_lock_times_out_with_an_exact_message_and_leaves_the_file_alone(self):
        lock = self.file.with_name(self.file.name + ".lock")
        lock.parent.mkdir(parents=True)
        lock.write_text("", encoding="utf-8")
        old = reserve.LOCK_TIMEOUT_S
        reserve.LOCK_TIMEOUT_S = 0.2
        try:
            code, out = self.nxt("api", "alembic", apply=True)
        finally:
            reserve.LOCK_TIMEOUT_S = old
        self.assertEqual(code, 1)
        self.assertRegex(out, r"lock .*reservations\.md\.lock")
        self.assertFalse(self.file.exists())

    def test_the_file_lives_under_the_configured_coordination_root(self):
        project = self.root / "p"
        (project / ".batuta").mkdir(parents=True)
        doc = config.default_config()
        doc["contract_version"] = "1.0"
        doc["coordination_root"] = "coord"
        doc["roots"] = {k: f"$BATUTA_{k.upper()}" for k in ("temp", "data", "worktrees")}
        (project / ".batuta" / "batuta.json").write_text(json.dumps(doc), encoding="utf-8")
        code, out, _ = run("reserve", "next", "api", "alembic", "--root", str(project), "--apply", env=self.env)
        self.assertEqual(code, 0, out)
        self.assertTrue((project / "coord" / "delegation" / "reservations.md").is_file())

    def test_json_output_is_the_c20_object(self):
        code, out, _ = run("reserve", "next", "api", "alembic", "--root", str(self.root), "--json", env=self.env)
        doc = json.loads(out)
        self.assertEqual((doc["area"], doc["verb"]), ("reserve", "next"))


if __name__ == "__main__":
    unittest.main()
