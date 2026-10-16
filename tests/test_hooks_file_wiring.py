"""hooks.json wires every handler through the launcher exactly as C31 and decision 19 state."""
import json
import re
import subprocess
import sys
import unittest

from _support import ROOT, SCRIPTS, load_batuta

PLUGIN = ROOT / "plugins" / "batuta"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
MATRIX = ROOT / "docs" / "reference" / "enforcement-matrix.md"
BATUTA = SCRIPTS / "batuta.py"

SHELL = set("Bash|PowerShell|Monitor".split("|"))
FILES = set("Edit|Write|MultiEdit|NotebookEdit".split("|"))
# (event, handler id) -> tools its matcher must cover (None: the event takes no matcher)
REQUIRED = {
    ("SessionStart", "session-check"): {"startup", "resume"},
    ("PreToolUse", "guard-automation"): SHELL | FILES,
    ("PreToolUse", "guard-destructive"): SHELL,
    ("PreToolUse", "guard-locked-tests"): SHELL | FILES,
    ("PreToolUse", "guard-approvals"): SHELL | FILES,
    ("PreToolUse", "guard-secrets"): {"Read", "Grep", "Glob", "NotebookRead"} | SHELL,
    ("PreToolUse", "guard-require-brief"): {"Agent", "Task"},
    ("SubagentStop", "subagent-stop"): None,
    ("UserPromptSubmit", "spec-approval"): None,
    ("UserPromptSubmit", "tdd-change-request"): None,
    ("Stop", "gate-stop"): None,
}
COMMAND = re.compile(r'^"\$CLAUDE_PLUGIN_OPTION_PYTHON" -I "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hook\.py" ([a-z][a-z-]*)$')


def entries():
    """(event, matcher or None, entry, handler id) for every hooks.json entry."""
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    for event, groups in data["hooks"].items():
        for group in groups:
            for entry in group["hooks"]:
                m = COMMAND.match(entry.get("command", ""))
                yield event, group.get("matcher"), entry, (m.group(1) if m else None)


def fail_closed_ids_from_matrix():
    ids = set()
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"`guard-[a-z-]+`", cells[1]) and cells[-1] == "block":
            ids.add(cells[1].strip("`"))
    return ids


class HooksFileTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(HOOKS_JSON.is_file(), f"{HOOKS_JSON} is missing")
        self.found = list(entries())

    def test_satisfies_c31(self):
        load_batuta()
        from batuta_lib import contract as core
        schema = core.find_schema(PLUGIN / "contracts", "C31")
        self.assertEqual(core.validate_file(HOOKS_JSON, schema, "C31"), [])

    def test_every_entry_is_the_decision_19_shell_form(self):
        for event, matcher, entry, hid in self.found:
            self.assertIsNotNone(hid, f"{event}: {entry.get('command')}")
            self.assertEqual(entry["type"], "command")
            self.assertEqual(entry.get("shell"), "bash")
            self.assertNotIn("args", entry)

    def test_no_machine_path_or_hard_coded_interpreter(self):
        text = HOOKS_JSON.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]|/home/|/Users/|/usr/|python\.exe", text))
        for _, _, entry, _ in self.found:
            self.assertTrue(entry["command"].startswith('"$CLAUDE_PLUGIN_OPTION_PYTHON" '))

    def test_exactly_the_expected_handlers_are_wired(self):
        wired = {}
        for event, matcher, entry, hid in self.found:
            self.assertNotIn((event, hid), wired, f"{hid} wired twice on {event}")
            wired[(event, hid)] = matcher
        self.assertEqual(set(wired), set(REQUIRED))

    def test_matchers_cover_what_each_handler_inspects(self):
        for event, matcher, entry, hid in self.found:
            need = REQUIRED[(event, hid)]
            if need is None:
                self.assertIsNone(matcher, f"{hid}: {event} takes no matcher")
                continue
            self.assertIsNotNone(matcher, hid)
            have = set(matcher.split("|"))
            self.assertLessEqual(need, have, f"{hid}: matcher {matcher} misses {sorted(need - have)}")

    def test_session_start_matcher_is_startup_or_resume(self):
        for event, matcher, _, hid in self.found:
            if hid == "session-check":
                self.assertEqual(matcher, "startup|resume")

    def test_on_failure_block_exactly_on_the_fail_closed_guards(self):
        expected = fail_closed_ids_from_matrix()
        self.assertEqual(expected, {"guard-automation", "guard-locked-tests", "guard-approvals", "guard-secrets",
                                    "guard-destructive"})
        blocking = set()
        for event, matcher, entry, hid in self.found:
            if entry.get("onFailure") == "block":
                blocking.add(hid)
                self.assertEqual(event, "PreToolUse", hid)
                self.assertFalse(entry.get("async") or entry.get("asyncRewake"), hid)
        self.assertEqual(blocking, expected)

    def test_no_on_failure_on_session_start_subagent_stop_or_stop(self):
        for event, _, entry, hid in self.found:
            if event in ("SessionStart", "SubagentStop", "Stop"):
                self.assertNotIn("onFailure", entry, hid)

    def test_status_messages_are_short(self):
        for _, _, entry, hid in self.found:
            message = entry.get("statusMessage", "")
            self.assertTrue(message.strip(), f"{hid} has no statusMessage")
            self.assertLessEqual(len(message), 60, hid)

    def test_timeouts_are_bounded(self):
        for _, _, entry, hid in self.found:
            self.assertIn("timeout", entry, hid)
            self.assertLessEqual(entry["timeout"], 60, hid)

    def test_contract_lint_resolves_every_id(self):
        result = subprocess.run([sys.executable, "-B", str(BATUTA), "contract", "lint"], capture_output=True, text=True,
                                timeout=300, cwd=str(ROOT))
        out = result.stdout
        self.assertEqual(result.returncode, 0, out + result.stderr)
        self.assertIn("hooks/hooks.json satisfies C31; its 11 entr(ies) resolve to a handler each", out)


if __name__ == "__main__":
    unittest.main()
