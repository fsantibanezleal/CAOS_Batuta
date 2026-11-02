"""The real-home guard ignores the entries the operating system owns on Windows (the registry hive and its logs) and keeps
comparing everything else."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _home_guard  # noqa: E402

OS_OWNED = ("ntuser.dat.LOG1", "ntuser.dat.LOG2", "NTUSER.DAT", "ntuser.ini", "NTUSER.DAT.LOG1", "ntuser.dat{abc}.TM.blf")


def seen_changes(windows, name, other=None):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / name).write_text("a", encoding="utf-8")
        if other:
            (home / other).write_text("a", encoding="utf-8")
        with mock.patch.object(_home_guard, "IS_WINDOWS", windows, create=True):
            before = _home_guard.snapshot(home)
            (home / name).write_text("longer content", encoding="utf-8")
            if other:
                (home / other).write_text("longer content", encoding="utf-8")
            return _home_guard.changed(before, _home_guard.snapshot(home))


class OperatingSystemEntries(unittest.TestCase):
    def test_on_windows_the_registry_hive_family_is_not_a_change(self):
        for name in OS_OWNED:
            self.assertEqual(seen_changes(True, name), [], name)

    def test_on_windows_another_entry_is_still_a_change(self):
        self.assertEqual(seen_changes(True, "ntuser.dat.LOG1", other="notes.txt"), ["notes.txt"])
        self.assertEqual(seen_changes(True, "ntuser_backup.txt"), ["ntuser_backup.txt"])

    def test_elsewhere_the_same_names_are_compared(self):
        self.assertEqual(seen_changes(False, "ntuser.dat.LOG1"), ["ntuser.dat.LOG1"])

    def test_a_real_file_write_is_seen_on_every_platform(self):
        for windows in (True, False):
            self.assertEqual(seen_changes(windows, "real-write.txt"), ["real-write.txt"])

    def test_a_write_under_the_batuta_folder_is_seen_on_every_platform(self):
        for windows in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                (home / ".batuta").mkdir()
                with mock.patch.object(_home_guard, "IS_WINDOWS", windows, create=True):
                    before = _home_guard.snapshot(home)
                    (home / ".batuta" / "x.json").write_text("{}", encoding="utf-8")
                    self.assertEqual(_home_guard.changed(before, _home_guard.snapshot(home)), [".batuta/x.json"])
