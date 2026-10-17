"""No test reads the real `~/.claude`: every call of a command that takes a home folder (`context check`, `context measure`)
in the tests passes `--home`. Calls built from a variable argument list are checked where they are written."""
import ast
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
NEEDS_HOME = {("context", "check"), ("context", "measure")}


def literal_args(call):
    out = []
    for a in call.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            out.append(a.value)
        elif isinstance(a, ast.Starred):
            return None
        else:
            out.append(None)
    return out


class NoRealHome(unittest.TestCase):
    def test_every_context_command_in_the_tests_names_a_temporary_home(self):
        offenders = []
        for path in sorted(TESTS.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                args = literal_args(node)
                if not args:
                    continue
                for i in range(len(args) - 1):
                    if (args[i], args[i + 1]) in NEEDS_HOME and "--home" not in args:
                        offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [], "a command that reads ~/.claude without --home")


if __name__ == "__main__":
    unittest.main()
