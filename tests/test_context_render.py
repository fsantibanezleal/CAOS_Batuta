"""render.py: placeholder rendering, atomic writes, and the shipped user templates."""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib import render  # noqa: E402

TEMPLATES = ROOT / "plugins" / "batuta" / "templates"
USER_VALUES = {"language": "English", "tone": "Direct, no filler.", "user_name": "the user", "python": "python3",
               "deploy_root": "~/.batuta", "temp_root": "~/.batuta/temp", "data_root": "~/.batuta/data",
               "models_root": "~/.batuta/models", "worktrees_root": "~/.batuta/worktrees"}
REFERENCE = ("deep-work.md", "automation.md", "disks.md", "agentic-orchestration.md")


class Render(unittest.TestCase):
    def test_replaces_every_placeholder(self):
        self.assertEqual(render.render("a {{x}} b {{ y }} {{x}}", {"x": "1", "y": "2"}), "a 1 b 2 1")

    def test_missing_value_is_refused_naming_it(self):
        with self.assertRaises(render.RenderError) as cm:
            render.render("a {{x}} {{zeta}}", {"x": "1"})
        self.assertIn("zeta", str(cm.exception))

    def test_value_that_carries_a_placeholder_is_refused(self):
        with self.assertRaises(render.RenderError):
            render.render("a {{x}}", {"x": "{{y}}"})

    def test_unused_values_are_ignored(self):
        self.assertEqual(render.render("{{x}}", {"x": "1", "unused": "2"}), "1")

    def test_placeholders_listed_in_order_without_duplicates(self):
        self.assertEqual(render.placeholders("{{b}} {{a}} {{b}}"), ["b", "a"])

    def test_crlf_is_normalised_to_lf(self):
        self.assertEqual(render.render("a\r\n{{x}}\r\n", {"x": "1"}), "a\n1\n")

    def test_write_atomic_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "f.md"
            self.assertEqual(render.status(path, "x\n"), "NEW")
            render.write_atomic(path, "x\n")
            self.assertEqual(render.status(path, "x\n"), "SAME")
            self.assertEqual(render.status(path, "y\n"), "CHANGED")
            self.assertEqual(path.read_bytes(), b"x\n")
            self.assertEqual([p.name for p in path.parent.iterdir()], ["f.md"])


class Templates(unittest.TestCase):
    def files(self):
        return sorted((TEMPLATES / "user").rglob("*.md"))

    def test_templates_exist(self):
        names = {p.name for p in self.files()}
        self.assertIn("CLAUDE.template.md", names)
        self.assertTrue(set(REFERENCE) <= names)

    def test_every_template_renders_with_the_documented_values(self):
        for path in self.files():
            with self.subTest(path.name):
                text = render.render(path.read_text(encoding="utf-8"), USER_VALUES)
                self.assertNotIn("{{", text)

    def test_core_template_is_small_and_points_to_reference_files(self):
        text = render.render((TEMPLATES / "user" / "CLAUDE.template.md").read_text(encoding="utf-8"), USER_VALUES)
        self.assertLess(len(text.encode("utf-8")), 7000)
        for name in REFERENCE:
            self.assertIn(name, text)

    def test_reference_files_state_a_trigger(self):
        refs = [p for p in self.files() if p.parent.name == "reference"]
        self.assertEqual(len(refs), len(REFERENCE))
        for path in refs:
            with self.subTest(path.name):
                self.assertRegex(path.read_text(encoding="utf-8"), r"(?m)^Read when: ")

    def test_no_machine_paths_or_addresses_and_no_deny_listed_term(self):
        """Structural checks; names to keep out come from a local file named by BATUTA_PRIVATE_TERMS (one per line),
        which never lives in the repository."""
        structural = re.compile(r"[A-Za-z]:[\\/]|/home/[A-Za-z]|/Users/|\\Users\\|[\w.+-]+@[\w-]+\.[\w.]+")
        terms = []
        listed = os.environ.get("BATUTA_PRIVATE_TERMS")
        if listed and Path(listed).is_file():
            terms = [t.strip().lower() for t in Path(listed).read_text(encoding="utf-8").splitlines() if t.strip()]
        for path in self.files():
            text = path.read_text(encoding="utf-8")
            with self.subTest(path.name):
                self.assertIsNone(structural.search(text))
                for term in terms:
                    self.assertNotIn(term, text.lower())

    def test_knowledge_template_folder_has_a_sample_manifest(self):
        sample = TEMPLATES / "knowledge" / "manifest.json"
        self.assertTrue(sample.is_file())


if __name__ == "__main__":
    unittest.main()
