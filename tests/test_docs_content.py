"""The wiki's content rules: commands it shows exist, diagrams are accessible and theme-aware, no private terms, the
index lists every page and ADR, the skills page matches the skills, the known limits are all there."""
import os
import re
import shlex
import unittest
from pathlib import Path

from _support import ROOT, load_module, load_batuta

DOCS = ROOT / "docs"
PAGES = sorted(p for p in DOCS.rglob("*.md"))
# Generic machine-path patterns only; the names to keep out come from a local file named by BATUTA_PRIVATE_TERMS
# (one per line), which never lives in the repository, as in test_context_render.py.
PATH_TERMS = ("d:" + chr(92) + "_", "e:" + chr(92) + "_", "/users/")


def private_terms():
    listed = os.environ.get("BATUTA_PRIVATE_TERMS")
    if listed and Path(listed).is_file():
        return tuple(t.strip().lower() for t in Path(listed).read_text(encoding="utf-8").splitlines() if t.strip())
    return ()


def text_of(path):
    return path.read_text(encoding="utf-8")


def parser_tree():
    batuta = load_batuta()
    areas, warnings = batuta.load_areas()
    assert not warnings, warnings
    return batuta.build_parser(areas, "0")


def sub_action(parser):
    import argparse
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a
    return None


def options_of(parser):
    return {s for a in parser._actions for s in a.option_strings}


def command_lines(md):
    """Command lines of fenced blocks: `batuta ...`, `python .../batuta.py ...` or `$ batuta ...`."""
    out = []
    for block in re.findall(r"```[a-z]*\n(.*?)```", text_of(md), flags=re.S):
        for line in block.splitlines():
            line = line.strip()
            m = re.match(r"^(?:\$ )?(?:BATUTA_\w+=\S+ )*(?:batuta|python\S* \S*batuta\.py) (.*)$", line)
            if m:
                out.append(m.group(1))
    return out


class CommandsExistTests(unittest.TestCase):
    def test_every_command_a_page_shows_exists(self):
        root = parser_tree()
        bad, seen = [], 0
        for md in PAGES + [ROOT / "README.md"]:
            for rest in command_lines(md):
                rest = rest.split(" < ")[0].split(" | ")[0]
                try:
                    tokens = shlex.split(rest, posix=True)
                except ValueError:
                    continue
                parser = root
                for tok in tokens:
                    if tok.startswith("-") or tok.startswith("<") or tok in ("...",):
                        break
                    sub = sub_action(parser)
                    if sub is None:
                        break
                    if tok not in sub.choices:
                        bad.append(f"{md.relative_to(ROOT)}: unknown word {tok!r} in `{rest}`")
                        break
                    parser = sub.choices[tok]
                seen += 1
                known = options_of(parser) | {"--config", "--json", "--version", "-h", "--help"}
                for tok in tokens:
                    if tok.startswith("--") and tok.split("=")[0] not in known:
                        bad.append(f"{md.relative_to(ROOT)}: unknown option {tok!r} in `{rest}`")
        self.assertGreater(seen, 40)
        self.assertEqual(bad, [])


class HygieneTests(unittest.TestCase):
    def test_no_private_terms_in_pages(self):
        bad = []
        for md in PAGES + [ROOT / "README.md"]:
            low = text_of(md).lower()
            for term in PATH_TERMS + private_terms():
                if term in low:
                    bad.append(f"{md.relative_to(ROOT)}: {term}")
        self.assertEqual(bad, [])

    def test_no_arrow_characters_or_em_dashes_in_pages(self):
        for md in PAGES + [ROOT / "README.md"]:
            for ch in "\u2014\u2192\u2190\u21d2":
                self.assertNotIn(ch, text_of(md), md.name)


class DiagramTests(unittest.TestCase):
    SVGS = sorted((DOCS / "assets").glob("*.svg"))

    def test_five_diagrams_exist(self):
        self.assertEqual({p.stem for p in self.SVGS}, {"architecture", "lifecycle", "context-tiers", "delegation-loop", "contract-first-waves"})

    def test_each_is_accessible_theme_aware_and_self_contained(self):
        for svg in self.SVGS:
            t = text_of(svg)
            self.assertLess(len(t.encode("utf-8")), 60000, svg.name)
            self.assertIn("<title", t)
            self.assertIn("<desc", t)
            self.assertIn("prefers-color-scheme: dark", t)
            self.assertIn("<text", t)
            self.assertNotRegex(t, r"<image|@import|url\(http|href=\"http")
            self.assertNotIn("font-family:url", t)

    def test_each_is_referenced_with_alt_text(self):
        pages = "\n".join(text_of(p) for p in PAGES)
        for svg in self.SVGS:
            self.assertRegex(pages, r"!\[[^\]]{20,}\]\([./]*assets/" + re.escape(svg.name) + r"\)", svg.name)


class IndexTests(unittest.TestCase):
    def test_docs_index_lists_every_page_and_adr(self):
        index = text_of(DOCS / "README.md")
        for md in PAGES:
            rel = md.relative_to(DOCS).as_posix()
            if rel == "README.md":
                continue
            self.assertIn(f"({rel})", index, f"docs/README.md does not link {rel}")
        for adr in sorted((DOCS / "decisions").glob("ADR-*.md")):
            self.assertIn(adr.stem.split("-")[0] + "-" + adr.stem.split("-")[1], index)

    def test_readme_carries_the_one_step_install_line_and_no_planned_channels(self):
        readme = text_of(ROOT / "README.md")
        self.assertIn("/plugin install batuta --marketplace fsantibanezleal/CAOS_Batuta", readme)
        self.assertIn("2.1.275", readme)
        self.assertNotRegex(readme, r"(?i)not yet available|is planned and is not")


class SkillsPageTests(unittest.TestCase):
    def test_skills_page_lists_every_skill_with_its_description(self):
        page = text_of(DOCS / "reference" / "skills.md")
        names = sorted(p.parent.name for p in (ROOT / "plugins" / "batuta" / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(names), 13)
        for name in names:
            body = text_of(ROOT / "plugins" / "batuta" / "skills" / name / "SKILL.md")
            desc = re.search(r'^description: "(.*)"$', body, flags=re.M).group(1)
            self.assertIn(f"`/batuta:{name}`", page)
            self.assertIn(desc, page, name)


class KnownLimitsTests(unittest.TestCase):
    def test_every_accepted_residual_is_listed_with_its_decision(self):
        page = text_of(DOCS / "reference" / "known-limits.md")
        low = page.lower()
        for number in ("30", "32", "33", "34", "35", "36", "37"):
            self.assertRegex(page, r"decisions?[^|]*" + number)
        for needle in ("inline interpreter", "keystrokes", "concatenation", "tdd.test_command", "unverified"):
            self.assertIn(needle, low)


if __name__ == "__main__":
    unittest.main()
