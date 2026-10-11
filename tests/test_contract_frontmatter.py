"""Front matter parser, sections and tables (harness_lib.frontmatter)."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "harness" / "scripts"))

from harness_lib import frontmatter as fmx  # noqa: E402


def doc(*lines):
    return "\n".join(lines) + "\n"


class ParseScalars(unittest.TestCase):
    def test_scalars(self):
        meta, body = fmx.parse(doc("---", "a: hello world", "b: 42", "c: -7", "d: true", "e: false", "f: 2026-10-11",
                                   "g: 1.5", "---", "# Title"))
        self.assertEqual(meta, {"a": "hello world", "b": 42, "c": -7, "d": True, "e": False, "f": "2026-10-11", "g": "1.5"})
        self.assertEqual(body.strip(), "# Title")

    def test_quoted_strings_keep_special_characters(self):
        meta, _ = fmx.parse(doc("---", 'a: "x: y, z"', "b: 'it''s' ", 'c: "42"', 'd: "line\\nbreak \\"q\\""', "---"))
        self.assertEqual(meta["a"], "x: y, z")
        self.assertEqual(meta["c"], "42")
        self.assertEqual(meta["d"], 'line\nbreak "q"')

    def test_value_with_colon_is_a_plain_string(self):
        meta, _ = fmx.parse(doc("---", "review_trigger: review-by: 2027-04-11", "---"))
        self.assertEqual(meta["review_trigger"], "review-by: 2027-04-11")

    def test_empty_value_without_items_is_empty_string(self):
        meta, _ = fmx.parse(doc("---", "a:", "b: x", "---"))
        self.assertEqual(meta, {"a": "", "b": "x"})

    def test_null(self):
        meta, _ = fmx.parse(doc("---", "a: null", "---"))
        self.assertIsNone(meta["a"])


class ParseLists(unittest.TestCase):
    def test_inline_lists(self):
        meta, _ = fmx.parse(doc("---", "a: [x, y]", "b: []", "c: [1, true, 'q, r', \"s\"]", "---"))
        self.assertEqual(meta["a"], ["x", "y"])
        self.assertEqual(meta["b"], [])
        self.assertEqual(meta["c"], [1, True, "q, r", "s"])

    def test_block_list(self):
        meta, _ = fmx.parse(doc("---", "a:", "  - one", "  - 2", '  - "three: 3"', "b: x", "---"))
        self.assertEqual(meta, {"a": ["one", 2, "three: 3"], "b": "x"})

    def test_block_list_of_flow_maps(self):
        meta, _ = fmx.parse(doc("---", "w:", "  - {gate: P3-red, reason: \"a, b\", by: me, n: 2}", "---"))
        self.assertEqual(meta["w"], [{"gate": "P3-red", "reason": "a, b", "by": "me", "n": 2}])

    def test_nested_map(self):
        meta, _ = fmx.parse(doc("---", "gates:", "  P0-research: passed", "  P3-red: pending", "n: 1", "---"))
        self.assertEqual(meta, {"gates": {"P0-research": "passed", "P3-red": "pending"}, "n": 1})


class ParseStructure(unittest.TestCase):
    def test_leading_comment_lines_are_skipped(self):
        meta, body = fmx.parse(doc("<!-- why: x -->", "<!-- expect: y -->", "---", "a: 1", "---", "body"))
        self.assertEqual(meta, {"a": 1})
        self.assertEqual(body.strip(), "body")

    def test_body_keeps_dashes_lines_after_the_close(self):
        _, body = fmx.parse(doc("---", "a: 1", "---", "text", "---", "more"))
        self.assertIn("---", body)

    def test_crlf(self):
        meta, body = fmx.parse("---\r\na: 1\r\nb: [x, y]\r\n---\r\nbody\r\n")
        self.assertEqual(meta, {"a": 1, "b": ["x", "y"]})
        self.assertEqual(body.strip(), "body")

    def test_empty_front_matter(self):
        meta, body = fmx.parse(doc("---", "---", "body"))
        self.assertEqual(meta, {})

    def test_keys_with_dash_and_camel_case(self):
        meta, _ = fmx.parse(doc("---", "disallowedTools: WebFetch", "P1b-contracts: passed", "---"))
        self.assertEqual(meta, {"disallowedTools": "WebFetch", "P1b-contracts": "passed"})


class ParseErrors(unittest.TestCase):
    def assertErr(self, text, fragment, line):
        with self.assertRaises(ValueError) as cm:
            fmx.parse(text)
        msg = str(cm.exception)
        self.assertIn(fragment, msg)
        self.assertIn(f"line {line}", msg)

    def test_missing_front_matter(self):
        self.assertErr("# no front matter\n", "front matter", 1)

    def test_unclosed(self):
        self.assertErr(doc("---", "a: 1", "b: 2"), "not closed", 1)

    def test_duplicate_key(self):
        self.assertErr(doc("---", "a: 1", "b: 2", "a: 3", "---"), "duplicate key 'a'", 4)

    def test_line_without_key(self):
        self.assertErr(doc("---", "a: 1", "just text", "---"), "key: value", 3)

    def test_unterminated_quote(self):
        self.assertErr(doc("---", 'a: "open', "---"), "unterminated", 2)

    def test_unterminated_inline_list(self):
        self.assertErr(doc("---", "a: [x, y", "---"), "inline list", 2)

    def test_tab_indent(self):
        self.assertErr(doc("---", "a:", "\t- x", "---"), "tab", 3)

    def test_mixed_list_and_map(self):
        self.assertErr(doc("---", "a:", "  - x", "  k: v", "---"), "mix", 4)

    def test_indented_line_without_parent(self):
        self.assertErr(doc("---", "  - x", "---"), "indented", 2)

    def test_line_numbers_count_leading_comments(self):
        self.assertErr(doc("<!-- c -->", "---", "oops", "---"), "key: value", 3)


class Sections(unittest.TestCase):
    def test_level_two_titles_in_order(self):
        body = doc("# T", "## Goal", "text", "### Sub", "## Spec ", "more", "## Checks")
        self.assertEqual(fmx.sections(body), ["Goal", "Spec", "Checks"])

    def test_headings_inside_code_fences_are_ignored(self):
        body = doc("## Real", "```", "## Fake", "```", "~~~", "## Fake 2", "~~~", "## Also real")
        self.assertEqual(fmx.sections(body), ["Real", "Also real"])

    def test_no_sections(self):
        self.assertEqual(fmx.sections("just text\n"), [])

    def test_section_bodies(self):
        body = doc("## A", "a1", "a2", "## B", "", "b1")
        got = fmx.section_bodies(body)
        self.assertEqual(got["A"].strip(), "a1\na2")
        self.assertEqual(got["B"].strip(), "b1")


class Tables(unittest.TestCase):
    T = doc("| A | B |", "|---|:--:|", "| 1 | two words |", "| `x|y` is split | z |".replace("`x|y`", "x\\|y"))

    def test_basic_table(self):
        out = fmx.tables(doc("text", "| A | B |", "|---|---|", "| 1 | 2 |", "| 3 | 4 |", "", "after"))
        self.assertEqual(out, [(["A", "B"], [["1", "2"], ["3", "4"]])])

    def test_alignment_row_and_escaped_pipe(self):
        (headers, rows), = fmx.tables(self.T)
        self.assertEqual(headers, ["A", "B"])
        self.assertEqual(rows[1], ["x|y is split", "z"])

    def test_two_tables_and_empty_table(self):
        body = doc("| A |", "|---|", "| 1 |", "", "| B | C |", "|---|---|")
        out = fmx.tables(body)
        self.assertEqual(out, [(["A"], [["1"]]), (["B", "C"], [])])

    def test_tables_in_code_fences_are_ignored(self):
        self.assertEqual(fmx.tables(doc("```", "| A |", "|---|", "| 1 |", "```")), [])

    def test_ragged_row_raises_with_line(self):
        with self.assertRaises(ValueError) as cm:
            fmx.tables(doc("x", "| A | B |", "|---|---|", "| 1 |"))
        self.assertIn("line 4", str(cm.exception))

    def test_pipe_line_without_separator_is_not_a_table(self):
        self.assertEqual(fmx.tables(doc("| not a table |", "plain")), [])

    def test_section_tables_attach_the_section(self):
        body = doc("## Reqs", "| A |", "|---|", "| 1 |", "## Other", "| B |", "|---|", "| 2 |")
        got = fmx.section_tables(body)
        self.assertEqual([g[0] for g in got], ["Reqs", "Other"])


if __name__ == "__main__":
    unittest.main()
