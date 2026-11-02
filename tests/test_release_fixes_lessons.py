"""Release review fix F-09 (LESSON-1): Batuta's own LESSONS.md follows its own C19 lesson line format."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import CONTRACTS, ROOT, run  # noqa: E402

LESSONS = ROOT / "LESSONS.md"


def problems(text, today="2099-01-01"):
    """What is wrong with the lesson lines of `text`: a bullet that is not a C19 line, a bullet outside it, a heading mismatch."""
    from batuta_lib import contract
    schema = contract.load_schema(contract.find_schema(CONTRACTS, "C19"))
    found, heading_date = [], None
    for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        head = re.match(r"^## (\d{4}-\d{2}-\d{2}),", line)
        if head:
            heading_date = head.group(1)
        elif line.startswith("- "):
            errors = contract.validate(line, schema)
            if errors:
                found.append(f"line {n}: {errors[0]}")
            elif line[2:12] != heading_date:
                found.append(f"line {n}: dated {line[2:12]} under the heading of {heading_date}")
        elif line.startswith(("  ", "\t")) and line.strip():
            found.append(f"line {n}: a wrapped continuation of a bullet")
    return found


class OwnLessons(unittest.TestCase):
    def test_every_bullet_is_a_c19_line_dated_as_its_heading(self):
        self.assertEqual(problems(LESSONS.read_text(encoding="utf-8")), [])

    def test_the_checker_finds_an_old_style_bullet(self):
        old = "## 2026-10-30, unit\n\n- A prose bullet that wraps\n  onto a second line.\n"
        self.assertEqual(len(problems(old)), 2)

    def test_the_entries_keep_their_heading_order_newest_first(self):
        dates = re.findall(r"^## (\d{4}-\d{2}-\d{2}),", LESSONS.read_text(encoding="utf-8"), re.M)
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(len(dates), 18)

    def test_lessons_check_prints_no_warning(self):
        code, out, err = run("lessons", "check", "--root", ROOT)
        self.assertNotIn("WARN", out + err)
        self.assertEqual(code, 0, out + err)

    def test_contract_validate_accepts_the_lines(self):
        from batuta_lib import contract
        schema = contract.load_schema(contract.find_schema(CONTRACTS, "C19"))
        lines = [ln for ln in LESSONS.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]
        self.assertGreater(len(lines), 50)
        self.assertEqual([ln for ln in lines if contract.validate(ln, schema)], [])


if __name__ == "__main__":
    unittest.main()
