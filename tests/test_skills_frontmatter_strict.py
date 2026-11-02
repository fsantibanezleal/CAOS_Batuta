"""Skill front matter is valid YAML: the strict reader refuses a plain scalar that YAML cannot read, and every SKILL.md passes."""
import unittest

from _support import ROOT, load_batuta

SKILLS = ROOT / "plugins" / "batuta" / "skills"


def doc(*lines):
    return "\n".join(lines) + "\n"


class StrictReader(unittest.TestCase):
    def setUp(self):
        load_batuta()
        from batuta_lib import frontmatter
        self.fm = frontmatter

    def refused(self, line):
        with self.assertRaises(ValueError, msg=line):
            self.fm.parse(doc("---", line, "---"), strict=True)

    def test_a_plain_scalar_with_colon_space_is_refused_in_strict_mode_only(self):
        text = doc("---", "description: Use when about to hand work to an agent: write the brief first.", "---")
        meta, _ = self.fm.parse(text)
        self.assertIn("agent: write", meta["description"])
        self.refused("description: Use when about to hand work to an agent: write the brief first.")

    def test_other_plain_scalar_problems_are_refused(self):
        self.refused("description: text # a comment marker")
        self.refused("description: ends with a colon:")
        for first in "&*!|>%@`,]}#":
            self.refused(f"description: {first}starts with an indicator")
        self.refused("description: - a dash and a space")
        self.refused("description: ? a question mark and a space")

    def test_quoted_and_ordinary_scalars_pass(self):
        meta, _ = self.fm.parse(doc("---", 'description: "Use when: a thing # happens, then do it"', "name: a-b",
                                     "allowed-tools: Bash(python *) Read", "argument-hint: <topic> <agent>",
                                     "disable-model-invocation: true", "note: -dash-start is fine", "---"), strict=True)
        self.assertEqual(meta["description"], "Use when: a thing # happens, then do it")
        self.assertEqual(meta["note"], "-dash-start is fine")

    def test_strict_applies_to_block_list_items_too(self):
        with self.assertRaises(ValueError):
            self.fm.parse(doc("---", "items:", "  - a: b", "---"), strict=True)


class ShippedSkills(unittest.TestCase):
    def test_every_skill_passes_the_strict_reader(self):
        load_batuta()
        from batuta_lib import frontmatter
        files = sorted(SKILLS.glob("*/SKILL.md"))
        self.assertEqual(len(files), 13)
        for path in files:
            try:
                meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"), strict=True)
            except ValueError as exc:
                self.fail(f"{path.parent.name}: {exc}")
            self.assertEqual(meta["name"], path.parent.name)

    def test_every_skill_parses_with_pyyaml_when_it_is_importable(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not importable here; the strict reader test above covers the same defect")
        load_batuta()
        from batuta_lib import frontmatter
        for path in sorted(SKILLS.glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            head = text.split("\n---", 1)[0].split("---\n", 1)[1]
            data = yaml.safe_load(head)
            self.assertIsInstance(data, dict, path.parent.name)
            self.assertEqual(data["name"], path.parent.name)
            meta, _ = frontmatter.parse(text)
            self.assertEqual(data["description"], meta["description"], path.parent.name)
            if path.parent.name in ("freeze", "promote"):
                self.assertIs(data["disable-model-invocation"], True)


if __name__ == "__main__":
    unittest.main()
