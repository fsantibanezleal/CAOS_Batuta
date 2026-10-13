"""test_markers: hashes, requirement ids, weakening markers and assertion counts (AST for Python)."""
import hashlib
import sys
import unittest

from _support import SCRIPTS

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib import test_markers as tm  # noqa: E402


class Hashing(unittest.TestCase):
    def test_crlf_and_lf_hash_the_same(self):
        self.assertEqual(tm.normalized_sha256(b"a\r\nb\r\n"), tm.normalized_sha256(b"a\nb\n"))
        self.assertEqual(tm.normalized_sha256(b"a\nb\n"), hashlib.sha256(b"a\nb\n").hexdigest())

    def test_a_changed_byte_changes_the_hash(self):
        self.assertNotEqual(tm.normalized_sha256(b"a\n"), tm.normalized_sha256(b"b\n"))

    def test_a_lone_carriage_return_is_content(self):
        self.assertNotEqual(tm.normalized_sha256(b"a\rb"), tm.normalized_sha256(b"a\nb"))


class RequirementIds(unittest.TestCase):
    def test_ids_are_read_from_req_marker_lines(self):
        text = "# REQ: REQ-CALC-001, REQ-CALC-002\n// REQ: REQ-WEB-003\nx = 'REQ-NOT-001'\n"
        self.assertEqual(tm.requirement_ids(text), ["REQ-CALC-001", "REQ-CALC-002", "REQ-WEB-003"])

    def test_no_marker_gives_no_ids_and_duplicates_collapse(self):
        self.assertEqual(tm.requirement_ids("def test(): pass\n"), [])
        self.assertEqual(tm.requirement_ids("# REQ: REQ-A-001\n# REQ: REQ-A-001\n"), ["REQ-A-001"])


class TestPaths(unittest.TestCase):
    def test_test_file_names(self):
        for path in ("tests/test_a.py", "pkg/b_test.py", "web/a.test.ts", "web/a.spec.js", "web/__tests__/a.js"):
            with self.subTest(path=path):
                self.assertTrue(tm.is_test_path(path))
        for path in ("calc.py", "README.md", "src/app.ts", "tests/data.json"):
            with self.subTest(path=path):
                self.assertFalse(tm.is_test_path(path))

    def test_language_by_extension(self):
        self.assertEqual(tm.language_of("a/test_x.py"), "python")
        self.assertEqual(tm.language_of("a.test.tsx"), "javascript")
        self.assertIsNone(tm.language_of("a.md"))


class PythonMarkers(unittest.TestCase):
    def count(self, src):
        return sum(tm.weakening_markers("tests/test_x.py", src).values())

    def test_each_default_marker_is_found(self):
        cases = [
            "import unittest\n@unittest.skip('x')\ndef test_a(): pass\n",
            "import unittest\n@unittest.skipIf(True, 'x')\ndef test_a(): pass\n",
            "import unittest\n@unittest.skipUnless(False, 'x')\ndef test_a(): pass\n",
            "import unittest\n@unittest.expectedFailure\ndef test_a(): pass\n",
            "import pytest\n@pytest.mark.skip\ndef test_a(): pass\n",
            "import pytest\n@pytest.mark.xfail(reason='x')\ndef test_a(): pass\n",
            "import pytest\ndef test_a():\n    pytest.skip('x')\n",
            "from unittest import skip\n@skip('x')\ndef test_a(): pass\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertEqual(self.count(src), 1)

    def test_a_marker_inside_a_string_or_comment_is_not_a_marker(self):
        src = "# @unittest.skip is forbidden\nS = '@unittest.skip(\"x\")'\ndef test_a():\n    \"\"\"pytest.skip( in prose\"\"\"\n"
        self.assertEqual(self.count(src), 0)

    def test_a_syntax_error_is_reported(self):
        with self.assertRaises(tm.UnparsableTestFile):
            tm.weakening_markers("tests/test_x.py", "def broken(:\n")

    def test_a_custom_marker_list_replaces_the_default(self):
        src = "import unittest\n@unittest.skip('x')\ndef test_a(): pass\n@wip\ndef test_b(): pass\n"
        found = tm.weakening_markers("tests/test_x.py", src, {"python": ["wip"]})
        self.assertEqual(sum(found.values()), 1)


class JavascriptMarkers(unittest.TestCase):
    def count(self, src):
        return sum(tm.weakening_markers("web/a.test.js", src).values())

    def test_each_default_marker_is_found(self):
        for marker in ("it.only", "describe.only", "test.only", "it.skip", "describe.skip", "test.skip", "xit", "xdescribe", "test.todo"):
            with self.subTest(marker=marker):
                self.assertEqual(self.count(f"{marker}('works', () => {{ expect(1).toBe(1); }});\n"), 1)

    def test_comments_and_strings_do_not_count(self):
        src = "// it.only('a')\n/* test.skip('b') */\nconst s = \"xit('c')\";\nconst t = `describe.only`;\nit('ok', () => {});\n"
        self.assertEqual(self.count(src), 0)

    def test_an_identifier_that_only_contains_the_marker_is_not_one(self):
        self.assertEqual(self.count("const exit = 1; const xits = 2; audit.only = 3;\n"), 0)


class AssertionCounts(unittest.TestCase):
    def test_python_counts_assert_statements_and_assert_calls(self):
        src = (
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        self.assertEqual(1, 1)\n"
            "        self.assertTrue(True)\n"
            "        assert 1 == 1\n"
            "        with self.assertRaises(ValueError):\n"
            "            int('x')\n"
        )
        self.assertEqual(tm.assertion_count("tests/test_x.py", src), 4)

    def test_python_ignores_assert_words_in_strings_and_comments(self):
        src = "def test_a():\n    # assert 1\n    s = 'assert x'\n    \"\"\"self.assertEqual(1, 2)\"\"\"\n"
        self.assertEqual(tm.assertion_count("tests/test_x.py", src), 0)

    def test_python_syntax_error_is_reported(self):
        with self.assertRaises(tm.UnparsableTestFile):
            tm.assertion_count("tests/test_x.py", "def (:\n")

    def test_javascript_counts_expect_and_assert_calls_outside_comments_and_strings(self):
        src = (
            "it('a', () => {\n"
            "  expect(1).toBe(1);\n"
            "  expect(2).toBe(2);\n"
            "  assert(true);\n"
            "  // expect(3)\n"
            "  const s = 'expect(4)';\n"
            "});\n"
        )
        self.assertEqual(tm.assertion_count("web/a.test.ts", src), 3)

    def test_other_languages_have_no_count(self):
        self.assertIsNone(tm.assertion_count("notes.md", "assert(1)"))


if __name__ == "__main__":
    unittest.main()
