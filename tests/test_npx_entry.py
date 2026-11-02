"""The npx entry `bin/batuta.mjs`: Python discovery (BATUTA_PYTHON, then `py -3` on Windows, `python3`, `python`; the first
that reports 3.10 or newer wins), the pass-through of arguments and exit code, and the message when no suitable Python
exists. The discovery is driven with a scripted probe so every OS and every missing interpreter can be tested anywhere;
the end-to-end runs use the real interpreter. Skipped, with the reason, where Node 18 or newer is absent."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "bin" / "batuta.mjs"


def node_version():
    node = shutil.which("node")
    if not node:
        return None, "Node is not installed (the npx channel needs Node 18 or newer)"
    done = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30)
    try:
        major = int(done.stdout.strip().lstrip("v").split(".")[0])
    except ValueError:
        return None, f"cannot read the Node version from {done.stdout!r}"
    if major < 18:
        return None, f"Node {done.stdout.strip()} is older than 18"
    return node, ""


NODE, WHY = node_version()


def find_python(env, platform, versions):
    """Run `findPython` of the entry with a scripted probe. `versions` maps 'cmd arg arg' to '3.12' or None (fails to run).
    Returns {"python": [...] or null, "tried": [...], "probed": [...]}."""
    script = f"""
import {{ findPython }} from {json.dumps(ENTRY.as_uri())};
const versions = {json.dumps(versions)};
const probed = [];
const run = (cmd, args) => {{
  const key = [cmd, ...args.filter((a) => a === '-3')].join(' ');
  probed.push([cmd, ...args]);
  const v = versions[key];
  if (v === undefined || v === null) return {{ error: new Error('not found'), status: null, stdout: '' }};
  return {{ status: 0, stdout: v + '\\n' }};
}};
const result = findPython({{ env: {json.dumps(env)}, platform: {json.dumps(platform)}, run }});
console.log(JSON.stringify({{ ...result, probed }}));
"""
    done = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout.strip().splitlines()[-1])


@unittest.skipIf(NODE is None, WHY)
class Discovery(unittest.TestCase):
    def test_batuta_python_wins_when_it_is_3_10_or_newer(self):
        r = find_python({"BATUTA_PYTHON": "my-python"}, "linux", {"my-python": "3.12", "python3": "3.11"})
        self.assertEqual(r["python"], ["my-python"])
        self.assertEqual(r["probed"][0][0], "my-python")

    def test_batuta_python_below_3_10_is_skipped_and_the_next_candidate_is_tried(self):
        r = find_python({"BATUTA_PYTHON": "old-python"}, "linux", {"old-python": "3.9", "python3": "3.11"})
        self.assertEqual(r["python"], ["python3"])

    def test_windows_tries_the_launcher_first(self):
        r = find_python({}, "win32", {"py -3": "3.13", "python3": "3.12", "python": "3.12"})
        self.assertEqual(r["python"], ["py", "-3"])

    def test_windows_with_only_py_installed(self):
        r = find_python({}, "win32", {"py -3": "3.12"})
        self.assertEqual(r["python"], ["py", "-3"])

    def test_posix_with_only_python3(self):
        r = find_python({}, "darwin", {"python3": "3.11"})
        self.assertEqual(r["python"], ["python3"])
        self.assertNotIn(["py", "-3", "-c"], [p[:3] for p in r["probed"]], "py is tried on Windows only")

    def test_posix_with_only_python(self):
        r = find_python({}, "linux", {"python": "3.10"})
        self.assertEqual(r["python"], ["python"])

    def test_python_3_9_found_first_is_skipped_and_the_next_is_used(self):
        r = find_python({}, "win32", {"py -3": "3.9", "python3": "3.9", "python": "3.12"})
        self.assertEqual(r["python"], ["python"])
        r = find_python({}, "linux", {"python3": "3.9", "python": "3.11"})
        self.assertEqual(r["python"], ["python"])

    def test_python_2_is_never_picked(self):
        r = find_python({}, "linux", {"python3": None, "python": "2.7"})
        self.assertIsNone(r["python"])

    def test_nothing_suitable_returns_every_candidate_tried_in_order(self):
        r = find_python({"BATUTA_PYTHON": "mine"}, "win32", {"mine": "3.8", "py -3": "3.9"})
        self.assertIsNone(r["python"])
        self.assertEqual(r["tried"], ["BATUTA_PYTHON=mine (3.8)", "py -3 (3.9)", "python3 (not found)", "python (not found)"])

    def test_minor_versions_compare_numerically(self):
        r = find_python({}, "linux", {"python3": "3.100"})
        self.assertEqual(r["python"], ["python3"])
        r = find_python({}, "linux", {"python3": "3.9"})
        self.assertIsNone(r["python"])

    def test_batuta_python_that_names_an_existing_file_is_one_command_even_with_spaces(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        exe = Path(folder) / "a folder" / "python tool.exe"
        exe.parent.mkdir()
        exe.write_text("x", encoding="utf-8")
        r = find_python({"BATUTA_PYTHON": str(exe)}, "linux", {str(exe): "3.12"})
        self.assertEqual(r["python"], [str(exe)])

    def test_batuta_python_may_carry_arguments_when_it_is_not_a_file(self):
        r = find_python({"BATUTA_PYTHON": "py -3"}, "win32", {"py -3": "3.12"})
        self.assertEqual(r["python"], ["py", "-3"])


@unittest.skipIf(NODE is None, WHY)
class EndToEnd(unittest.TestCase):
    def env(self, **extra):
        base = {k: v for k, v in os.environ.items() if k != "BATUTA_PYTHON"}
        return {**base, "BATUTA_HOME": str(Path(tempfile.gettempdir()) / "batuta-npx-test-no-home"), **extra}

    def node(self, *args, env=None):
        return subprocess.run([NODE, str(ENTRY), *args], capture_output=True, text=True, timeout=120, env=env)

    def python_direct(self, *args):
        script = ROOT / "plugins" / "batuta" / "scripts" / "batuta.py"
        return subprocess.run([sys.executable, "-B", str(script), *args], capture_output=True, text=True, timeout=120)

    def test_version_show_runs_through_the_entry_with_batuta_python(self):
        done = self.node("version", "show", env=self.env(BATUTA_PYTHON=sys.executable))
        self.assertEqual(done.returncode, 0, done.stderr)
        expected = self.python_direct("version", "show")
        self.assertEqual(done.stdout, expected.stdout)

    def test_version_show_runs_through_real_discovery(self):
        done = self.node("version", "show", env=self.env())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stdout, r"\d+\.\d+\.\d+")

    def test_the_exit_code_and_arguments_pass_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ("spec", "trace", "999-none", "--root", tmp)
            ours = self.node(*args, env=self.env(BATUTA_PYTHON=sys.executable))
            direct = self.python_direct(*args)
            self.assertNotEqual(direct.returncode, 0)
            self.assertEqual(ours.returncode, direct.returncode)
            self.assertEqual(ours.stdout, direct.stdout)

    def test_arguments_with_spaces_arrive_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "a folder with spaces"
            folder.mkdir()
            done = self.node("reserve", "next", "api", "mig", "--root", str(folder), env=self.env(BATUTA_PYTHON=sys.executable))
            self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
            self.assertIn("api:mig = 1", done.stdout)

    def test_no_suitable_python_exits_1_naming_what_was_tried_and_how_to_set_it(self):
        with tempfile.TemporaryDirectory() as empty:
            env = {"PATH": empty, "SystemRoot": os.environ.get("SystemRoot", ""), "BATUTA_PYTHON": str(Path(empty) / "nope")}
            done = self.node("version", "show", env=env)
        self.assertEqual(done.returncode, 1)
        self.assertIn("Python 3.10", done.stderr)
        self.assertIn("BATUTA_PYTHON", done.stderr)
        for tried in ("python3", "python"):
            self.assertIn(tried, done.stderr)
        self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
