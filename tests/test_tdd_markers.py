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

    def test_a_custom_marker_list_extends_the_default_and_never_removes_a_marker(self):
        src = "import unittest\n@unittest.skip('x')\ndef test_a(): pass\n@wip\ndef test_b(): pass\n"
        found = tm.weakening_markers("tests/test_x.py", src, {"python": ["wip"]})
        self.assertEqual(sum(found.values()), 2)
        self.assertEqual(sum(tm.weakening_markers("tests/test_x.py", src, {"python": ["unittest.skip"]}).values()), 1)
        js = tm.weakening_markers("web/a.test.js", "it.only('a', () => {});\nwip('b', () => {});\n", {"javascript": ["wip"]})
        self.assertEqual(sum(js.values()), 2)


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


class ReviewPythonMarkers(unittest.TestCase):
    """C-06 and M-02: aliases, renamed imports and skip equivalents."""

    def count(self, src, markers=None):
        return sum(tm.weakening_markers("tests/test_x.py", src, markers).values())

    def test_an_aliased_module_or_a_renamed_import_is_resolved(self):
        cases = [
            "import unittest as u\n@u.skip('x')\ndef test_a(): pass\n",
            "from unittest import skip as s\n@s('x')\ndef test_a(): pass\n",
            "import pytest as p\n@p.mark.skip\ndef test_a(): pass\n",
            "from pytest import mark\n@mark.skip\ndef test_a(): pass\n",
            "from pytest import mark as m\n@m.xfail\ndef test_a(): pass\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertEqual(self.count(src), 1)

    def test_skip_equivalents_are_markers(self):
        cases = [
            "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.skipTest('x')\n",
            "import unittest\ndef test_a():\n    raise unittest.SkipTest('x')\n",
            "from unittest import SkipTest\ndef test_a():\n    raise SkipTest('x')\n",
            "import unittest\n@getattr(unittest, 'skip')('x')\ndef test_a(): pass\n",
            "import pytest\ndef test_a():\n    pytest.importorskip('nope_xyz')\n",
            "import unittest\nunittest.TestCase.run = lambda self, result=None: None\n",
            "import pytest\ndef pytest_collection_modifyitems(items):\n    for item in items:\n        item.add_marker(pytest.mark.skip(reason='x'))\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertGreaterEqual(self.count(src), 1)

    def test_ordinary_names_are_not_markers(self):
        self.assertEqual(self.count("skipped = 3\nskip_count = skipped + 1\ndef test_a():\n    assert skipped == 3\n"), 0)


class ReviewJavascriptMarkers(unittest.TestCase):
    """C-06, m-04: member chains, bracket access, destructuring, regex literals, focus forms."""

    def count(self, src):
        return sum(tm.weakening_markers("web/a.test.js", src).values())

    def test_member_chains_brackets_and_destructuring_are_markers(self):
        cases = [
            "it['only']('a', () => {});\n",
            "globalThis.it.only('a', () => {});\n",
            "const { only } = it;\nonly('a', () => {});\n",
            "window . test . skip('a', () => {});\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertGreaterEqual(self.count(src), 1)

    def test_a_regex_literal_holding_a_quote_does_not_hide_a_marker(self):
        for quote in ("`", "'", '"'):
            with self.subTest(quote=quote):
                src = f"const r = /{quote}/;\nit.only('a', () => {{}});\nconst q = /{quote}/;\n"
                self.assertEqual(self.count(src), 1)

    def test_more_focus_and_skip_forms_are_markers(self):
        for marker in ("fit", "fdescribe", "xtest", "describe.todo", "it.todo"):
            with self.subTest(marker=marker):
                self.assertEqual(self.count(f"{marker}('works', () => {{ expect(1).toBe(1); }});\n"), 1)

    def test_a_division_is_not_a_regex_and_exit_is_not_xit(self):
        self.assertEqual(self.count("const a = b / c;\nconst exit = 1; it('ok', () => {});\nconst d = e / f;\n"), 0)


class ReviewAssertionCounts(unittest.TestCase):
    """C-07: evasions that keep the number but not the assertions."""

    def count(self, src, path="tests/test_x.py"):
        return tm.assertion_count(path, src)

    def test_a_local_no_op_helper_named_assert_does_not_count(self):
        src = "def assert_same(*a):\n    pass\n\n\ndef test_a():\n    assert_same(1, 1)\n    assert_same(2, 2)\n"
        self.assertEqual(self.count(src), 0)

    def test_a_local_helper_that_asserts_counts_in_its_body_and_at_its_calls(self):
        src = "def assert_same(a, b):\n    assert a == b\n\n\ndef test_a():\n    assert_same(1, 1)\n"
        self.assertEqual(self.count(src), 2)

    def test_an_imported_assert_function_counts_and_an_unknown_one_does_not(self):
        self.assertEqual(self.count("from numpy.testing import assert_allclose\ndef test_a():\n    assert_allclose(1, 1)\n"), 1)
        self.assertEqual(self.count("from helpers import assert_same\ndef test_a():\n    assert_same(1, 1)\n"), 0)

    def test_asserts_under_a_constant_false_branch_do_not_count(self):
        for test in ("False", "0", "None"):
            with self.subTest(test=test):
                self.assertEqual(self.count(f"def test_a():\n    if {test}:\n        assert 1 == 1\n        assert 2 == 2\n"), 0)
        self.assertEqual(self.count("def test_a():\n    if True:\n        assert 1 == 1\n"), 1)

    def test_asserts_inside_a_try_that_swallows_assertion_errors_do_not_count(self):
        swallow = ("AssertionError", "Exception", "BaseException")
        for name in swallow:
            with self.subTest(name=name):
                src = f"def test_a():\n    try:\n        assert 1 == 2\n    except {name}:\n        pass\n"
                self.assertEqual(self.count(src), 0)
        self.assertEqual(self.count("def test_a():\n    try:\n        assert 1 == 2\n    except:\n        pass\n"), 0)
        self.assertEqual(self.count("def test_a():\n    try:\n        assert 1 == 1\n    except ValueError:\n        pass\n"), 1)

    def test_javascript_regex_literals_do_not_blank_the_expect_calls(self):
        for quote in ("`", "'", '"'):
            with self.subTest(quote=quote):
                self.assertEqual(self.count(f"const r = /{quote}/;\nexpect(1).toBe(1);\nconst q = /{quote}/;\n", "web/a.test.js"), 1)
        self.assertEqual(self.count("const a = b / c;\nexpect(1).toBe(1);\nconst d = e / f;\n", "web/a.test.js"), 1)


class SecondRoundPythonMarkers(unittest.TestCase):
    """R2-02 and R2-03: import by call, name aliases, collection hooks."""

    def count(self, src, path="tests/test_x.py"):
        return sum(tm.weakening_markers(path, src).values())

    def test_a_module_reached_through_importlib_or_dunder_import_is_resolved(self):
        cases = [
            "import importlib\nu = importlib.import_module('unittest')\n@u.skip('x')\ndef test_a(): pass\n",
            "import importlib\n@importlib.import_module('unittest').skip('x')\ndef test_a(): pass\n",
            "@__import__('unittest').skip('x')\ndef test_a(): pass\n",
            "import unittest\nu = unittest\n@u.skip('x')\ndef test_a(): pass\n",
            "import unittest\ns = unittest.skip\n@s('x')\ndef test_a(): pass\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertGreaterEqual(self.count(src), 1)

    def test_collection_hooks_and_ignore_lists_are_markers(self):
        cases = [
            "import unittest\ndef load_tests(loader, tests, pattern):\n    return unittest.TestSuite()\n",
            "collect_ignore = ['test_calc.py']\n",
            "collect_ignore_glob = ['test_*.py']\n",
            "def pytest_collection_modifyitems(config, items):\n    items.clear()\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertGreaterEqual(self.count(src, "tests/conftest.py"), 1)

    def test_runner_settings_that_deselect_tests_are_markers(self):
        cases = [
            ("pytest.ini", '[pytest]\naddopts = -k "not test_add"\n'),
            ("setup.cfg", "[tool:pytest]\npython_files = check_*.py\n"),
            ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = "--deselect tests/test_a.py::test_x"\n'),
            ("tox.ini", "[pytest]\ntestpaths = nothing\n"),
            ("pytest.ini", "[pytest]\nnorecursedirs = tests\n"),
        ]
        for path, text in cases:
            with self.subTest(path=path):
                self.assertGreaterEqual(self.count(text, path), 1)

    def test_a_pyproject_without_a_pytest_section_is_clean(self):
        self.assertEqual(self.count('[tool.ruff]\nselect = ["E"]\naddopts = "-k x"\n', "pyproject.toml"), 0)


class ThirdRoundPythonMarkers(unittest.TestCase):
    """R3-03: the module that defines `skip`, sys.modules lookups, computed module names."""

    def count(self, src):
        return sum(tm.weakening_markers("tests/test_x.py", src).values())

    def test_other_spellings_of_the_unittest_and_pytest_modules_are_resolved(self):
        cases = [
            "import unittest\n@unittest.case.skip('x')\ndef test_a(): pass\n",
            "from unittest import case\n@case.skip('x')\ndef test_a(): pass\n",
            "from unittest.case import skip\n@skip('x')\ndef test_a(): pass\n",
            "import unittest\ndef test_a():\n    raise unittest.case.SkipTest('x')\n",
            "import sys\nu = sys.modules['unittest']\n@u.skip('x')\ndef test_a(): pass\n",
            "import sys\n@sys.modules['unittest'].skip('x')\ndef test_a(): pass\n",
            "from _pytest.outcomes import skip\ndef test_a():\n    skip('x')\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertGreaterEqual(self.count(src), 1)

    def test_a_module_imported_by_a_computed_name_is_a_marker(self):
        cases = [
            "import importlib\nu = importlib.import_module('unit' + 'test')\n@u.skip('x')\ndef test_a(): pass\n",
            "name = 'unittest'\nu = __import__(name)\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertGreaterEqual(self.count(src), 1)

    def test_a_literal_import_of_an_ordinary_module_is_not(self):
        self.assertEqual(self.count("import importlib\nm = importlib.import_module('json')\n"), 0)


class ThirdRoundListing(unittest.TestCase):
    """R3-01 and R3-02: the recorded outcome of each locked test, parametrized ids, the JUnit report of pytest."""

    def test_an_expected_failure_and_a_skip_are_problems_a_pass_is_not(self):
        from batuta_lib import tdd_history as hist
        base = [("C", "test_a"), ("C", "test_b"), ("C", "test_c")]
        listing = [{"id": "test_m.C.test_a", "outcome": "passed"}, {"id": "test_m.C.test_b", "outcome": "expected failure"},
                   {"id": "test_m.C.test_c", "outcome": "skipped"}]
        problems = hist.compare_listing("tests/test_m.py", base, listing)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("test_b" in p and "expected failure" in p for p in problems))
        self.assertTrue(any("test_c" in p and "skipped" in p for p in problems))
        failing = [{"id": "test_m.C.test_a", "outcome": "failed"}, {"id": "test_m.C.test_b", "outcome": "error"}]
        self.assertEqual(hist.compare_listing("tests/test_m.py", base[:2], failing), [])

    def test_a_parametrized_test_is_compared_by_its_base_name(self):
        from batuta_lib import tdd_history as hist
        ok = [{"id": "tests/test_p.py::test_x[1]", "outcome": "passed"}, {"id": "tests/test_p.py::test_x[2]", "outcome": "skipped"}]
        self.assertEqual(hist.compare_listing("tests/test_p.py", [(None, "test_x")], ok), [])
        gone = [{"id": "tests/test_p.py::test_y[1]", "outcome": "passed"}]
        self.assertEqual(len(hist.compare_listing("tests/test_p.py", [(None, "test_x")], gone)), 1)
        allskipped = [{"id": "tests/test_p.py::test_x[1]", "outcome": "skipped"}]
        self.assertEqual(len(hist.compare_listing("tests/test_p.py", [(None, "test_x")], allskipped)), 1)

    def test_a_junit_report_is_read_into_outcomes(self):
        from batuta_lib import tdd_history as hist
        xml = ('<testsuites><testsuite>'
               '<testcase classname="tests.test_p" name="test_x[1]"/>'
               '<testcase classname="tests.test_p" name="test_x[2]"><skipped type="pytest.skip" message="s"/></testcase>'
               '<testcase classname="tests.test_p.C" name="test_y"><skipped type="pytest.xfail" message="x"/></testcase>'
               '<testcase classname="tests.test_p" name="test_z"><failure message="f"/></testcase>'
               '<testcase classname="tests.test_p" name="test_e"><error message="e"/></testcase>'
               '</testsuite></testsuites>')
        got = {e["id"]: e["outcome"] for e in hist.parse_junit(xml)}
        self.assertEqual(got, {"tests.test_p.test_x[1]": "passed", "tests.test_p.test_x[2]": "skipped",
                               "tests.test_p.C.test_y": "expected failure", "tests.test_p.test_z": "failed", "tests.test_p.test_e": "error"})

    def test_an_empty_listing_is_a_listing(self):
        from batuta_lib import tdd_history as hist
        self.assertEqual(hist.parse_unittest_listing("no tests here\n[]\n"), [])


class SecondRoundJavascriptMarkers(unittest.TestCase):
    def count(self, src):
        return sum(tm.weakening_markers("web/a.test.js", src).values())

    def test_aliases_template_keys_and_regex_after_a_condition(self):
        cases = [
            "const t = it;\nt.only('a', () => {});\n",
            "let d = describe;\nd.skip('a', () => {});\n",
            "it[`only`]('a', () => {});\n",
            "if (true) /`/.test('a');\nit.only('a', () => {});\n",
            "while (x) /'/.test(y);\nit.only('a', () => {});\nconst z = /'/;\n",
        ]
        for src in cases:
            with self.subTest(src=src):
                self.assertGreaterEqual(self.count(src), 1)

    def test_a_division_after_a_parenthesis_is_not_a_regex(self):
        self.assertEqual(self.count("const a = (b) / c;\nit.only('x', () => {});\nconst d = (e) / f;\n"), 1)


class SecondRoundAssertionCounts(unittest.TestCase):
    def count(self, src):
        return tm.assertion_count("tests/test_x.py", src)

    def test_a_helper_whose_assertion_ignores_its_arguments_does_not_count_at_its_calls(self):
        src = "def assert_same(*a):\n    assert True\n\n\ndef test_a():\n    assert_same(1, 1)\n    assert_same(2, 2)\n"
        self.assertEqual(self.count(src), 0)

    def test_a_constant_true_assert_does_not_count(self):
        self.assertEqual(self.count("def test_a():\n    assert True\n    assert 1\n"), 0)

    def test_a_local_assert_method_counts_only_when_it_asserts(self):
        noop = ("import unittest\nclass T(unittest.TestCase):\n    def assert_same(self, *a):\n        pass\n"
                "    def test_a(self):\n        self.assert_same(1, 1)\n        self.assertEqual(1, 1)\n")
        real = ("import unittest\nclass T(unittest.TestCase):\n    def assert_same(self, a, b):\n        self.assertEqual(a, b)\n"
                "    def test_a(self):\n        self.assert_same(1, 1)\n")
        self.assertEqual(self.count(noop), 1)
        self.assertEqual(self.count(real), 2)

    def test_asserts_after_a_return_a_raise_a_continue_or_a_break_do_not_count(self):
        self.assertEqual(self.count("def test_a():\n    return\n    assert 1 == 2\n"), 0)
        self.assertEqual(self.count("def test_a():\n    raise ValueError('x')\n    assert 1 == 2\n"), 0)
        self.assertEqual(self.count("def test_a():\n    for i in range(2):\n        continue\n        assert i == 5\n"), 0)

    def test_a_constant_expression_that_is_false_hides_its_branch(self):
        self.assertEqual(self.count("def test_a():\n    if 1 == 2:\n        assert 1 == 1\n"), 0)
        self.assertEqual(self.count("def test_a():\n    if 1 + 1 == 2:\n        assert 1 == 1\n"), 1)

    def test_suppressing_assertion_errors_hides_the_block(self):
        src = "import contextlib\ndef test_a():\n    with contextlib.suppress(AssertionError):\n        assert 1 == 2\n"
        self.assertEqual(self.count(src), 0)
        ok = "import contextlib\ndef test_a():\n    with contextlib.suppress(KeyError):\n        assert 1 == 1\n"
        self.assertEqual(self.count(ok), 1)

    def test_a_nested_function_counts_only_when_it_is_used(self):
        never = "def test_a():\n    def inner():\n        assert 1 == 1\n"
        called = "def test_a():\n    def inner():\n        assert 1 == 1\n    inner()\n"
        self.assertEqual(self.count(never), 0)
        self.assertEqual(self.count(called), 1)


if __name__ == "__main__":
    unittest.main()
