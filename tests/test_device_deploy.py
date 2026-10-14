"""device deploy: the device copy and its C15 profile; dry run by default; refusals."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_device_support import DeviceCase, ROOT, make_file_link, make_link, tree_digest  # noqa: E402

from batuta_lib import config, contract, device_profile  # noqa: E402
from batuta_lib.areas import device  # noqa: E402


class Deploy(DeviceCase):
    def test_dry_run_writes_nothing(self):
        code, out, _ = self.deploy(apply=False)
        self.assertEqual(0, code)
        self.assertIn("NEW", out)
        self.assertIn("dry run", out)
        self.assertFalse(self.deploy_dir.exists())

    def test_apply_copies_scripts_contracts_templates_and_writes_c15(self):
        code, out, _ = self.deploy()
        self.assertEqual(0, code, out)
        d = self.deploy_dir
        for rel in ("scripts/batuta.py", "scripts/batuta_lib/config.py", "scripts/batuta_lib/areas/device.py",
                    "contracts/C01-batuta-config.schema.json", "templates/presets/base.json",
                    "templates/presets/session-check.json", "templates/user/CLAUDE.template.md",
                    "reference/deep-work.md", ".claude-plugin/plugin.json", "device.json"):
            self.assertTrue((d / rel).is_file(), rel)
        self.assertFalse(list(d.rglob("__pycache__")))
        self.assertFalse((d / "contracts" / "fixtures").exists())   # test data, never read at run time
        profile = device_profile.read_profile(d)
        self.assertEqual(d.as_posix(), profile["deploy_root"])
        self.assertEqual((self.bh / "temp").as_posix(), profile["temp_root"])
        self.assertEqual((self.bh / "models").as_posix(), profile["models_root"])
        self.assertRegex(profile["batuta_version"], r"^\d+\.\d{2}\.\d{3}$")
        self.assertEqual(Path(sys.executable).as_posix(), profile["python"])

    def test_python_flag_is_recorded(self):
        self.deploy("--python", str(self.root / "py" / "python"))
        self.assertEqual((self.root / "py" / "python").as_posix(), device_profile.read_profile(self.deploy_dir)["python"])

    def test_second_apply_changes_nothing(self):
        self.deploy()
        before = tree_digest(self.deploy_dir)
        code, out, _ = self.deploy()
        self.assertEqual(0, code)
        self.assertNotIn("NEW", out)
        self.assertNotIn("CHANGED", out)
        self.assertEqual(before, tree_digest(self.deploy_dir))

    def test_stale_file_in_a_mirrored_area_is_removed(self):
        self.deploy()
        stale = self.deploy_dir / "scripts" / "stale.py"
        stale.write_text("x = 1\n", encoding="utf-8")
        code, out, _ = self.deploy()
        self.assertIn("REMOVED", out)
        self.assertFalse(stale.exists())

    def test_the_deployed_copy_runs_by_itself(self):
        self.deploy()
        proc = subprocess.run([sys.executable, str(self.deploy_dir / "scripts" / "batuta.py"), "--version"],
                              capture_output=True, text=True, env={**os.environ, **self.env})
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("batuta", proc.stdout)

    def test_deploy_root_inside_a_repository_is_refused(self):
        repo = self.root / "repo"
        (repo / ".git").mkdir(parents=True)
        code, out, _ = self.cli("device", "deploy", "--deploy-root", str(repo / "copy"), "--home", str(self.home), "--apply")
        self.assertEqual(1, code)
        self.assertIn("repository", out)
        self.assertFalse((repo / "copy").exists())

    def test_relative_deploy_root_is_refused(self):
        code, out, _ = self.cli("device", "deploy", "--deploy-root", "rel/dir", "--home", str(self.home))
        self.assertEqual(1, code)
        self.assertIn("absolute", out)

    def test_deploy_root_on_a_missing_drive_is_a_configuration_error(self):
        with mock.patch.object(device, "_drive_exists", lambda p: False):
            code, out, _ = self.deploy(apply=False)
        self.assertEqual(1, code)
        self.assertIn("not available", out)

    def test_foreign_folder_with_scripts_and_no_profile_is_refused(self):
        (self.deploy_dir / "scripts").mkdir(parents=True)
        (self.deploy_dir / "scripts" / "mine.py").write_text("# mine\n", encoding="utf-8")
        code, out, _ = self.deploy()
        self.assertEqual(1, code)
        self.assertIn("device.json", out)
        self.assertTrue((self.deploy_dir / "scripts" / "mine.py").exists())

    def test_batuta_json_next_to_the_copy_is_left_alone(self):
        self.deploy_dir.mkdir(parents=True)
        (self.deploy_dir / "batuta.json").write_text("{}", encoding="utf-8")
        code, out, _ = self.deploy()
        self.assertEqual(0, code, out)
        self.assertEqual("{}", (self.deploy_dir / "batuta.json").read_text(encoding="utf-8"))

    def test_roots_come_from_the_configuration_file(self):
        cfg = config.default_config({"BATUTA_HOME": str(self.bh)})
        cfg["roots"] = {"temp": str(self.root / "t"), "data": str(self.root / "d"), "worktrees": str(self.root / "w"),
                        "models": str(self.root / "m")}
        path = self.root / "batuta.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        code, out, _ = self.cli("--config", str(path), "device", "deploy", "--deploy-root", str(self.deploy_dir),
                                "--home", str(self.home), "--apply")
        self.assertEqual(0, code, out)
        profile = device_profile.read_profile(self.deploy_dir)
        self.assertEqual((self.root / "m").as_posix(), profile["models_root"])
        self.assertEqual((self.root / "w").as_posix(), profile["worktrees_root"])

    def test_json_output_is_c20(self):
        code, out, _ = self.deploy("--json", apply=False)
        sp = contract.find_schema(config.contracts_dir(), "C20")
        doc = json.loads(out)
        self.assertEqual([], contract.validate_instance("C20", doc, contract.load_schema(sp)))
        self.assertEqual("device", doc["area"])

    def test_no_machine_path_in_the_shipped_device_code(self):
        for rel in ("areas/device.py", "areas/preflight.py", "settings_merge.py", "device_profile.py"):
            text = (ROOT / "plugins" / "batuta" / "scripts" / "batuta_lib" / rel).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])")


class TemplateFolders(unittest.TestCase):
    """A deploy mirrors the repository's templates and the plugin's own together (an area adding plugin templates
    must never drop the presets or the user core), and never a folder above a device copy."""

    def layout(self, base, *folders):
        for rel in folders:
            (base / rel).mkdir(parents=True)
            (base / rel / "x.md").write_text(rel, encoding="utf-8")

    def test_a_checkout_mirrors_the_repository_templates_and_the_plugin_templates(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.layout(base, "templates/presets", "plugins/batuta/templates/spec")
            (base / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
            with mock.patch.object(device, "PLUGIN_ROOT", base / "plugins" / "batuta"):
                self.assertEqual([base / "templates", base / "plugins" / "batuta" / "templates"],
                                 device._templates_dirs())

    def test_a_checkout_without_plugin_templates_still_mirrors_the_repository_templates(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.layout(base, "templates/presets")
            (base / "plugins" / "batuta").mkdir(parents=True)
            (base / ".git").mkdir()
            with mock.patch.object(device, "PLUGIN_ROOT", base / "plugins" / "batuta"):
                self.assertEqual([base / "templates"], device._templates_dirs())

    def test_a_plugins_folder_outside_a_repository_is_not_a_checkout(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.layout(base, "templates/unrelated", "plugins/batuta/templates/spec")
            with mock.patch.object(device, "PLUGIN_ROOT", base / "plugins" / "batuta"):
                self.assertEqual([base / "plugins" / "batuta" / "templates"], device._templates_dirs())

    def test_a_device_copy_never_reads_a_templates_folder_above_it(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.layout(base, "templates/unrelated", "home/copy/templates/presets")
            with mock.patch.object(device, "PLUGIN_ROOT", base / "home" / "copy"):
                self.assertEqual([base / "home" / "copy" / "templates"], device._templates_dirs())


class DeployLinks(DeviceCase):
    """Re-check of F2 for deploy mirroring: a link nested in a mirrored area is never followed or deleted through."""

    def setUp(self):
        super().setUp()
        self.assertEqual(0, self.deploy()[0])
        self.victim = self.root / "victim"
        (self.victim / "precious").mkdir(parents=True)
        (self.victim / "precious" / "thesis.md").write_text("irreplaceable\n", encoding="utf-8")
        self.before = tree_digest(self.victim)

    def refused(self):
        code, out, _ = self.deploy()
        self.assertEqual(1, code, out)
        self.assertIn("REFUSED", out)
        self.assertNotIn("REMOVED", out)
        self.assertEqual(self.before, tree_digest(self.victim))

    def test_a_junction_directly_below_an_area_root(self):
        make_link(self.deploy_dir / "scripts" / "old", self.victim)
        self.refused()

    def test_a_junction_two_levels_down(self):
        make_link(self.deploy_dir / "scripts" / "batuta_lib" / "old", self.victim)
        self.refused()

    def test_a_symlink_file_where_a_managed_file_belongs(self):
        outside = self.root / "outside.md"
        outside.write_text("keep\n", encoding="utf-8")
        target = self.deploy_dir / "templates" / "presets" / "base.json"
        target.unlink()
        make_file_link(target, outside)
        self.refused()
        self.assertEqual("keep\n", outside.read_text(encoding="utf-8"))

    def test_a_file_link_is_refused_even_where_the_account_cannot_create_symlinks(self):
        (self.deploy_dir / "templates" / "ghost.md").write_text("stale\n", encoding="utf-8")
        with mock.patch.object(device, "_is_link", lambda p: Path(p).name == "ghost.md"):
            code, out, _ = self.deploy()
        self.assertEqual(1, code, out)
        self.assertIn("ghost.md", out)
        self.assertNotIn("REMOVED", out)
        self.assertTrue((self.deploy_dir / "templates" / "ghost.md").exists())

    def test_a_stale_symlink_file_in_an_area(self):
        outside = self.root / "outside.md"
        outside.write_text("keep\n", encoding="utf-8")
        make_file_link(self.deploy_dir / "templates" / "ghost.md", outside)
        self.refused()
        self.assertEqual("keep\n", outside.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
