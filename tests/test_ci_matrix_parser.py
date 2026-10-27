"""The unittest verbose parser reads the same ids from every supported interpreter: before Python 3.11 a verbose line is
`test_x (module.Class) ... ok`, from 3.11 it is `test_x (module.Class.test_x) ... ok`. The two fixtures are real output of
the same test module run by Python 3.10 and by Python 3.14."""
import sys
import unittest
from pathlib import Path

from _support import SCRIPTS

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib import tdd_history as hist  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXPECTED = {
    "tests.test_calc.CalcTests.test_add": "passed", "tests.test_calc.CalcTests.test_error": "error",
    "tests.test_calc.CalcTests.test_fail": "failed", "tests.test_calc.CalcTests.test_skip": "skipped",
    "tests.test_calc.CalcTests.test_sub": "passed", "tests.test_calc.CalcTests.test_sub_tests": "passed",
    "tests.test_calc.CalcTests.test_xfail": "expected failure", "tests.test_calc.CalcTests.test_xpass": "unexpected success",
    "tests.test_calc.test_twin.test_other": "passed", "tests.test_calc.test_twin.test_twin": "passed",
}


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8").replace("\r\n", "\n")


class BothFormsGiveTheSameIds(unittest.TestCase):
    def ids(self, name):
        return {e["id"]: e["outcome"] for e in hist.parse_unittest_verbose(read(name))}

    def test_python_310_output_gives_module_class_method(self):
        self.assertEqual(self.ids("unittest-verbose-py310.txt"), EXPECTED)

    def test_python_314_output_gives_module_class_method(self):
        self.assertEqual(self.ids("unittest-verbose-py314.txt"), EXPECTED)

    def test_the_two_forms_give_identical_lists_in_order(self):
        old = [(e["id"], e["outcome"]) for e in hist.parse_unittest_verbose(read("unittest-verbose-py310.txt"))]
        new = [(e["id"], e["outcome"]) for e in hist.parse_unittest_verbose(read("unittest-verbose-py314.txt"))]
        self.assertEqual(old, new)

    def test_both_forms_pass_the_check_against_the_runner_summary(self):
        for name in ("unittest-verbose-py310.txt", "unittest-verbose-py314.txt"):
            self.assertEqual(len(hist.check_unittest_run(read(name))), 10, name)

    def test_a_subtest_suffix_on_the_old_form_is_read(self):
        text = "test_h (test_m.C) (i=1) ... ok\ntest_a (test_m.C) ... ok\n\nRan 1 test\n"
        got = hist.parse_unittest_verbose(text)
        self.assertEqual([(e["id"], e["sub"]) for e in got], [("test_m.C.test_h", True), ("test_m.C.test_a", False)])

    def test_a_docstring_line_on_the_old_form_is_read(self):
        text = "test_g (test_m.C)\nA docstring line ... ok\n"
        self.assertEqual([e["id"] for e in hist.parse_unittest_verbose(text)], ["test_m.C.test_g"])
