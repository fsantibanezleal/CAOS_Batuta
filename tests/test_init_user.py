"""`init user`: the user configuration from a C01 template, the device copy (deploy), the restore (settings merge and user
core), the install manifest, and the whole thing undone by `uninstall`. Always a temporary home and BATUTA_HOME."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import World, snapshot  # noqa: E402

from batuta_lib import config  # noqa: E402
from batuta_lib import install_manifest as im  # noqa: E402


class InitUser(World):
    def test_dry_run_writes_nothing(self):
        code, out, err = self.init_user(apply=False)
        self.assertIn(code, (0, 2), out + err)
        self.assertFalse(self.bh.exists())
        self.assertEqual(snapshot(self.home), {".claude": None})
        self.assertIn("NEW batuta.json", out)
        self.assertIn("dry run", out)

    def test_apply_writes_config_device_copy_settings_user_core_and_manifest(self):
        code, out, err = self.init_user("--var", "user_name=Ada Lovelace")
        self.assertIn(code, (0, 2), out + err)
        cfg_path = self.bh / "batuta.json"
        doc = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(config.validate(doc), [])
        self.assertEqual(doc["user_core"]["template"], "templates/user/CLAUDE.template.md")
        self.assertEqual(doc["user_core"]["values"]["user_name"], "Ada Lovelace")
        self.assertEqual(doc["roots"], {"temp": "$BATUTA_TEMP", "data": "$BATUTA_DATA", "worktrees": "$BATUTA_WORKTREES"})
        self.assertTrue((self.bh / "scripts" / "batuta.py").is_file())
        self.assertTrue((self.bh / "device.json").is_file())
        settings = json.loads((self.home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertIn("Agent(Explore)", settings["permissions"]["deny"])
        core = (self.home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("Ada Lovelace", core)
        manifest = im.Manifest.load(self.bh / "installed.json")
        self.assertEqual(manifest.kind, "user")
        paths = {(e["base"], e["path"]) for e in manifest.files}
        self.assertIn(("deploy", "batuta.json"), paths)
        self.assertIn(("deploy", "scripts/batuta.py"), paths)
        self.assertIn(("deploy", "device.json"), paths)
        self.assertIn(("claude", "settings.json"), paths)
        self.assertIn(("claude", "CLAUDE.md"), paths)
        for role in ("searcher", "runner", "implementer", "test-author", "doc-writer", "adversary", "reviewer"):
            self.assertIn(("claude", f"agents/{role}.md"), paths)
            self.assertTrue((self.home / ".claude" / "agents" / f"{role}.md").is_file(), role)
        for e in manifest.files:
            base = Path(manifest.bases[e["base"]])
            self.assertEqual(manifest.state(base, e["path"]), "SAME", e["path"])

    def test_no_machine_path_is_written_into_the_user_configuration(self):
        self.init_user()
        text = (self.bh / "batuta.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.root), text)
        self.assertNotIn(str(self.home), text)

    def test_an_existing_configuration_is_never_overwritten(self):
        self.bh.mkdir()
        mine = json.dumps(config.default_config(self.env), indent=2) + "\n"
        (self.bh / "batuta.json").write_text(mine, encoding="utf-8")
        code, out, _ = self.init_user()
        self.assertEqual((self.bh / "batuta.json").read_text(encoding="utf-8"), mine)
        self.assertRegex(out, r"SAME batuta\.json|SKIP batuta\.json")

    def test_second_run_changes_nothing(self):
        self.init_user()
        before = snapshot(self.root)
        code, out, err = self.init_user()
        self.assertIn(code, (0, 2), out + err)
        self.assertEqual(snapshot(self.root), before)
        self.assertNotIn("CHANGED", out)

    def test_an_existing_user_core_is_backed_up_and_uninstall_restores_everything(self):
        (self.home / ".claude" / "CLAUDE.md").write_bytes(b"# Mine\r\nkeep\r\n")
        (self.home / ".claude" / "settings.json").write_bytes(b'{\n  "model": "opus"\n}\n')
        before = snapshot(self.root)
        code, out, err = self.init_user()
        self.assertIn(code, (0, 2), out + err)
        self.assertTrue(list((self.home / ".claude").glob("CLAUDE.md.bak-*")))
        self.assertTrue(list((self.home / ".claude").glob("settings.json.bak-*")))
        code, out, err = self.cli("init", "uninstall", "--scope", "user", "--home", str(self.home), "--apply")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(snapshot(self.root), before)

    def test_uninstall_keeps_an_edited_user_core(self):
        self.init_user()
        core = self.home / ".claude" / "CLAUDE.md"
        core.write_text(core.read_text(encoding="utf-8") + "\nmy rule\n", encoding="utf-8")
        code, out, _ = self.cli("init", "uninstall", "--scope", "user", "--home", str(self.home), "--apply")
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"DIFFERENT CLAUDE\.md")
        self.assertIn("my rule", core.read_text(encoding="utf-8"))

    def test_uninstall_is_a_dry_run_by_default(self):
        self.init_user()
        before = snapshot(self.root)
        code, out, _ = self.cli("init", "uninstall", "--scope", "user", "--home", str(self.home))
        self.assertEqual(code, 0, out)
        self.assertEqual(snapshot(self.root), before)

    def test_update_refreshes_the_device_copy_and_backs_up_an_edited_file(self):
        self.init_user()
        script = self.bh / "scripts" / "batuta.py"
        original = script.read_bytes()
        script.write_bytes(original + b"\n# local edit\n")
        code, out, err = self.cli("init", "update", "--scope", "user", "--home", str(self.home), "--apply")
        self.assertIn(code, (0, 2), out + err)
        self.assertEqual(script.read_bytes(), original)
        backups = list(script.parent.glob("batuta.py.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertIn(b"# local edit", backups[0].read_bytes())

    def test_a_deploy_root_inside_a_repository_is_refused(self):
        from test_init_support import make_repo
        repo = make_repo(self.root / "repo")
        code, out, _ = self.cli("init", "user", "--home", str(self.home), "--deploy-root", str(repo / "inside"), "--apply")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL|REFUSED")
        self.assertFalse((repo / "inside").exists())


if __name__ == "__main__":
    unittest.main()
