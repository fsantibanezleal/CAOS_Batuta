"""The install manifest (`install_manifest.py`): what init wrote, its hash and the backup of what it replaced; the state of
each file against its hash (SAME, DIFFERENT, MISSING); line endings do not change a hash."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import sha  # noqa: E402,F401

from batuta_lib import install_manifest as im  # noqa: E402


class Hashing(unittest.TestCase):
    def test_hash_ignores_line_endings(self):
        self.assertEqual(im.sha256_bytes(b"a\r\nb\r\n"), im.sha256_bytes(b"a\nb\n"))
        self.assertNotEqual(im.sha256_bytes(b"a\nb\n"), im.sha256_bytes(b"a\nc\n"))
        self.assertEqual(len(im.sha256_bytes(b"")), 64)


class ManifestFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = self.root / ".batuta" / "installed.json"

    def test_record_save_and_load_round_trip(self):
        m = im.Manifest(self.path, "project", {"project": str(self.root)}, {"project_name": "x"})
        m.record("project", "a/b.txt", b"hello\n", backup="b.txt.bak-20261015-101010")
        m.record_dir("project", "a")
        m.save()
        loaded = im.Manifest.load(self.path)
        self.assertEqual(loaded.kind, "project")
        self.assertEqual(loaded.variables, {"project_name": "x"})
        entry = loaded.entry("project", "a/b.txt")
        self.assertEqual(entry["sha256"], im.sha256_bytes(b"hello\n"))
        self.assertEqual(entry["backup"], "b.txt.bak-20261015-101010")
        self.assertEqual(loaded.dirs, [{"base": "project", "path": "a"}])
        self.assertTrue(json.loads(self.path.read_text(encoding="utf-8")))

    def test_save_is_atomic_lf_and_stable(self):
        m = im.Manifest(self.path, "user", {"deploy": str(self.root)})
        m.record("deploy", "x.txt", b"1")
        m.save()
        first = self.path.read_bytes()
        self.assertNotIn(b"\r", first)
        m.save()
        self.assertEqual(self.path.read_bytes(), first)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["installed.json"], "no temp file is left")

    def test_load_of_a_missing_file_is_none_and_of_a_corrupt_one_is_an_error(self):
        self.assertIsNone(im.Manifest.load(self.path))
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(im.ManifestError):
            im.Manifest.load(self.path)
        self.path.write_text(json.dumps({"manifest_version": 99}), encoding="utf-8")
        with self.assertRaises(im.ManifestError):
            im.Manifest.load(self.path)

    def test_a_path_that_escapes_its_base_is_refused(self):
        m = im.Manifest(self.path, "project", {"project": str(self.root)})
        for bad in ("../x", "/abs", "a/../../x", "C:/x", ""):
            with self.assertRaises(im.ManifestError, msg=bad):
                m.record("project", bad, b"x")
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"manifest_version": 1, "kind": "project", "bases": {"project": str(self.root)},
                                         "variables": {}, "files": [{"base": "project", "path": "../evil",
                                                                      "sha256": "0" * 64, "backup": None}],
                                         "dirs": []}), encoding="utf-8")
        with self.assertRaises(im.ManifestError):
            im.Manifest.load(self.path)

    def test_state_is_same_different_or_missing(self):
        m = im.Manifest(self.path, "project", {"project": str(self.root)})
        target = self.root / "f.txt"
        target.write_bytes(b"one\n")
        m.record("project", "f.txt", b"one\n")
        self.assertEqual(m.state(self.root, "f.txt"), "SAME")
        target.write_bytes(b"one\r\n")
        self.assertEqual(m.state(self.root, "f.txt"), "SAME", "line endings are not an edit")
        target.write_bytes(b"two\n")
        self.assertEqual(m.state(self.root, "f.txt"), "DIFFERENT")
        target.unlink()
        self.assertEqual(m.state(self.root, "f.txt"), "MISSING")

    def test_record_replaces_an_entry_and_keeps_the_original_backup(self):
        m = im.Manifest(self.path, "project", {"project": str(self.root)})
        m.record("project", "f.txt", b"v1", backup="f.txt.bak-1")
        m.record("project", "f.txt", b"v2", backup="f.txt.bak-2")
        entry = m.entry("project", "f.txt")
        self.assertEqual(entry["sha256"], im.sha256_bytes(b"v2"))
        self.assertEqual(entry["backup"], "f.txt.bak-1", "the backup of what init first replaced is what uninstall restores")
        self.assertEqual(entry["previous"], ["f.txt.bak-2"])
        self.assertEqual(len(m.files), 1)

    def test_forget_removes_an_entry(self):
        m = im.Manifest(self.path, "project", {"project": str(self.root)})
        m.record("project", "f.txt", b"v1")
        m.forget("project", "f.txt")
        self.assertIsNone(m.entry("project", "f.txt"))


if __name__ == "__main__":
    unittest.main()
