"""Validator hardening: the reproductions of review findings F20 to F25 and the Markdown mechanisms the sizing,
catalog, brief and report contracts need (bullet header, unordered sections, lenient table headers, new rules)."""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib import contract, frontmatter as fm  # noqa: E402

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"


def schema_path(cid):
    return sorted(CONTRACTS.glob(f"{cid}-*.schema.json"))[0]


def write(d, name, text, binary=False):
    p = pathlib.Path(d) / name
    if binary:
        p.write_bytes(text)
    else:
        p.write_text(text, encoding="utf-8", newline="")
    return p


class F20PatternAnchoring(unittest.TestCase):
    """F20: `$` accepted a trailing newline and `\\d` accepted any Unicode digit."""

    SCHEMA = {"type": "string", "pattern": "^T-\\d{3}$"}

    def test_a_trailing_newline_is_refused(self):
        self.assertTrue(contract.validate("T-001\n", self.SCHEMA))

    def test_arabic_indic_digits_are_refused(self):
        self.assertTrue(contract.validate("T-١٢٣", self.SCHEMA))

    def test_the_plain_value_is_accepted(self):
        self.assertEqual(contract.validate("T-001", self.SCHEMA), [])

    def test_a_dollar_inside_a_class_or_escaped_is_kept_literal(self):
        self.assertEqual(contract.validate("a$", {"type": "string", "pattern": "^a[$]\\Z"}), [])
        self.assertEqual(contract.validate("a$", {"type": "string", "pattern": "^a\\$$"}), [])

    def test_c07_task_id_with_a_trailing_newline_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            doc = {"contract_version": "1.0", "entries": [{
                "path": "tests/test_x.py", "sha256": "a" * 64, "task_id": "T-001\n", "req_ids": [], "locked_commit": "abc1234"}]}
            p = write(d, "lock.json", json.dumps(doc))
            self.assertTrue(contract.validate_file(p, schema_path("C07")))

    def test_a_quoted_newline_escape_in_front_matter_is_refused(self):
        text = "---\nid: \"001-x\\n\"\ntitle: T\nstatus: Draft\ntier: S\nowner: me\ncreated: 2026-10-12\n---\n\n## Problem\nx\n"
        with tempfile.TemporaryDirectory() as d:
            p = write(d, "spec.md", text)
            errs = contract.validate_file(p, schema_path("C05"))
            self.assertTrue(any("/id" in e and "pattern" in e for e in errs), errs)


class F21NonJsonNumbersAndDuplicateKeys(unittest.TestCase):
    """F21: NaN and duplicate JSON keys were accepted."""

    def check(self, text, cid="C11", name="t.json"):
        with tempfile.TemporaryDirectory() as d:
            return contract.validate_file(write(d, name, text), schema_path(cid))

    def test_nan_is_refused(self):
        errs = self.check('{"contract_version": "1.0", "values": {"cov": NaN}}')
        self.assertTrue(any("NaN" in e for e in errs), errs)

    def test_infinity_is_refused(self):
        self.assertTrue(any("Infinity" in e for e in self.check('{"contract_version": "1.0", "values": {"cov": Infinity}}')))

    def test_a_duplicate_key_is_refused(self):
        text = ('{"contract_version": "1.0", "spec_id": "001-x", "spec_sha256": "%s", "spec_sha256": "%s", '
                '"contracts_sha256": {}, "named_tests_sha256": {}, "adrs_sha256": {}, "approved_by": "me", "prompt_excerpt": "ok", '
                '"approved_at": "2026-10-12T10:00:00Z", "tool_version": "0.1.0"}') % ("a" * 64, "b" * 64)
        errs = self.check(text, "C06")
        self.assertTrue(any("duplicate key" in e for e in errs), errs)

    def test_nan_in_a_jsonl_line_is_refused(self):
        errs = contract.validate_jsonl('{"contract_version": "1.0", "x": NaN}', contract.load_schema(schema_path("C04")))
        self.assertTrue(any("NaN" in e for e in errs), errs)

    def test_strict_loader_is_reusable(self):
        self.assertEqual(contract.loads_strict('{"a": 1}'), {"a": 1})
        with self.assertRaises(ValueError):
            contract.loads_strict('{"a": 1, "a": 2}')


class F22Bom(unittest.TestCase):
    """F22: a UTF-8 BOM made a Markdown artifact unreadable."""

    SPEC = "---\nid: 001-x\ntitle: T\nstatus: Draft\ntier: S\nowner: me\ncreated: 2026-10-12\n---\n"

    def test_front_matter_parse_skips_a_bom(self):
        meta, _ = fm.parse("﻿" + self.SPEC)
        self.assertEqual(meta["id"], "001-x")

    def test_validate_file_reads_a_bom_json_file(self):
        with tempfile.TemporaryDirectory() as d:
            doc = (CONTRACTS / "fixtures" / "C01" / "valid-minimal.json").read_bytes()
            p = write(d, "c.json", b"\xef\xbb\xbf" + doc, binary=True)
            self.assertEqual(contract.validate_file(p, schema_path("C01")), [])

    def test_validate_file_reads_a_bom_markdown_file(self):
        src = (CONTRACTS / "fixtures" / "C05" / "valid-frozen.md").read_bytes()
        with tempfile.TemporaryDirectory() as d:
            p = write(d, "s.md", b"\xef\xbb\xbf" + src, binary=True)
            self.assertEqual(contract.validate_file(p, schema_path("C05")), [])


class F23SectionsFileKeys(unittest.TestCase):
    """F23: a misspelled key in a sections file was silently ignored."""

    def load(self, spec):
        with tempfile.TemporaryDirectory() as d:
            sp = write(d, "CX-t.schema.json", "{}")
            write(d, "CX-t.sections.json", json.dumps(spec))
            return contract.load_sections_spec(sp)

    def test_unknown_top_level_key_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.load({"contract_id": "CX", "contract_version": "1.0", "sectionz": []})
        self.assertIn("sectionz", str(cm.exception))

    def test_a_misspelled_table_key_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.load({"tables": [{"name": "T", "headers": ["A"], "min_row": 99}]})
        self.assertIn("min_row", str(cm.exception))

    def test_a_misspelled_rule_key_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.load({"rules": [{"type": "unique_column", "table": "T", "colum": "A"}]})
        self.assertIn("colum", str(cm.exception))

    def test_an_unknown_rule_type_is_refused_at_load(self):
        with self.assertRaises(ValueError) as cm:
            self.load({"rules": [{"type": "no_such_rule"}]})
        self.assertIn("no_such_rule", str(cm.exception))

    def test_every_shipped_sections_file_loads(self):
        for sp in sorted(CONTRACTS.glob("*.sections.json")):
            with self.subTest(file=sp.name):
                contract.load_sections_spec(sp.with_name(sp.name.replace(".sections.json", ".schema.json")))


class F24RefCycle(unittest.TestCase):
    """F24: a pure $ref cycle passed check_schema and then rejected every instance."""

    def test_a_self_cycle_is_reported(self):
        schema = {"$ref": "#/$defs/a", "$defs": {"a": {"$ref": "#/$defs/a"}}}
        self.assertTrue(any("cycle" in p for p in contract.check_schema(schema)))

    def test_a_two_node_cycle_is_reported(self):
        schema = {"type": "object", "properties": {"x": {"$ref": "#/$defs/a"}},
                  "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}}
        self.assertTrue(any("cycle" in p for p in contract.check_schema(schema)))

    def test_recursion_through_properties_is_still_allowed(self):
        schema = {"type": "object", "properties": {"child": {"$ref": "#/$defs/node"}},
                  "$defs": {"node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/node"}}}}}
        self.assertEqual(contract.check_schema(schema), [])


class F25RelativePaths(unittest.TestCase):
    """F25: relative path patterns admitted `..` traversal."""

    def check_c01(self, **over):
        doc = json.loads((CONTRACTS / "fixtures" / "C01" / "valid-minimal.json").read_text(encoding="utf-8"))
        doc.update(over)
        return contract.validate(doc, contract.load_schema(schema_path("C01")))

    def test_parent_traversal_is_refused(self):
        for bad in ("../../elsewhere", "a/../b", "..", "a/.."):
            with self.subTest(value=bad):
                self.assertTrue(self.check_c01(coordination_root=bad), bad)

    def test_plain_relative_paths_are_accepted(self):
        for ok in (".batuta", "a/b/c", "dir.with.dots/x", "a..b/c"):
            with self.subTest(value=ok):
                self.assertEqual(self.check_c01(coordination_root=ok), [])

    def test_knowledge_manifest_is_checked_too(self):
        self.assertTrue(self.check_c01(knowledge_manifest="../x/manifest.json"))


class MarkdownMechanisms(unittest.TestCase):
    """New Markdown contract features: bullet header, unordered sections, lenient tables, new rules."""

    def md(self, spec, text, schema=None):
        return contract.validate_markdown(text, schema or {"type": "object"}, spec)

    def test_bullet_header_is_read_and_validated_before_the_first_section(self):
        spec = {"front_matter": "bullets", "sections": []}
        schema = {"type": "object", "properties": {"id": {"type": "string", "pattern": "^x-\\d+$"}}, "required": ["id", "kind"]}
        errs = self.md(spec, "# T\n\n- id: x-1\n\n## A\n- kind: ignored\n", schema)
        self.assertTrue(any("kind" in e for e in errs), errs)
        self.assertEqual(self.md(spec, "# T\n\n- id: x-1\n- kind: run\n\n## A\n", schema), [])
        self.assertTrue(self.md(spec, "# T\n\n- id: bad\n- kind: run\n", schema))

    def test_bullet_header_keys_are_lowercased_and_may_have_spaces(self):
        spec = {"front_matter": "bullets"}
        schema = {"type": "object", "required": ["working directory"]}
        self.assertEqual(self.md(spec, "- Working Directory: /w\n\n## A\n", schema), [])

    def test_bullet_header_list_coercion(self):
        spec = {"front_matter": "bullets", "coerce": {"depends": "list"}}
        schema = {"type": "object", "properties": {"depends": {"type": "array", "items": {"type": "string", "pattern": "^[a-z-]+$"}}}}
        self.assertEqual(self.md(spec, "- depends: alert-event, run-log\n", schema), [])
        self.assertTrue(self.md(spec, "- depends: alert-event, Bad_Id\n", schema))

    def test_unordered_required_sections_match_case_insensitively_and_by_prefix(self):
        spec = {"front_matter": "none", "required_sections": ["goal", "checks"]}
        self.assertEqual(self.md(spec, "## Checks\n\n## Goal: the one sentence\n"), [])
        errs = self.md(spec, "## Goal\n")
        self.assertTrue(any("'checks'" in e for e in errs), errs)

    def test_required_sections_can_depend_on_a_header_value(self):
        spec = {"front_matter": "bullets",
                "required_sections_when": [{"when": {"kind": ["implement"]}, "sections": ["definitions"]}]}
        self.assertEqual(self.md(spec, "- kind: run\n\n## Goal\n"), [])
        self.assertTrue(self.md(spec, "- kind: implement\n\n## Goal\n"))
        self.assertEqual(self.md(spec, "- kind: implement\n\n## Definitions\nx\n"), [])

    def test_contains_mode_accepts_extra_columns_and_any_case(self):
        spec = {"front_matter": "none", "case_insensitive_titles": True, "tables": [
            {"name": "T", "headers": ["Tool", "Version"], "headers_match": "contains", "min_rows": 1, "section": "Matrix"}]}
        text = "## matrix\n\n| version | note | TOOL |\n|---|---|---|\n| 1.2 | x | a |\n"
        self.assertEqual(self.md(spec, text, {"type": "object", "required": ["Tool", "Version"]}), [])
        errs = self.md(spec, "## Matrix\n\n| Tool |\n|---|\n| a |\n")
        self.assertTrue(any("not found" in e for e in errs), errs)

    def test_contains_mode_names_the_missing_columns(self):
        spec = {"front_matter": "none", "tables": [
            {"name": "T", "headers": ["Tool", "Version"], "headers_match": "contains", "min_rows": 1}]}
        errs = self.md(spec, "## M\n\n| Tool | Other |\n|---|---|\n| a | b |\n")
        self.assertTrue(any("Version" in e for e in errs), errs)

    def test_disjoint_scopes_rule_refuses_overlaps_like_the_sizing_check(self):
        spec = {"front_matter": "none", "tables": [
            {"name": "U", "headers": ["Unit", "Write scope"], "min_rows": 1}],
            "rules": [{"type": "disjoint_scopes", "table": "U", "owner_column": "Unit", "scope_column": "Write scope"}]}
        ok = "## U\n\n| Unit | Write scope |\n|---|---|\n| a | src/a/, README.md |\n| b | src/b/, docs/*.md |\n"
        self.assertEqual(self.md(spec, ok), [])
        for a, b in (("src/", "src/b/x.py"), ("src/a.py", "src/a.py"), ("docs/*.md", "docs/x.md"), ("src/**", "src/b/")):
            with self.subTest(a=a, b=b):
                bad = f"## U\n\n| Unit | Write scope |\n|---|---|\n| a | {a} |\n| b | {b} |\n"
                self.assertTrue(any("overlap" in e for e in self.md(spec, bad)), (a, b))

    def test_row_requires_rule(self):
        spec = {"front_matter": "none", "tables": [{"name": "C", "headers": ["id", "model io", "provider"], "min_rows": 1}],
                "rules": [{"type": "row_requires", "table": "C", "when_column": "model io",
                           "when_not_in": ["", "-"], "column": "provider", "pattern": "^baseline:",
                           "message": "a model slot needs a baseline provider"}]}
        ok = "## C\n\n| id | model io | provider |\n|---|---|---|\n| a | - | stub:x |\n| m | in: a, out: b | baseline:y |\n"
        self.assertEqual(self.md(spec, ok), [])
        bad = "## C\n\n| id | model io | provider |\n|---|---|---|\n| m | in: a, out: b | stub:y |\n"
        self.assertTrue(any("baseline provider" in e for e in self.md(spec, bad)))

    def test_item_rule_joins_continuation_lines(self):
        spec = {"front_matter": "none", "rules": [{"type": "item_rule", "section": "Checks", "item_pattern": "^C\\d+\\b",
                                                  "require": "`[^`\\n]+`", "message": "each check needs a command"}]}
        good = "## Checks\n- C1: run\n  `pytest -q` passes\n- C2: `x`\n"
        self.assertEqual(self.md(spec, good), [])
        self.assertTrue(any("each check" in e for e in self.md(spec, "## Checks\n- C1: no command here\n")))

    def test_section_text_rule(self):
        spec = {"front_matter": "none", "rules": [{"type": "section_text", "section": "Contracts", "pattern": "(?i)produced",
                                                  "message": "list the produced contracts"}]}
        self.assertEqual(self.md(spec, "## Contracts\nConsumed: none. Produced: none.\n"), [])
        self.assertTrue(any("produced contracts" in e for e in self.md(spec, "## Contracts\nConsumed: x\n")))

    def test_section_order_rule(self):
        spec = {"front_matter": "none", "rules": [{"type": "section_order", "first": "Red run", "then": "Green run"}]}
        self.assertEqual(self.md(spec, "## Red run\n## Green run\n"), [])
        self.assertEqual(self.md(spec, "## Green run\n"), [])
        self.assertTrue(self.md(spec, "## Green run\n## Red run\n"))

    def test_line_count_per_matching_row_rule(self):
        spec = {"front_matter": "none", "tables": [{"name": "F", "headers": ["Id", "Status"], "min_rows": 0}],
                "rules": [{"type": "lines_per_row", "table": "F", "match": {"Status": ["fixed"]},
                           "pattern": "^Re-check:", "message": "one Re-check line per fixed finding"}]}
        text = "## F\n\n| Id | Status |\n|---|---|\n| a | fixed |\n| b | fixed |\n\nRe-check: a\n"
        self.assertTrue(any("Re-check" in e for e in self.md(spec, text)))
        self.assertEqual(self.md(spec, text + "Re-check: b\n"), [])

    def test_list_coercion_reads_none_as_empty(self):
        self.assertEqual(contract._coerce("none", "list"), [])
        self.assertEqual(contract._coerce("-", "list"), [])
        self.assertEqual(contract._coerce("a, b", "list"), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
