"""Installs the real-home guard before any other test module is imported (discovery loads modules in name order) and
tests the guard itself. See `_home_guard.py`."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _home_guard  # noqa: E402  (installs the guard)


class Guard(unittest.TestCase):
    def test_the_home_of_every_test_is_a_temporary_folder_not_the_real_one(self):
        self.assertNotEqual(Path.home().resolve(), _home_guard.real_home().resolve())
        self.assertEqual(Path(os.environ["USERPROFILE"]).resolve(), Path.home().resolve())
        self.assertEqual(Path(os.environ["HOME"]).resolve(), Path.home().resolve())

    def test_a_test_that_writes_into_the_home_default_fails_by_name(self):
        class Offender(unittest.TestCase):
            def test_writes(self):
                (Path.home() / ".batuta" / "temp").mkdir(parents=True)

        class Clean(unittest.TestCase):
            def test_quiet(self):
                pass

        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(Offender).run(result)
        self.assertEqual(len(result.failures), 1, result.failures)
        self.assertIn("home guard", result.failures[0][1])
        self.assertIn("test_writes", str(result.failures[0][0]))
        self.assertFalse((Path.home() / ".batuta").exists(), "the guard empties the temporary home")
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(Clean).run(result)
        self.assertEqual((len(result.failures), len(result.errors)), (0, 0))

    def test_a_change_of_the_real_home_is_seen_by_the_snapshot_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".batuta").mkdir()
            before = _home_guard.snapshot(home)
            (home / ".batuta" / "temp").mkdir()
            (home / "viaenv").mkdir()
            self.assertEqual(_home_guard.changed(before, _home_guard.snapshot(home)), [".batuta/temp", "viaenv"])

    def test_the_real_home_is_untouched_so_far(self):
        self.assertEqual(_home_guard.final_check(), [])


if __name__ == "__main__":
    unittest.main()
