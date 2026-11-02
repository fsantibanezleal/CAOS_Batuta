"""Every hooks.json entry runs end to end from a copy of the plugin alone, with a minimal valid C16 payload of its event."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import ROOT, load_batuta

PLUGIN = ROOT / "plugins" / "batuta"
COMMAND = re.compile(r'^"\$CLAUDE_PLUGIN_OPTION_PYTHON" -I "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hook\.py" ([a-z][a-z-]*)$')


def payload_for(event, hid, cwd):
    base = {"session_id": "sess-e2e", "cwd": cwd, "transcript_path": "t.jsonl", "hook_event_name": event}
    if event == "SessionStart":
        return {**base, "source": "startup"}
    if event == "PreToolUse":
        if hid == "guard-require-brief":
            return {**base, "tool_name": "Agent", "tool_input": {"subagent_type": "implementer", "prompt": "do the work"}}
        return {**base, "tool_name": "Bash", "tool_input": {"command": "echo hello"}}
    if event == "SubagentStop":
        return {**base, "agent_type": "implementer", "last_assistant_message": "done", "stop_hook_active": False,
                "agent_transcript_path": "a.jsonl"}
    if event == "UserPromptSubmit":
        return {**base, "prompt": "hello"}
    if event == "Stop":
        return {**base, "stop_hook_active": False}
    raise AssertionError(event)


def entries():
    data = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    for event, groups in data["hooks"].items():
        for group in groups:
            for entry in group["hooks"]:
                yield event, entry


def bash_works(env, root):
    bash = shutil.which("bash")
    if not bash:
        return None
    try:
        out = subprocess.run([bash, "-c", 'echo "$CLAUDE_PLUGIN_ROOT"'], env=env, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return bash if out.returncode == 0 and out.stdout.strip() == root else None


class HooksEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_batuta()
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.plugin = base / "plugin"
        shutil.copytree(PLUGIN, cls.plugin, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        cls.project = base / "project"
        cls.project.mkdir()
        cls.home = base / "home"
        cls.home.mkdir()
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "BATUTA"))}
        cls.env.update({"HOME": str(cls.home), "USERPROFILE": str(cls.home), "BATUTA_HOME": str(cls.home / ".batuta"),
                        "CLAUDE_PLUGIN_ROOT": cls.plugin.as_posix(), "CLAUDE_PLUGIN_OPTION_PYTHON": Path(sys.executable).as_posix(),
                        "PYTHONDONTWRITEBYTECODE": "1"})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check_result(self, label, result):
        self.assertEqual(result.returncode, 0, f"{label}: exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")
        text = result.stdout.strip()
        if text:
            from batuta_lib import contract
            output = json.loads(text)
            schema = contract.load_schema(contract.find_schema(self.plugin / "contracts", "C16"))
            self.assertEqual(contract.validate_instance("C16", output, schema), [], label)

    def test_every_entry_runs_through_the_launcher_alone(self):
        count = 0
        for event, entry in entries():
            m = COMMAND.match(entry["command"])
            self.assertIsNotNone(m, entry["command"])
            hid = m.group(1)
            payload = json.dumps(payload_for(event, hid, str(self.project)))
            argv = [sys.executable, "-B", "-I", str(self.plugin / "scripts" / "hook.py"), hid]
            result = subprocess.run(argv, input=payload, env=self.env, capture_output=True, text=True, timeout=120,
                                    cwd=str(self.project))
            self.check_result(f"{event} {hid}", result)
            count += 1
        self.assertEqual(count, 11)

    def test_every_entry_runs_as_the_exact_shell_command(self):
        bash = bash_works(self.env, self.plugin.as_posix())
        if bash is None:
            self.skipTest("no bash on PATH that sees CLAUDE_PLUGIN_ROOT as the plugin copy")
        for event, entry in entries():
            hid = COMMAND.match(entry["command"]).group(1)
            payload = json.dumps(payload_for(event, hid, str(self.project)))
            result = subprocess.run([bash, "-c", entry["command"]], input=payload, env=self.env, capture_output=True, text=True,
                                    timeout=120, cwd=str(self.project))
            self.check_result(f"{event} {hid} (bash)", result)


if __name__ == "__main__":
    unittest.main()
