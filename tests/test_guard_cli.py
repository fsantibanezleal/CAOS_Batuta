"""The `guard` area on the command line: one guard on a payload file, --explain, `guard scan --diff`, the real
launcher on the real guards from a copy of the plugin folder alone, and the enforcement matrix."""
import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from test_guard_common import ROOT, isolated_env, pre, bash, write_json

from batuta_lib.areas import guard

PLUGIN = ROOT / "plugins" / "batuta"
GUARD_IDS = ["guard-automation", "guard-locked-tests", "guard-approvals", "guard-secrets", "guard-destructive",
             "guard-require-brief"]


def run_cli(*argv):
    sys.path.insert(0, str(PLUGIN / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("batuta_cli_guard", PLUGIN / "scripts" / "batuta.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class AreaLayout(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(guard.AREA, "guard")
        self.assertTrue(guard.HELP)
        self.assertTrue(callable(guard.register))

    def test_hooks_is_a_literal_dict_with_the_six_ids(self):
        from batuta_lib import contract
        found, problems = contract.discover_hook_ids(PLUGIN / "scripts" / "batuta_lib" / "areas")
        self.assertEqual(problems, [])
        for hid in GUARD_IDS:
            self.assertEqual(found.get(hid), ["guard"], hid)

    def test_the_verbs_are_the_guards_and_scan(self):
        import argparse
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers(dest="verb")
        guard.register(subs)
        self.assertEqual(set(subs.choices), {"automation", "locked-tests", "approvals", "secrets", "destructive",
                                             "require-brief", "scan"})


class GuardVerb(unittest.TestCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)

    def payload(self, doc):
        return str(write_json(self.dir / "payload.json", doc))

    def test_deny_prints_refused_and_exits_one(self):
        code, out, _ = run_cli("guard", "automation", "--payload", self.payload(bash("schtasks /create /tn x")))
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", out)
        self.assertIn("scheduled task", out)

    def test_allow_prints_ok_and_exits_zero(self):
        code, out, _ = run_cli("guard", "automation", "--payload", self.payload(bash("ls")))
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_ask_prints_warn_and_exits_two(self):
        doc = pre("Bash", self.dir, command="python batuta.py spec approve 001-x --apply")
        code, out, _ = run_cli("guard", "approvals", "--payload", self.payload(doc))
        self.assertEqual(code, 2)
        self.assertIn("WARN", out)

    def test_json_output_is_the_c20_object(self):
        code, out, _ = run_cli("guard", "automation", "--json", "--payload", self.payload(bash("crontab x")))
        doc = json.loads(out)
        self.assertEqual(doc["area"], "guard")
        self.assertEqual(doc["exit_code"], 1)
        from batuta_lib import contract
        schema = contract.load_schema(contract.find_schema(PLUGIN / "contracts", "C20"))
        self.assertEqual(contract.validate_instance("C20", doc, schema), [])

    def test_a_missing_payload_file_fails(self):
        code, out, _ = run_cli("guard", "automation", "--payload", str(self.dir / "nope.json"))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_a_malformed_payload_file_fails(self):
        path = self.dir / "bad.json"
        path.write_text("{no", encoding="utf-8")
        code, out, _ = run_cli("guard", "automation", "--payload", str(path))
        self.assertEqual(code, 1)

    def test_explain_lists_the_rules_and_the_missing_data_state(self):
        for name in ("automation", "locked-tests", "approvals", "secrets", "destructive", "require-brief"):
            with self.subTest(name=name):
                code, out, _ = run_cli("guard", name, "--explain")
                self.assertEqual(code, 0)
                self.assertGreater(len(out.splitlines()), 2)
        code, out, _ = run_cli("guard", "locked-tests", "--explain")
        self.assertIn("no lock file", out.lower())

    def test_a_malformed_lock_fails_the_cli(self):
        (self.dir / ".git").mkdir()
        (self.dir / ".batuta").mkdir()
        (self.dir / ".batuta" / "test-locks.json").write_text("{no", encoding="utf-8")
        doc = pre("Write", self.dir, file_path="tests/test_a.py", content="x")
        code, out, _ = run_cli("guard", "locked-tests", "--payload", self.payload(doc))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)


def git(root, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env, check=True).stdout


class ScanDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        git(self.root, "init", "-q")
        (self.root / "README.md").write_text("base\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")

    def commit(self, files):
        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "change")

    def scan(self, *extra):
        return run_cli("guard", "scan", "--diff", "HEAD~1..HEAD", "--root", str(self.root), *extra)

    def test_a_scheduled_task_in_an_added_script_line_is_reported_with_file_and_line(self):
        self.commit({"deploy.sh": "echo start\nschtasks /create /tn x /tr y\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("deploy.sh:2", out)
        self.assertIn("scheduled task", out)

    def test_a_destructive_command_in_a_workflow_is_reported(self):
        self.commit({"ci.yml": "steps:\n  - run: git push --force origin main\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("ci.yml:2", out)
        self.assertIn("protected", out)

    def test_a_clean_diff_exits_zero(self):
        self.commit({"app.py": "print('hello')\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_removed_lines_are_not_scanned(self):
        self.commit({"deploy.sh": "schtasks /create /tn x\n"})
        self.commit({"deploy.sh": "echo gone\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 0, out)

    def test_only_markdown_is_exempt_by_default_and_it_is_reported(self):
        self.commit({"docs/a.md": "schtasks /create /tn x\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 2, out)
        self.assertIn("WARN", out)

    def test_tests_and_guard_tables_are_scanned_like_any_file(self):
        self.commit({"tests/test_a.py": "x = 'crontab foo'\n", "plugins/batuta/scripts/batuta_lib/guards/t.py": "x = 'nohup y'\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/test_a.py:1", out)

    def test_the_inline_marker_names_the_rule_it_excuses(self):
        self.commit({"a.sh": "crontab foo  # batuta-guard: ignore linux-autostart\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 2, out)

    def test_an_unbounded_loop_across_added_lines_is_reported(self):
        self.commit({"loop.sh": "while true; do\n  sleep 5\ndone\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("polling loop", out)

    def test_a_bad_range_fails(self):
        code, out, _ = run_cli("guard", "scan", "--diff", "nope..nada", "--root", str(self.root))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)


class RealLauncher(unittest.TestCase):
    """The production path: hook.py on the real guards, from a copy of the plugin folder alone."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.plugin = pathlib.Path(cls.tmp.name) / "batuta"
        shutil.copytree(PLUGIN, cls.plugin, ignore=shutil.ignore_patterns("__pycache__"))
        cls.home = pathlib.Path(cls.tmp.name) / "home"
        cls.home.mkdir()
        cls.work = pathlib.Path(cls.tmp.name) / "work"
        (cls.work / ".git").mkdir(parents=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def hook(self, hid, payload):
        env = {k: v for k, v in os.environ.items() if k not in ("BATUTA_CONFIG", "CLAUDE_PROJECT_DIR")}
        env["BATUTA_HOME"] = str(self.home)
        start = time.perf_counter()
        proc = subprocess.run([sys.executable, str(self.plugin / "scripts" / "hook.py"), hid],
                              input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                              env=env, cwd=str(self.work), timeout=120)
        return proc, time.perf_counter() - start

    CASES = {
        "guard-automation": (bash("schtasks /create /tn x"), bash("ls")),
        "guard-locked-tests": (None, pre("Write", file_path="tests/test_a.py", content="x")),
        "guard-approvals": (pre("Write", file_path="specs/001-x/approvals/a.json", content="x"), bash("ls")),
        "guard-secrets": (pre("Read", file_path=".env"), pre("Read", file_path="README.md")),
        "guard-destructive": (bash("git reset --hard"), bash("git status")),
        "guard-require-brief": (pre("Agent", subagent_type="implementer", prompt="do it"), pre("Bash", command="ls")),
    }

    def test_block_and_allow_cases_on_the_real_path(self):
        for hid, (block, allow) in self.CASES.items():
            with self.subTest(hid=hid):
                if block is not None:
                    proc, _ = self.hook(hid, block)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    out = json.loads(proc.stdout)
                    self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
                proc, _ = self.hook(hid, allow)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout.strip(), "")

    def test_a_locked_test_is_denied_through_the_launcher(self):
        write_json(self.work / ".batuta" / "test-locks.json", {"contract_version": "1.0", "entries": [
            {"path": "tests/test_a.py", "sha256": "b" * 64, "task_id": "T-001", "req_ids": ["REQ-A-001"],
             "locked_commit": "abc", "locked_at": "2026-10-13T10:00:00Z"}]})
        try:
            proc, _ = self.hook("guard-locked-tests", pre("Write", file_path="tests/test_a.py", content="x"))
            self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        finally:
            shutil.rmtree(self.work / ".batuta")

    def test_a_removed_guard_file_fails_open(self):
        copy = pathlib.Path(self.tmp.name) / "batuta-nogd"
        shutil.copytree(self.plugin, copy, ignore=shutil.ignore_patterns("__pycache__"))
        (copy / "scripts" / "batuta_lib" / "areas" / "guard.py").unlink()
        proc = subprocess.run([sys.executable, str(copy / "scripts" / "hook.py"), "guard-automation"],
                              input=json.dumps(bash("schtasks /create /tn x")), capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(proc.returncode, 1)  # non-blocking for Claude Code: the call goes on
        self.assertEqual(proc.stdout.strip(), "")
        self.assertIn("unknown", proc.stderr.lower())

    def test_a_guard_that_crashes_does_not_block(self):
        proc = subprocess.run([sys.executable, str(self.plugin / "scripts" / "hook.py"), "guard-automation"],
                              input="{broken", capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 1)

    def test_no_bytecode_is_written_into_the_copy(self):
        self.hook("guard-automation", bash("ls"))
        self.assertEqual(list(self.plugin.rglob("__pycache__")), [])

    def test_the_automation_guard_answers_in_under_200_ms_in_process(self):
        from batuta_lib.areas import guard as area
        payloads = [bash(c) for c in ("ls -la", "git status", "python -m unittest", "schtasks /create /tn x",
                                      "echo hello && cat README.md")]
        area.HOOKS["guard-automation"](payloads[0])  # warm the module
        start = time.perf_counter()
        for payload in payloads * 4:
            area.HOOKS["guard-automation"](payload)
        per_call = (time.perf_counter() - start) / (len(payloads) * 4)
        self.assertLess(per_call, 0.2)


class Matrix(unittest.TestCase):
    PATH = ROOT / "docs" / "reference" / "enforcement-matrix.md"

    def test_the_matrix_names_every_guard_with_script_ci_and_fail_mode(self):
        text = self.PATH.read_text(encoding="utf-8")
        rows = {}
        for line in text.splitlines():
            cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
            if len(cells) >= 5 and cells[1] in GUARD_IDS:
                rows[cells[1]] = cells
        self.assertEqual(sorted(rows), sorted(GUARD_IDS))
        for hid, cells in rows.items():
            self.assertRegex(cells[-1], r"^(block|continue)$", hid)
            self.assertIn("guard", cells[2], hid)
        for hid in ("guard-locked-tests", "guard-approvals", "guard-automation", "guard-secrets", "guard-destructive"):
            self.assertEqual(rows[hid][-1], "block", hid)

    def test_the_matrix_documents_the_fail_open_launcher_and_the_config_keys(self):
        text = self.PATH.read_text(encoding="utf-8")
        for word in ("onFailure", "fail open", "tdd.lock_file", "guards.secret_globs", "guards.protected_branches",
                     "guards.require_brief", "leaks scan", "GUARD-3"):
            self.assertIn(word, text, word)


if __name__ == "__main__":
    unittest.main()
