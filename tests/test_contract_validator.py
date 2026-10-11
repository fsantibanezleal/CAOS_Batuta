"""Validator keyword coverage and refusal of unsupported keywords (harness_lib.contract)."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "harness" / "scripts"))

from harness_lib import contract  # noqa: E402


def errs(instance, schema):
    return contract.validate(instance, schema)


class TypeKeyword(unittest.TestCase):
    def test_each_type_accepts_and_rejects(self):
        cases = {
            "string": ("a", 1), "integer": (3, "3"), "number": (1.5, "1.5"), "boolean": (True, 1),
            "null": (None, 0), "object": ({}, []), "array": ([], {}),
        }
        for t, (good, bad) in cases.items():
            with self.subTest(type=t):
                self.assertEqual(errs(good, {"type": t}), [])
                out = errs(bad, {"type": t})
                self.assertEqual(len(out), 1)
                self.assertIn(f"expected {t}", out[0])

    def test_bool_is_not_integer_or_number(self):
        self.assertTrue(errs(True, {"type": "integer"}))
        self.assertTrue(errs(False, {"type": "number"}))
        self.assertTrue(errs(1, {"type": "boolean"}))

    def test_integer_accepts_integral_float(self):
        self.assertEqual(errs(2.0, {"type": "integer"}), [])
        self.assertTrue(errs(2.5, {"type": "integer"}))

    def test_type_list(self):
        s = {"type": ["integer", "null"]}
        self.assertEqual(errs(None, s), [])
        self.assertEqual(errs(4, s), [])
        self.assertTrue(errs("4", s))


class ScalarKeywords(unittest.TestCase):
    def test_enum(self):
        s = {"enum": ["a", "b"]}
        self.assertEqual(errs("a", s), [])
        self.assertIn("not in enum", errs("c", s)[0])

    def test_enum_does_not_confuse_bool_and_int(self):
        self.assertTrue(errs(1, {"enum": [True]}))
        self.assertEqual(errs(True, {"enum": [True]}), [])

    def test_const(self):
        s = {"const": "1.0"}
        self.assertEqual(errs("1.0", s), [])
        self.assertIn("constant", errs("2.0", s)[0])

    def test_pattern_is_a_search_not_a_full_match_unless_anchored(self):
        self.assertEqual(errs("xxabcxx", {"type": "string", "pattern": "abc"}), [])
        self.assertTrue(errs("xxabcxx", {"type": "string", "pattern": "^abc$"}))
        self.assertIn("does not match pattern", errs("zz", {"type": "string", "pattern": "^a"})[0])

    def test_pattern_ignored_for_non_strings_but_type_catches_them(self):
        self.assertTrue(errs(5, {"type": "string", "pattern": "^a"}))

    def test_min_max_length(self):
        s = {"type": "string", "minLength": 2, "maxLength": 3}
        self.assertEqual(errs("ab", s), [])
        self.assertIn("minLength", errs("a", s)[0])
        self.assertIn("maxLength", errs("abcd", s)[0])

    def test_minimum_maximum(self):
        s = {"type": "integer", "minimum": 1, "maximum": 3}
        self.assertEqual(errs(2, s), [])
        self.assertIn(">= 1", errs(0, s)[0])
        self.assertIn("<= 3", errs(4, s)[0])


class StructureKeywords(unittest.TestCase):
    def test_required_and_error_path(self):
        s = {"type": "object", "required": ["a"], "properties": {"b": {"type": "object", "required": ["c"]}}}
        self.assertEqual(errs({"a": 1}, s), [])
        self.assertEqual(errs({}, s), ["/: missing required property 'a'"])
        self.assertEqual(errs({"a": 1, "b": {}}, s), ["/b: missing required property 'c'"])

    def test_properties_validate_nested_values(self):
        s = {"type": "object", "properties": {"n": {"type": "integer"}}}
        self.assertEqual(errs({"n": "x"}, s), ["/n: expected integer, got string"])

    def test_additional_properties_false(self):
        s = {"type": "object", "properties": {"a": {}}, "additionalProperties": False}
        out = errs({"a": 1, "z": 2}, s)
        self.assertEqual(len(out), 1)
        self.assertIn("/z", out[0])
        self.assertIn("unexpected property", out[0])

    def test_additional_properties_true_and_default(self):
        self.assertEqual(errs({"z": 1}, {"type": "object", "additionalProperties": True}), [])
        self.assertEqual(errs({"z": 1}, {"type": "object"}), [])

    def test_additional_properties_schema(self):
        s = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": {"type": "integer"}}
        self.assertEqual(errs({"a": "x", "b": 1}, s), [])
        self.assertEqual(errs({"a": "x", "b": "no"}, s), ["/b: expected integer, got string"])

    def test_items_and_min_items(self):
        s = {"type": "array", "items": {"type": "integer"}, "minItems": 2}
        self.assertEqual(errs([1, 2], s), [])
        self.assertEqual(errs([1, "x"], s), ["/1: expected integer, got string"])
        self.assertIn("minItems", errs([1], s)[0])

    def test_pointer_escapes_slash_and_tilde_in_keys(self):
        s = {"type": "object", "additionalProperties": {"type": "integer"}}
        self.assertEqual(errs({"a/b": "x"}, s), ["/a~1b: expected integer, got string"])
        self.assertEqual(errs({"a~b": "x"}, s), ["/a~0b: expected integer, got string"])

    def test_ref_to_defs(self):
        s = {"type": "object", "properties": {"x": {"$ref": "#/$defs/n"}}, "$defs": {"n": {"type": "integer", "minimum": 5}}}
        self.assertEqual(errs({"x": 6}, s), [])
        self.assertEqual(errs({"x": 1}, s), ["/x: 1 must be >= 5"])

    def test_ref_inside_array_items(self):
        s = {"type": "array", "items": {"$ref": "#/$defs/e"}, "$defs": {"e": {"type": "object", "required": ["k"]}}}
        self.assertEqual(errs([{"k": 1}, {}], s), ["/1: missing required property 'k'"])

    def test_all_errors_are_collected(self):
        s = {"type": "object", "required": ["a", "b"]}
        self.assertEqual(len(errs({}, s)), 2)


class SchemaChecking(unittest.TestCase):
    def test_supported_subset_is_accepted(self):
        s = {"$schema": "https://json-schema.org/draft/2020-12/schema", "contract_id": "CX", "contract_version": "1.0",
             "title": "t", "description": "d", "type": "object", "required": ["a"],
             "properties": {"a": {"$ref": "#/$defs/s"}}, "additionalProperties": False,
             "$defs": {"s": {"type": "string", "enum": ["x"], "pattern": "^x$", "minLength": 1, "maxLength": 3}}}
        self.assertEqual(contract.check_schema(s), [])

    def test_unsupported_keywords_are_refused(self):
        for kw, val in [("oneOf", [{}]), ("allOf", [{}]), ("anyOf", [{}]), ("not", {}), ("if", {}), ("then", {}),
                        ("patternProperties", {}), ("format", "date"), ("uniqueItems", True), ("minProperties", 1),
                        ("maxItems", 3), ("exclusiveMinimum", 1), ("multipleOf", 2), ("dependentRequired", {}),
                        ("propertyNames", {}), ("contains", {}), ("prefixItems", [])]:
            with self.subTest(keyword=kw):
                out = contract.check_schema({"type": "object", kw: val})
                self.assertTrue(out, kw)
                self.assertIn(kw, out[0])
                self.assertIn("unsupported keyword", out[0])

    def test_unsupported_keyword_nested_is_found(self):
        out = contract.check_schema({"type": "object", "properties": {"a": {"type": "array", "items": {"oneOf": []}}}})
        self.assertTrue(any("/properties/a/items" in e and "oneOf" in e for e in out), out)

    def test_property_named_like_a_keyword_is_not_a_keyword(self):
        s = {"type": "object", "properties": {"format": {"type": "string"}, "not": {"type": "string"}}}
        self.assertEqual(contract.check_schema(s), [])

    def test_bad_ref_is_refused(self):
        self.assertTrue(contract.check_schema({"$ref": "#/$defs/missing"}))
        self.assertTrue(contract.check_schema({"$ref": "other.json#/$defs/x"}))
        self.assertTrue(contract.check_schema({"$ref": "#/properties/x"}))

    def test_bad_values_are_refused(self):
        self.assertTrue(contract.check_schema({"type": "date"}))
        self.assertTrue(contract.check_schema({"pattern": "("}))
        self.assertTrue(contract.check_schema({"required": "a"}))
        self.assertTrue(contract.check_schema({"minimum": "1"}))
        self.assertTrue(contract.check_schema({"properties": []}))

    def test_load_schema_refuses_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "x.schema.json"
            p.write_text('{"type": "object", "oneOf": []}', encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                contract.load_schema(p)
            self.assertIn("oneOf", str(cm.exception))
            p.write_text('{"type": "object", "required": ["a"]}', encoding="utf-8")
            self.assertEqual(contract.load_schema(p)["required"], ["a"])
            p.write_text("{nope", encoding="utf-8")
            with self.assertRaises(ValueError):
                contract.load_schema(p)


class JsonlValidation(unittest.TestCase):
    S = {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}, "additionalProperties": False}

    def test_valid_lines_comments_and_blanks(self):
        self.assertEqual(contract.validate_jsonl('# note\n{"id": 1}\n\n{"id": 2}\n', self.S), [])
        self.assertEqual(contract.validate_jsonl("", self.S), [])

    def test_errors_carry_line_numbers(self):
        out = contract.validate_jsonl('{"id": 1}\n{"id": "x"}\n{}\n', self.S)
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0].startswith("line 2 /id:"), out)
        self.assertTrue(out[1].startswith("line 3 /:"), out)

    def test_invalid_json_line(self):
        out = contract.validate_jsonl('{"id": 1}\n{oops\n', self.S)
        self.assertEqual(len(out), 1)
        self.assertIn("line 2", out[0])
        self.assertIn("invalid JSON", out[0])

    def test_line_must_be_an_object_per_schema(self):
        out = contract.validate_jsonl("[1]\n", self.S)
        self.assertIn("expected object", out[0])


if __name__ == "__main__":
    unittest.main()
