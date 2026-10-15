"""Shared helpers for the guard tests, plus the tests of the shared text and shell helpers (normalization,
deobfuscation, tokenizing, write and read targets)."""
import base64
import contextlib
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "batuta" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib import contract  # noqa: E402

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"


def pre(tool, cwd=None, **tool_input):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


def bash(command, cwd=None):
    return pre("Bash", cwd, command=command)


def decision_of(result):
    out = result["output"]
    return "allow" if out is None else out["hookSpecificOutput"]["permissionDecision"]


def reason_of(result):
    out = result["output"]
    return "" if out is None else out["hookSpecificOutput"]["permissionDecisionReason"]


@contextlib.contextmanager
def isolated_env(**extra):
    """No real user configuration is read: BATUTA_HOME is a temp folder, the other selectors are removed."""
    with tempfile.TemporaryDirectory() as home:
        env = {k: v for k, v in os.environ.items()
               if k not in ("BATUTA_CONFIG", "CLAUDE_PROJECT_DIR", "BATUTA_HOME")}
        env["BATUTA_HOME"] = home
        env.update(extra)
        with mock.patch.dict(os.environ, env, clear=True):
            yield pathlib.Path(home)


class GuardCase(unittest.TestCase):
    """Base class: every handler result must validate as a C31 handler result (and its output as C16)."""

    def check_valid(self, result):
        schema = contract.load_schema(contract.find_schema(CONTRACTS, "C31"))
        self.assertEqual(contract.validate_instance("C31", result, schema), [])
        return result

    def allows(self, result, msg=None):
        self.check_valid(result)
        self.assertEqual(decision_of(result), "allow", msg or reason_of(result))
        self.assertEqual(result["exit_code"], 0)

    def denies(self, result, contains=None, msg=None):
        self.check_valid(result)
        self.assertEqual(decision_of(result), "deny", msg or "expected a deny")
        self.assertEqual(result["exit_code"], 0)
        if contains:
            self.assertIn(contains.lower(), reason_of(result).lower())

    def asks(self, result, contains=None):
        self.check_valid(result)
        self.assertEqual(decision_of(result), "ask")
        if contains:
            self.assertIn(contains.lower(), reason_of(result).lower())

    def table(self, handler, blocked, allowed, decision="deny", wrap=bash):
        for case in blocked:
            with self.subTest(blocked=case):
                result = handler(wrap(case))
                self.check_valid(result)
                self.assertEqual(decision_of(result), decision, case)
        for case in allowed:
            with self.subTest(allowed=case):
                self.allows(handler(wrap(case)), case)


def write_json(path, doc):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def write_config(root, **extras):
    """A valid batuta.json (the built-in defaults plus the given extra sections) under `root/.batuta`."""
    from batuta_lib import config
    doc = config.default_config()
    doc.update(extras)
    return write_json(pathlib.Path(root) / ".batuta" / "batuta.json", doc)


class TextHelpers(unittest.TestCase):
    def setUp(self):
        from batuta_lib.guards import text
        self.text = text

    def test_nfkc_fullwidth_letters_fold_to_ascii(self):
        self.assertEqual(self.text.normalize("\uff53\uff43\uff48\uff54\uff41\uff53\uff4b\uff53"), "schtasks")

    def test_zero_width_characters_are_removed(self):
        self.assertEqual(self.text.normalize("sch\u200btasks"), "schtasks")

    def test_cyrillic_lookalikes_fold_to_latin(self):
        self.assertEqual(self.text.normalize("cr\u043entab"), "crontab")
        self.assertEqual(self.text.normalize("s\u0441htasks"), "schtasks")

    def test_deobfuscate_strips_backticks_carets_and_empty_quotes(self):
        self.assertEqual(self.text.deobfuscate("Reg`ister-Sched`uledTask"), "Register-ScheduledTask")
        self.assertEqual(self.text.deobfuscate("sch^tasks"), "schtasks")
        self.assertEqual(self.text.deobfuscate('sch""tasks'), "schtasks")
        self.assertEqual(self.text.deobfuscate("sch''tasks"), "schtasks")

    def test_encoded_commands_are_decoded(self):
        raw = base64.b64encode("Register-ScheduledTask -TaskName x".encode("utf-16-le")).decode()
        decoded = self.text.decoded_commands(f"powershell -NoProfile -EncodedCommand {raw}")
        self.assertEqual(decoded, ["Register-ScheduledTask -TaskName x"])
        self.assertEqual(self.text.decoded_commands(f"pwsh -enc {raw}"), decoded)
        self.assertEqual(self.text.decoded_commands("powershell -ec ZZZ"), [None])  # undecodable, reported as None

    def test_plain_commands_have_no_encoded_part(self):
        self.assertEqual(self.text.decoded_commands("ls -la"), [])

    def test_nested_texts_collects_quoted_and_subshell_parts(self):
        parts = self.text.nested_texts("bash -c 'echo hi; crontab x' && echo $(date) `whoami`")
        self.assertIn("echo hi; crontab x", parts)
        self.assertIn("date", parts)
        self.assertIn("whoami", parts)


class ShellHelpers(unittest.TestCase):
    def setUp(self):
        from batuta_lib.guards import shell
        self.sh = shell

    def segs(self, cmd):
        return [s.words for s in self.sh.segments(cmd)]

    def test_segments_split_on_operators_and_newlines(self):
        got = self.segs("a 1 && b 2; c 3 | d 4\ne 5 || f 6")
        self.assertEqual([w[0] for w in got], list("abcdef"))

    def test_quoted_operators_do_not_split(self):
        self.assertEqual(len(self.segs("echo 'a && b; c'")), 1)

    def test_windows_paths_keep_their_backslashes(self):
        words = self.segs('type "C:\\work\\a b\\x.txt" y\\z')[0]
        self.assertEqual(words[1], "C:\\work\\a b\\x.txt")
        self.assertEqual(words[2], "y\\z")

    def test_redirect_targets_are_reported_as_writes(self):
        for cmd in ("echo x > t.py", "echo x >> t.py", "echo x 1>t.py", "echo x 2> t.py", "echo x &> t.py",
                    "echo x >| t.py", "echo x>t.py"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.sh.write_targets(self.sh.segments(cmd)[0]), ["t.py"])

    def test_write_verbs_report_their_targets(self):
        cases = {
            "rm -rf tests/test_a.py": ["tests/test_a.py"],
            "sed -i s/a/b/ tests/test_a.py": ["tests/test_a.py"],
            "tee tests/test_a.py": ["tests/test_a.py"],
            "cp new.py tests/test_a.py": ["tests/test_a.py"],
            "mv tests/test_a.py old.py": ["tests/test_a.py", "old.py"],
            "Set-Content -Path tests/test_a.py -Value x": ["tests/test_a.py"],
            "Remove-Item tests/test_a.py": ["tests/test_a.py"],
            "Copy-Item new.py tests/test_a.py": ["tests/test_a.py"],
            "git checkout -- tests/test_a.py": ["tests/test_a.py"],
        }
        for cmd, want in cases.items():
            with self.subTest(cmd=cmd):
                got = self.sh.write_targets(self.sh.segments(cmd)[0])
                for target in want:
                    self.assertIn(target, got)

    def test_read_only_commands_report_no_write_targets(self):
        for cmd in ("cat tests/test_a.py", "python -m pytest tests/test_a.py", "git diff tests/test_a.py",
                    "grep x tests/test_a.py", "cp tests/test_a.py /tmp/copy.py"):
            with self.subTest(cmd=cmd):
                got = self.sh.write_targets(self.sh.segments(cmd)[0])
                self.assertNotIn("tests/test_a.py", got)

    def test_nested_shell_commands_are_flattened(self):
        flat = [s.words for s in self.sh.all_segments("bash -c 'echo x > tests/test_a.py'")]
        self.assertTrue(any(w[0] == "echo" for w in flat))
        flat = [s.words for s in self.sh.all_segments('pwsh -Command "Set-Content tests/a.py x"')]
        self.assertTrue(any(w[0] == "Set-Content" for w in flat))

    def test_command_name_skips_wrappers_and_extensions(self):
        seg = self.sh.segments("FOO=1 sudo env BAR=2 /usr/bin/Rm.exe -f x")[0]
        self.assertEqual(self.sh.command_name(seg), "rm")

    def test_read_targets_of_a_reader(self):
        seg = self.sh.segments("cat .env")[0]
        self.assertIn(".env", self.sh.read_targets(seg))
        seg = self.sh.segments("Get-Content -Path .env")[0]
        self.assertIn(".env", self.sh.read_targets(seg))


if __name__ == "__main__":
    unittest.main()
