"""`fragments changelog`: merge `changes/*.md` bullet fragments under `## [Unreleased]` of CHANGELOG.md (port of the
parallel-unit fragment merge, generic). Dry run by default; a refusal changes nothing."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_device_support import run  # noqa: E402

CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n- existing entry\n\n## [1.0.0] - 2026-01-01\n\n- first release\n"


class ChangelogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.cl = self.root / "CHANGELOG.md"
        self.cl.write_bytes(CHANGELOG.encode())
        self.changes = self.root / "changes"
        self.changes.mkdir()
        (self.changes / "b-unit.md").write_text("- beta change\n", encoding="utf-8")
        (self.changes / "a-unit.md").write_text("- alpha change\n- alpha two\n", encoding="utf-8")

    def test_dry_run_lists_the_lines_and_writes_nothing(self):
        code, out, _ = run("fragments", "changelog", str(self.root))
        self.assertEqual(code, 0, out)
        self.assertIn("MERGED a-unit.md: - alpha change", out)
        self.assertIn("dry run", out)
        self.assertEqual(self.cl.read_bytes(), CHANGELOG.encode())
        self.assertEqual(len(list(self.changes.glob("*.md"))), 2)

    def test_apply_merges_in_file_name_order_under_unreleased_and_deletes_the_fragments(self):
        code, out, _ = run("fragments", "changelog", str(self.root), "--apply")
        self.assertEqual(code, 0, out)
        text = self.cl.read_text(encoding="utf-8")
        order = [text.index(s) for s in ("existing entry", "alpha change", "alpha two", "beta change", "[1.0.0]")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(list(self.changes.glob("*.md")), [])
        self.assertIn("REMOVED changes/a-unit.md", out)

    def test_apply_twice_does_not_duplicate(self):
        run("fragments", "changelog", str(self.root), "--apply")
        (self.changes / "a-unit.md").write_text("- alpha change\n", encoding="utf-8")
        run("fragments", "changelog", str(self.root), "--apply")
        self.assertEqual(self.cl.read_text(encoding="utf-8").count("alpha change"), 1)

    def test_continuation_lines_stay_with_their_bullet(self):
        (self.changes / "a-unit.md").write_text("- alpha change\n  continued here\n", encoding="utf-8")
        run("fragments", "changelog", str(self.root), "--apply")
        self.assertIn("- alpha change\n  continued here\n", self.cl.read_text(encoding="utf-8"))

    def test_crlf_is_preserved(self):
        self.cl.write_bytes(CHANGELOG.replace("\n", "\r\n").encode())
        run("fragments", "changelog", str(self.root), "--apply")
        raw = self.cl.read_bytes()
        self.assertNotIn(b"\r\r", raw)
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertIn(b"alpha change", raw)

    def test_missing_unreleased_heading_is_refused_and_keeps_fragments(self):
        self.cl.write_text("# Changelog\n\n## [1.0.0]\n", encoding="utf-8")
        code, out, _ = run("fragments", "changelog", str(self.root), "--apply")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED .*\[Unreleased\]")
        self.assertEqual(len(list(self.changes.glob("*.md"))), 2)

    def test_unreleased_as_last_section(self):
        self.cl.write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")
        run("fragments", "changelog", str(self.root), "--apply")
        self.assertIn("- alpha change", self.cl.read_text(encoding="utf-8"))

    def test_a_fragment_with_a_heading_or_prose_is_refused_and_nothing_changes(self):
        for bad in ("prose line\n", "## A heading\n- x\n"):
            (self.changes / "c-unit.md").write_text(bad, encoding="utf-8")
            code, out, _ = run("fragments", "changelog", str(self.root), "--apply")
            self.assertEqual(code, 1)
            self.assertIn("c-unit.md", out)
            self.assertEqual(self.cl.read_bytes(), CHANGELOG.encode())
            self.assertEqual(len(list(self.changes.glob("*.md"))), 3)

    def test_a_missing_changelog_is_refused(self):
        self.cl.unlink()
        code, out, _ = run("fragments", "changelog", str(self.root), "--apply")
        self.assertEqual(code, 1)
        self.assertIn("CHANGELOG.md", out)

    def test_no_fragments_is_ok(self):
        for f in self.changes.glob("*.md"):
            f.unlink()
        code, out, _ = run("fragments", "changelog", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("no fragments", out)

    def test_json_output_is_the_c20_object(self):
        code, out, _ = run("fragments", "changelog", str(self.root), "--json")
        doc = json.loads(out)
        self.assertEqual((doc["area"], doc["verb"], doc["exit_code"]), ("fragments", "changelog", 0))


if __name__ == "__main__":
    unittest.main()
