"""Reproductions of the Opus review findings on `guard scan --diff` (F-8c, F-15, F-18) and on the matrix (F-1, F-25)."""
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from test_guard_cli import git, run_cli
from test_guard_common import ROOT, write_config

MATRIX = ROOT / "docs" / "reference" / "enforcement-matrix.md"


class ScanBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        git(self.root, "init", "-q")
        (self.root / "README.md").write_text("base\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")

    def base_config(self, **extras):
        """Commit a configuration into the base revision."""
        from test_guard_common import isolated_env
        with isolated_env():
            write_config(self.root, **extras)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "config")

    def commit(self, files):
        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "change")

    def scan(self, *extra):
        return run_cli("guard", "scan", "--diff", "HEAD~1..HEAD", "--root", str(self.root), *extra)


class F15NoSelfExemption(ScanBase):
    LINE = "schtasks /create /tn x /tr y\n"

    def test_no_implicit_exemption_for_tests_or_markdown_without_a_base_config_key(self):
        self.commit({"tests/setup.sh": self.LINE})
        code, out, _ = self.scan()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/setup.sh:1", out)

    def test_the_shipped_default_exempts_markdown_only_and_reports_it(self):
        self.commit({"docs/setup.md": "```\n" + self.LINE + "```\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 2, out)  # WARN, not clean
        self.assertIn("WARN", out)
        self.assertIn("docs/setup.md:2", out)
        self.assertIn("scan_ignore", out)

    def test_a_head_config_cannot_exempt_its_own_change(self):
        from test_guard_common import isolated_env
        (self.root / ".batuta").mkdir()
        with isolated_env():
            doc = __import__("batuta_lib.config", fromlist=["x"]).default_config()
        doc["guards"] = {"scan_ignore": ["**"]}
        self.commit({".batuta/batuta.json": json.dumps(doc), "install.sh": self.LINE})
        code, out, _ = self.scan()
        self.assertEqual(code, 1, out)
        self.assertIn("install.sh:1", out)

    def test_the_base_revision_config_is_honoured_and_every_ignored_hit_is_a_warn(self):
        self.base_config(guards={"scan_ignore": ["legacy/**"]})
        self.commit({"legacy/old.sh": self.LINE + "crontab x\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 2, out)
        self.assertEqual(out.count("WARN"), 2, out)  # one line per ignored hit
        self.assertIn("2 ignored", out)

    def test_the_cli_ignore_option_is_gone(self):
        self.commit({"a.sh": self.LINE})
        with self.assertRaises(SystemExit):
            self.scan("--ignore", "a.sh")

    def test_the_inline_marker_works_only_for_the_rule_id_it_names(self):
        self.commit({"a.sh": "crontab foo  # batuta-guard: ignore linux-autostart\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 2, out)
        self.assertIn("WARN", out)
        self.assertIn("linux-autostart", out)
        self.commit({"b.sh": "crontab foo  # batuta-guard: ignore scheduled-task\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 1, out)
        self.commit({"c.sh": "crontab foo  # batuta-guard: ignore\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 1, out)

    def test_protected_branches_and_disabled_packs_come_from_the_base_revision(self):
        self.commit({".batuta/batuta.json": json.dumps({"guards": {"destructive_disable": ["hard-reset"]}}),
                     "x.sh": "git reset --hard\n"})
        code, out, _ = self.scan()
        self.assertEqual(code, 1, out)


class F8ConfigChangeWarning(ScanBase):
    def test_a_change_to_the_security_keys_is_a_warn(self):
        self.commit({".batuta/batuta.json": json.dumps({"guards": {"require_brief": "off"}, "tdd": {"lock_file": "x.json"}})})
        code, out, _ = self.scan()
        self.assertEqual(code, 2, out)
        self.assertIn("WARN", out)
        self.assertIn(".batuta/batuta.json", out)
        self.assertIn("guards", out)

    def test_other_config_changes_are_not_flagged(self):
        self.commit({".batuta/batuta.json": json.dumps({"caps": {"max_concurrent_agents": 2}})})
        code, out, _ = self.scan()
        self.assertEqual(code, 0, out)


class F18ArgumentInjection(ScanBase):
    def test_a_range_that_starts_with_a_dash_is_refused_and_nothing_is_written(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        target = pathlib.Path(other.name) / "injected.txt"
        code, out, _ = run_cli("guard", "scan", f"--diff=--output={target.as_posix()}", "--root", str(self.root))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertFalse(target.exists())
        code, out, _ = run_cli("guard", "scan", "--diff=-p", "--root", str(self.root))
        self.assertEqual(code, 1)

    def test_a_real_range_still_works(self):
        self.commit({"a.py": "print(1)\n"})
        self.assertEqual(self.scan()[0], 0)


class MatrixCorrections(unittest.TestCase):
    def test_the_matrix_states_the_matcher_u9_must_use(self):  # F-1
        text = MATRIX.read_text(encoding="utf-8")
        self.assertIn("Bash|PowerShell|Monitor", text)

    def test_the_secrets_row_has_no_read_twin_beyond_the_payload_command(self):  # F-25
        row = next(line for line in MATRIX.read_text(encoding="utf-8").splitlines() if "`guard-secrets`" in line)
        self.assertNotIn("leaks scan", row)
        self.assertIn("guard secrets --payload", row)

    def test_the_config_file_protection_is_documented(self):  # F-8
        text = MATRIX.read_text(encoding="utf-8")
        self.assertIn(".batuta/batuta.json", text)
        self.assertIn("ask", text)


if __name__ == "__main__":
    unittest.main()
