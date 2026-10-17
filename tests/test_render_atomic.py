"""The shared atomic writer retries `os.replace` a few times, with a short backoff, on a transient Windows access error
(`PermissionError`, `[WinError 5]`) held by a scanner or an indexer, then raises; it leaves no temp file behind."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "batuta" / "scripts"))

from batuta_lib import render  # noqa: E402


class Flaky:
    """An `os.replace` stand-in that fails `n` times with `error`, then really replaces."""

    def __init__(self, n, error=None):
        import os
        self.n, self.calls, self.real = n, 0, os.replace
        self.error = error or PermissionError(13, "Access is denied")

    def __call__(self, src, dst):
        self.calls += 1
        if self.calls <= self.n:
            raise self.error
        return self.real(src, dst)


class AtomicWrite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.sleeps = []

    def write(self, flaky, fn=render.write_atomic, data="x\n"):
        with mock.patch.object(render, "_replace", flaky), mock.patch.object(render, "_sleep", self.sleeps.append):
            return fn(self.dir / "f.txt", data)

    def test_a_transient_failure_is_retried_and_the_write_succeeds(self):
        flaky = Flaky(2)
        self.write(flaky)
        self.assertEqual((self.dir / "f.txt").read_text(encoding="utf-8"), "x\n")
        self.assertEqual(flaky.calls, 3)
        self.assertEqual(len(self.sleeps), 2)
        self.assertTrue(all(0 < s <= 0.5 for s in self.sleeps), self.sleeps)
        self.assertEqual(self.sleeps, sorted(self.sleeps), "the backoff does not shrink")

    def test_winerror_5_as_a_plain_oserror_is_retried_too(self):
        error = OSError(13, "Access is denied")
        error.winerror = 5
        flaky = Flaky(1, error)
        self.write(flaky)
        self.assertEqual(flaky.calls, 2)

    def test_a_persistent_failure_is_raised_after_a_bounded_number_of_tries_and_leaves_no_temp_file(self):
        flaky = Flaky(10 ** 6)
        with self.assertRaises(PermissionError):
            self.write(flaky)
        self.assertTrue(2 <= flaky.calls <= 10, flaky.calls)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_another_error_is_not_retried(self):
        flaky = Flaky(10 ** 6, FileNotFoundError(2, "gone"))
        with self.assertRaises(FileNotFoundError):
            self.write(flaky)
        self.assertEqual(flaky.calls, 1)

    def test_the_bytes_variant_has_the_same_retry_and_keeps_the_bytes_exactly(self):
        flaky = Flaky(1)
        self.write(flaky, render.write_atomic_bytes, b"a\r\nb\x00")
        self.assertEqual((self.dir / "f.txt").read_bytes(), b"a\r\nb\x00")
        self.assertEqual(flaky.calls, 2)

    def test_text_is_still_written_with_lf_endings(self):
        self.write(Flaky(0), data="a\r\nb\r\n")
        self.assertEqual((self.dir / "f.txt").read_bytes(), b"a\nb\n")


if __name__ == "__main__":
    unittest.main()


class EveryWriterUsesTheSharedRetry(unittest.TestCase):
    """The settings merge and the device area wrote with `os.replace` directly; both now go through the shared helper, so one
    transient access error does not fail the write."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def patched(self, flaky):
        sleeps = []
        return mock.patch.object(render, "_replace", flaky), mock.patch.object(render, "_sleep", sleeps.append)

    def test_the_settings_merge_write_survives_one_transient_error(self):
        from batuta_lib import settings_merge as sm
        flaky = Flaky(1)
        target = self.dir / "settings.json"
        a, b = self.patched(flaky)
        with a, b:
            sm._write_atomic(target, {"model": "opus"}, None, sm._read)
        self.assertEqual(flaky.calls, 2, "the write went through the shared helper and was retried once")
        self.assertIn("opus", target.read_text(encoding="utf-8"))
        self.assertEqual([p.name for p in self.dir.iterdir()], ["settings.json"])

    def test_the_device_area_write_survives_one_transient_error(self):
        from batuta_lib.areas import device
        flaky = Flaky(1)
        target = self.dir / "sub" / "f.bin"
        a, b = self.patched(flaky)
        with a, b:
            device._write_bytes(target, b"\x00\x01")
        self.assertEqual(flaky.calls, 2)
        self.assertEqual(target.read_bytes(), b"\x00\x01")
        self.assertEqual([p.name for p in target.parent.iterdir()], ["f.bin"])

    def test_the_settings_merge_still_refuses_a_file_that_changed_meanwhile(self):
        from batuta_lib import settings_merge as sm
        target = self.dir / "settings.json"
        target.write_text("{}", encoding="utf-8")
        with self.assertRaises(sm._Changed):
            sm._write_atomic(target, {"a": 1}, b"something else", sm._read)
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["settings.json"])
