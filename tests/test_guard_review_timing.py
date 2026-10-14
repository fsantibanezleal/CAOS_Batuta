"""F-31 and F-32 (timing probe): no pattern of the guards or of the leaks scan backtracks on a long hostile input. Every
compiled pattern is run over 50,000-character inputs with a generous bound."""
import re
import sys
import time
import unittest

from test_guard_common import SCRIPTS  # noqa: F401  (puts the scripts folder on sys.path)

from batuta_lib.areas import leaks
from batuta_lib.guards import approvals, automation, destructive, locked_tests, require_brief, secrets, shell
from batuta_lib.guards import text as textlib

N = 50000
BOUND = 0.5
INPUTS = {
    "letters": "a" * N,
    "words": "a " * (N // 2),
    "slashes": "a/" * (N // 2),
    "dots": "a." * (N // 2),
    "dashes": "-" * N,
    "backslashes": "\\" * N,
    "ats": "@" * N,
    "local-at": "a@" * (N // 2),
    "domain-labels": "x@" + "a." * (N // 2),
    "sk-prefix": "sk-" * (N // 3),
    "token-prefixes": "ghp_" * (N // 4) + "AKIA" * 10 + "hf_" * 10 + "npm_" * 10 + "glpat-" * 10 + "pypi-" * 10,
    "home": "/home/" * (N // 6),
    "drive": ("C:" + "/Users/") * (N // 9),
    "quotes": '"a' * (N // 2),
    "single-quotes": "'a" * (N // 2),
    "braces": "f(){ " * (N // 5),
    "keyword-schtasks": "schtasks " * (N // 9),
    "keyword-start-process": "Start-Process " * (N // 14),
    "keyword-reg": "reg add " * (N // 8),
    "keyword-claude": "claude " * (N // 7),
    "semicolons": "; " * (N // 2),
    "pipes": "| " * (N // 2),
    "brief-ish": "x.brief.m" * (N // 9),
    "brief-run": "/" + "a" * N + ".brief.md.x",
    "git-push": "git push " * (N // 9),
    "no-newline-keywords": "systemctl --user " * (N // 17),
    "redirects": ">a" * (N // 2),
    "newlines": "\n" * N,
    "escaped-quotes": '"\\' * (N // 2),
    "dollar-brace": "${" * (N // 2),
    "bracket-run": "[a" * (N // 2),
    "create-link": "CreateSymbolicLink(" * (N // 19),
    "timeout-flags": "timeout -a " * (N // 11),
    "claude-flags": "claude -x " * (N // 10),
    "function-heads": "function f { " * (N // 13),
    "claude-models": "claude --model claude-sonnet-4-5 " * (N // 31),
    "claude-segments": "; claude --model claude-opus-4-1 -x " * (N // 35),
    "claude-subshells": "(claude --model claude-x " * (N // 24),
    "backtick-run": "`a" * (N // 2),
    "brace-run": "{a" * (N // 2),
    "assign-run": "$a=1 " * (N // 5),
    "spaces": " " * N,
    "tabs-and-ats": "&" + " " * N,
}


def collect():
    """(name, compiled pattern) of every module-level pattern and every pattern inside the rule tables."""
    found = []
    for module in (automation, destructive, secrets, locked_tests, approvals, require_brief, textlib, shell, leaks):
        for attr, value in vars(module).items():
            if isinstance(value, re.Pattern):
                found.append((f"{module.__name__.rsplit('.', 1)[-1]}.{attr}", value))
            elif isinstance(value, list):
                for i, entry in enumerate(value):
                    items = entry if isinstance(entry, tuple) else (entry,)
                    for part in items:
                        if isinstance(part, re.Pattern):
                            found.append((f"{module.__name__.rsplit('.', 1)[-1]}.{attr}[{i}]", part))
            elif isinstance(value, tuple):
                for i, part in enumerate(value):
                    if isinstance(part, re.Pattern):
                        found.append((f"{module.__name__.rsplit('.', 1)[-1]}.{attr}[{i}]", part))
    return found


class PatternTiming(unittest.TestCase):
    def test_there_are_many_patterns_to_check(self):
        self.assertGreater(len(collect()), 50)

    def test_every_pattern_is_fast_on_every_hostile_input(self):
        slow = []
        for name, pattern in collect():
            for label, text in INPUTS.items():
                start = time.perf_counter()
                pattern.search(text)
                elapsed = time.perf_counter() - start
                if elapsed > BOUND:
                    slow.append(f"{name} on {label}: {elapsed:.2f}s")
        self.assertEqual(slow, [], "\n".join(slow))

    def test_the_functions_that_run_patterns_are_fast_too(self):
        functions = {
            "require_brief.brief_paths": require_brief.brief_paths,
            "require_brief.last_line": require_brief.last_line,
            "leaks.emails_in": lambda t: list(leaks.emails_in(t)),
            "leaks.scan_line": lambda t: leaks.scan_line(t, leaks.DEFAULT_ALLOW_EMAILS),
            "text.nested_texts": textlib.nested_texts,
            "text.deobfuscate": textlib.deobfuscate,
            "text.decoded_commands": textlib.decoded_commands,
            "automation.scan_hits": automation.scan_hits,
            "automation.self_calling_function": automation.self_calling_function,
        }
        slow = []
        for name, function in functions.items():
            for label, text in INPUTS.items():
                start = time.perf_counter()
                function(text)
                elapsed = time.perf_counter() - start
                if elapsed > 2.0:
                    slow.append(f"{name} on {label}: {elapsed:.2f}s")
        self.assertEqual(slow, [], "\n".join(slow))


class BriefPathsAreStillFound(unittest.TestCase):
    """The rewrite must keep the old behaviour on ordinary prompts."""

    CASES = {
        "Your brief is /work/x/a.brief.md. Follow it.": ["/work/x/a.brief.md"],
        "brief: C:/work/b.brief.md and C:\\work\\c.brief.md": ["C:/work/b.brief.md", "C:\\work\\c.brief.md"],
        "see ok.brief.md": ["ok.brief.md"],
        "two /a/x.brief.md /a/x.brief.md": ["/a/x.brief.md"],
        "(/a/x.brief.md)": ["/a/x.brief.md"],
        "[see](/a/z.brief.md)": ["/a/z.brief.md"],
        "path '/a/q.brief.md' quoted": ["/a/q.brief.md"],
        "none here": [],
        "/a/x.brief.mdx is not one": [],
        "./rel/y.brief.md, next": ["./rel/y.brief.md"],
    }

    def test_ordinary_prompts(self):
        for prompt, want in self.CASES.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(require_brief.brief_paths(prompt), want)


class EmailsAreStillFound(unittest.TestCase):
    def test_addresses_and_non_addresses(self):
        at = "@"   # assembled at run time: the file holds no address literal
        found = [a for a, _ in leaks.emails_in(f"mail a.b+c{at}corp-domain.dev, or x{at}y.z. and user{at}host and {at}scope/pkg")]
        self.assertEqual(found, [f"a.b+c{at}corp-domain.dev"])
        self.assertEqual([t for _, t in leaks.emails_in(f"q{at}a.b.example.")], ["example"])


if __name__ == "__main__":
    unittest.main()
