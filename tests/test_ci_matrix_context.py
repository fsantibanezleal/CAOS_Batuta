"""A stub link built across drives: no relative path exists, so the link falls back to the absolute path of the unit file."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import SCRIPTS

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib.areas import context  # noqa: E402


class CrossDriveLinks(unittest.TestCase):
    def test_the_fallback_is_the_absolute_posix_path_of_the_unit_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, folder = Path(tmp) / "rules-src", Path(tmp) / "build"
            (base / "units").mkdir(parents=True)
            folder.mkdir()
            (base / "units" / "a.md").write_text("x", encoding="utf-8")
            link = context._linker(base, folder)
            with mock.patch.object(os.path, "relpath", side_effect=ValueError("path is on mount 'C:', start on mount 'D:'")):
                got = link({"file": "units/a.md"})
            self.assertEqual(got, (base.resolve() / "units" / "a.md").as_posix())
            self.assertTrue(os.path.isabs(got))
            self.assertTrue(Path(got).is_file())

    def test_the_same_drive_link_stays_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, folder = Path(tmp) / "src", Path(tmp) / "build" / "rules"
            (base / "units").mkdir(parents=True)
            folder.mkdir(parents=True)
            self.assertEqual(context._linker(base, folder)({"file": "units/a.md"}), "../../src/units/a.md")
