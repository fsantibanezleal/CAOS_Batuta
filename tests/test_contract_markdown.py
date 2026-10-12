"""validate_markdown: front matter, section order, tables, rules, and C19 line mode."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib import contract  # noqa: E402

SCHEMA = {"type": "object", "required": ["kind"],
          "properties": {"kind": {"type": "string", "enum": ["a", "b"]}, "status": {"type": "string"}},
          "$defs": {"row": {"type": "object", "required": ["Id", "N"],
                            "properties": {"Id": {"type": "string", "pattern": "^R-\\d$"}, "N": {"type": ["integer", "null"]},
                                           "Tags": {"type": "array", "items": {"type": "string"}},
                                           "Sev": {"type": "string"}, "St": {"type": "string"}}}}}
SPEC = {"front_matter": "required", "sections": ["One", "Two", "Three"]}


def md(front="kind: a", sections=("One", "Two", "Three"), extra=""):
    parts = ["---", front, "---", ""]
    for s in sections:
        parts += [f"## {s}", "", "text", ""]
    return "\n".join(parts) + extra


class FrontMatterAndSections(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(contract.validate_markdown(md(), SCHEMA, SPEC), [])

    def test_extra_sections_are_allowed_between_required_ones(self):
        self.assertEqual(contract.validate_markdown(md(sections=("One", "Extra", "Two", "Three")), SCHEMA, SPEC), [])

    def test_front_matter_errors_are_prefixed(self):
        out = contract.validate_markdown(md(front="kind: z"), SCHEMA, SPEC)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("front matter /kind:"), out)

    def test_missing_front_matter_is_reported(self):
        out = contract.validate_markdown("## One\n", SCHEMA, SPEC)
        self.assertTrue(any(e.startswith("front matter:") for e in out), out)

    def test_malformed_front_matter_is_reported_with_line(self):
        out = contract.validate_markdown("---\nkind a\n---\n", SCHEMA, SPEC)
        self.assertTrue(any("line 2" in e for e in out), out)

    def test_missing_section(self):
        out = contract.validate_markdown(md(sections=("One", "Three")), SCHEMA, SPEC)
        self.assertEqual(out, ["sections: missing required section 'Two'"])

    def test_section_order(self):
        out = contract.validate_markdown(md(sections=("Two", "One", "Three")), SCHEMA, SPEC)
        self.assertEqual(len(out), 1)
        self.assertIn("out of order", out[0])

    def test_titles_are_case_sensitive_and_exact(self):
        out = contract.validate_markdown(md(sections=("one", "Two", "Three")), SCHEMA, SPEC)
        self.assertEqual(out, ["sections: missing required section 'One'"])

    def test_front_matter_none_ignores_it(self):
        spec = {"front_matter": "none", "sections": ["One"]}
        self.assertEqual(contract.validate_markdown("## One\n\nx\n", {"type": "object"}, spec), [])
        self.assertEqual(contract.validate_markdown(md(front="kind: zzz", sections=("One",)), {"type": "object"}, spec), [])

    def test_section_patterns(self):
        spec = {"front_matter": "none", "sections": [], "section_patterns": [{"pattern": "^D\\d+( |$)", "min": 1}]}
        self.assertTrue(contract.validate_markdown("## Summary\n", {}, spec))
        self.assertEqual(contract.validate_markdown("## Summary\n## D1 thing\n", {}, spec), [])

    def test_line_rules(self):
        spec = {"front_matter": "none", "sections": ["Del"], "line_rules": {"Del": {"pattern": "^- D\\d+: .+", "min": 1}}}
        self.assertEqual(contract.validate_markdown("## Del\n\n- D1: x\n", {}, spec), [])
        out = contract.validate_markdown("## Del\n\nprose only\n", {}, spec)
        self.assertEqual(len(out), 1)
        self.assertIn("Del", out[0])

    def test_forbidden_and_final_lines(self):
        spec = {"front_matter": "none", "sections": [], "forbidden": ["\\bTODO\\b"], "final_lines": ["^A: \\S+", "^B: \\S+"]}
        self.assertEqual(contract.validate_markdown("x\nA: 1\nB: 2\n\n", {}, spec), [])
        self.assertIn("placeholder", " ".join(contract.validate_markdown("TODO\nA: 1\nB: 2\n", {}, spec)))
        self.assertIn("final lines", " ".join(contract.validate_markdown("A: 1\nB: 2\nx\n", {}, spec)))

    def test_forbidden_text_inside_code_fence_still_counts(self):
        spec = {"front_matter": "none", "sections": [], "forbidden": ["TBD"]}
        self.assertTrue(contract.validate_markdown("```\nTBD\n```\n", {}, spec))


TBL = {"front_matter": "required", "sections": [],
       "tables": [{"name": "T", "headers": ["Id", "N", "Tags"], "row_def": "row", "min_rows": 1,
                   "coerce": {"N": "int", "Tags": "list"}}]}


def with_table(rows, headers="| Id | N | Tags |"):
    sep = "|" + "|".join("---" for _ in headers.strip("|").split("|")) + "|"
    return md() + "\n" + headers + "\n" + sep + "\n" + "\n".join(rows) + "\n"


class Tables(unittest.TestCase):
    def test_rows_are_coerced_and_validated(self):
        self.assertEqual(contract.validate_markdown(with_table(["| R-1 | 3 | a, b |", "| R-2 |  | - |"]), SCHEMA, TBL), [])

    def test_row_error_names_table_row_and_column(self):
        out = contract.validate_markdown(with_table(["| R-1 | 3 | a |", "| bad | 3 | a |"]), SCHEMA, TBL)
        self.assertEqual(len(out), 1)
        self.assertIn("table 'T' row 2 /Id", out[0])

    def test_int_coercion_failure_becomes_type_error(self):
        out = contract.validate_markdown(with_table(["| R-1 | soon | a |"]), SCHEMA, TBL)
        self.assertIn("/N", out[0])
        self.assertIn("expected integer|null", out[0])

    def test_missing_table(self):
        out = contract.validate_markdown(md(), SCHEMA, TBL)
        self.assertEqual(len(out), 1)
        self.assertIn("table 'T' not found", out[0])

    def test_wrong_headers_means_not_found(self):
        out = contract.validate_markdown(with_table(["| R-1 | 3 |"], headers="| Id | N |"), SCHEMA, TBL)
        self.assertIn("table 'T' not found", out[0])

    def test_optional_table_may_be_absent(self):
        spec = {**TBL, "tables": [{**TBL["tables"][0], "optional": True}]}
        self.assertEqual(contract.validate_markdown(md(), SCHEMA, spec), [])

    def test_min_rows(self):
        out = contract.validate_markdown(with_table([]), SCHEMA, TBL)
        self.assertIn("at least 1 row", out[0])

    def test_backticks_around_a_cell_are_stripped(self):
        self.assertEqual(contract.validate_markdown(with_table(["| `R-1` | 1 | `a`, `b` |"]), SCHEMA, TBL), [])

    def test_root_schema_as_row_schema(self):
        schema = {"type": "object", "required": ["A"], "properties": {"A": {"type": "string", "minLength": 1}}}
        spec = {"front_matter": "none", "sections": [], "tables": [{"name": "T", "headers": ["A"], "row_def": None}]}
        self.assertEqual(contract.validate_markdown("| A |\n|---|\n| x |\n", schema, spec), [])
        out = contract.validate_markdown("| A |\n|---|\n|  |\n", schema, spec)
        self.assertIn("/A", out[0])


RULE_SCHEMA = {"type": "object"}


class Rules(unittest.TestCase):
    def run_rules(self, rules, text, spec_extra=None):
        spec = {"front_matter": "required", "sections": [], "rules": rules,
                "tables": [{"name": "T", "headers": ["Id", "Sev", "St"], "row_def": None}]}
        spec.update(spec_extra or {})
        return contract.validate_markdown(text, RULE_SCHEMA, spec)

    def doc(self, status, rows, sections="## S\n\nbody\n"):
        t = "| Id | Sev | St |\n|---|---|---|\n" + "\n".join(rows) + "\n"
        return f"---\nstatus: {status}\n---\n\n{t}\n{sections}"

    def test_nonempty_sections_when(self):
        rule = {"type": "nonempty_sections", "when": {"status": ["x"]}, "sections": ["S"]}
        self.assertTrue(self.run_rules([rule], self.doc("x", [], sections="## S\n\n\n")))
        self.assertEqual(self.run_rules([rule], self.doc("y", [], sections="## S\n\n\n")), [])
        self.assertEqual(self.run_rules([rule], self.doc("x", [])), [])

    def test_forbid_text_when(self):
        rule = {"type": "forbid_text", "when": {"status": ["Review", "Frozen"]}, "pattern": "\\[NEEDS CLARIFICATION\\]"}
        self.assertTrue(self.run_rules([rule], self.doc("Frozen", [], sections="## S\n\n[NEEDS CLARIFICATION] x\n")))
        self.assertEqual(self.run_rules([rule], self.doc("Draft", [], sections="## S\n\n[NEEDS CLARIFICATION] x\n")), [])

    def test_forbid_rows(self):
        rule = {"type": "forbid_rows", "when": {"status": ["PASS"]}, "table": "T",
                "match": {"Sev": ["major"], "St": ["open"]}, "message": "no open major"}
        out = self.run_rules([rule], self.doc("PASS", ["| F1 | major | open |"]))
        self.assertIn("no open major", out[0])
        self.assertEqual(self.run_rules([rule], self.doc("PASS", ["| F1 | major | fixed |", "| F2 | minor | open |"])), [])
        self.assertEqual(self.run_rules([rule], self.doc("FAIL", ["| F1 | major | open |"])), [])

    def test_require_text_if_rows(self):
        rule = {"type": "require_text_if_rows", "when": {"status": ["PF"]}, "table": "T", "match": {"St": ["fixed"]},
                "pattern": "Re-check", "message": "needs a Re-check line"}
        self.assertTrue(self.run_rules([rule], self.doc("PF", ["| F1 | major | fixed |"])))
        self.assertEqual(self.run_rules([rule], self.doc("PF", ["| F1 | major | fixed |"], sections="## S\n\nRe-check: ok\n")), [])
        self.assertEqual(self.run_rules([rule], self.doc("PF", ["| F1 | major | open |"])), [])

    def test_unique_column(self):
        rule = {"type": "unique_column", "table": "T", "column": "Id"}
        self.assertEqual(self.run_rules([rule], self.doc("x", ["| a | m | o |", "| b | m | o |"])), [])
        out = self.run_rules([rule], self.doc("x", ["| a | m | o |", "| a | m | o |"]))
        self.assertIn("duplicate", out[0])

    def test_require_keys_when_and_forbid_keys(self):
        r1 = {"type": "require_keys", "when": {"status": ["x"]}, "keys": ["owner"]}
        r2 = {"type": "forbid_keys", "keys": ["hooks"]}
        self.assertIn("owner", self.run_rules([r1], self.doc("x", []))[0])
        self.assertEqual(self.run_rules([r1], self.doc("y", [])), [])
        doc = "---\nstatus: x\nhooks: 1\n---\n\n| Id | Sev | St |\n|---|---|---|\n"
        self.assertIn("hooks", self.run_rules([r2], doc)[0])

    def test_ids_match(self):
        rule = {"type": "ids_match", "sections_pattern": "^(D\\d+)( |$)", "table": "T", "column": "Id"}
        ok = self.doc("x", ["| D1 | a | b |", "| D2 | a | b |"], sections="## D1 one\n\n## D2 two\n")
        self.assertEqual(self.run_rules([rule], ok), [])
        bad = self.doc("x", ["| D1 | a | b |"], sections="## D1 one\n\n## D2 two\n")
        self.assertIn("D2", self.run_rules([rule], bad)[0])

    def test_unknown_rule_type_is_reported(self):
        out = self.run_rules([{"type": "nope"}], self.doc("x", []))
        self.assertIn("unknown rule type", out[0])


class LineMode(unittest.TestCase):
    SCHEMA = {"type": "string", "pattern": "^- \\d{4} \\| a$"}
    SPEC = {"mode": "lines", "line_prefix": "- ", "min_lines": 1}

    def test_valid_lines_and_ignored_text(self):
        self.assertEqual(contract.validate_markdown("# H\n\n- 2026 | a\n- 2027 | a\n", self.SCHEMA, self.SPEC), [])

    def test_bad_line_names_line_number(self):
        out = contract.validate_markdown("# H\n- 2026 | a\n- bad\n", self.SCHEMA, self.SPEC)
        self.assertEqual(len(out), 1)
        self.assertIn("line 3", out[0])

    def test_min_lines(self):
        out = contract.validate_markdown("# H\n", self.SCHEMA, self.SPEC)
        self.assertIn("no lesson lines", out[0])


if __name__ == "__main__":
    unittest.main()
