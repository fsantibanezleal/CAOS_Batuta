"""A marketplace install copies only `plugins/batuta/`: a copy of that folder alone must run `init project`, `init user`
and `device deploy`, so every template the areas read lives inside the plugin."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import ROOT, make_repo  # noqa: E402


class PluginAlone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name).resolve()
        cls.plugin = cls.tmp / "cache" / "batuta-0.1.0"          # where a marketplace install puts the plugin
        shutil.copytree(ROOT / "plugins" / "batuta", cls.plugin, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def batuta(self, *args, env=None):
        base = {k: v for k, v in os.environ.items() if k not in ("BATUTA_CONFIG", "BATUTA_HOME")}
        done = subprocess.run([sys.executable, "-B", str(self.plugin / "scripts" / "batuta.py"), *args],
                              capture_output=True, text=True, timeout=300, env={**base, **(env or {})})
        return done.returncode, done.stdout + done.stderr

    def test_the_repository_has_no_templates_folder_outside_the_plugin(self):
        self.assertFalse((ROOT / "templates").exists(), "templates live in plugins/batuta/templates")
        for name in ("presets", "user", "knowledge", "project", "spec", "gates"):
            self.assertTrue((self.plugin / "templates" / name).is_dir(), name)
        self.assertTrue((self.plugin / "templates" / "managed-settings.example.json").is_file())

    def test_init_project_runs_from_the_plugin_copy_alone(self):
        project = make_repo(self.tmp / "scratch project")
        code, out = self.batuta("init", "project", "--target", str(project), "--apply",
                                env={"BATUTA_HOME": str(self.tmp / "bh1")})
        self.assertEqual(code, 0, out)
        for rel in ("AGENTS.md", "CLAUDE.md", ".batuta/batuta.json", ".github/workflows/batuta-gates.yml",
                    "specs/001-example-feature/spec.md"):
            self.assertTrue((project / rel).is_file(), rel)

    def test_device_deploy_and_init_user_run_from_the_plugin_copy_alone(self):
        home = self.tmp / "home"
        (home / ".claude").mkdir(parents=True, exist_ok=True)
        deploy = self.tmp / "device copy"
        env = {"BATUTA_HOME": str(self.tmp / "bh2")}
        code, out = self.batuta("device", "deploy", "--deploy-root", str(deploy), "--home", str(home), "--apply", env=env)
        self.assertEqual(code, 0, out)
        for rel in ("templates/presets/base.json", "templates/user/CLAUDE.template.md", "templates/project/AGENTS.md",
                    "templates/managed-settings.example.json", "scripts/batuta.py", "reference"):
            self.assertTrue((deploy / rel).exists(), rel)
        code, out = self.batuta("init", "user", "--home", str(home), "--apply", env=env)
        self.assertIn(code, (0, 2), out)
        self.assertTrue((home / ".claude" / "agents" / "implementer.md").is_file())
        self.assertTrue((home / ".claude" / "CLAUDE.md").is_file())


if __name__ == "__main__":
    unittest.main()
