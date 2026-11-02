"""Every relative link and image of README.md and docs/**/*.md resolves to an existing file."""
import re
import unittest
from pathlib import Path

from _support import ROOT

LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def markdown_files():
    return [ROOT / "README.md"] + sorted((ROOT / "docs").rglob("*.md"))


def headings(path):
    out = set()
    fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            slug = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-")
            out.add(slug)
    return out


class LinkTests(unittest.TestCase):
    def test_relative_links_resolve(self):
        bad = []
        for md in markdown_files():
            text = re.sub(r"```.*?```", "", md.read_text(encoding="utf-8"), flags=re.S)
            for target in LINK.findall(text):
                if re.match(r"^(https?:|mailto:)", target):
                    continue
                path, _, anchor = target.partition("#")
                dest = md if not path else (md.parent / path).resolve()
                if not dest.exists():
                    bad.append(f"{md.relative_to(ROOT)}: {target}")
                elif anchor and dest.suffix == ".md" and anchor not in headings(dest):
                    bad.append(f"{md.relative_to(ROOT)}: {target} (no such heading)")
        self.assertEqual(bad, [])

    def test_the_wiki_has_pages(self):
        self.assertGreaterEqual(len(markdown_files()), 25)


if __name__ == "__main__":
    unittest.main()
