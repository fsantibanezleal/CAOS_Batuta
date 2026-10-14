"""Device profile (C15): root resolution and validation after $VAR expansion, the written profile, the presets."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
from batuta_lib import config, contract, device_profile as dp, settings_merge  # noqa: E402

PRESETS = ROOT / "templates" / "presets"
C31 = contract.load_schema(contract.find_schema(config.contracts_dir(), "C31"))


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()


class ContractTests(Case):
    """Contract conformance first."""

    def test_shipped_presets_are_c17(self):
        for name in ("base.json", "session-check.json"):
            settings_merge.load_preset(PRESETS / name)  # raises on a C17 violation

    def test_session_check_template_is_json_shaped_as_a_c31_entry(self):
        preset = settings_merge.load_preset(PRESETS / "session-check.json")
        group = preset["hooks"]["SessionStart"][0]
        self.assertEqual([], contract.validate_def(group, C31, "group"))

    def test_presets_hold_no_machine_path(self):
        for p in PRESETS.glob("*.json"):
            text = p.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"[A-Za-z]:[\\/]")
            self.assertNotIn("/home/", text)
            self.assertNotIn("/Users/", text)

    def test_written_profile_is_c15(self):
        roots = {k: str(self.root / k) for k in ("temp_root", "data_root", "models_root", "worktrees_root")}
        doc = dp.build_profile(self.root / "dev", roots, sys.executable, "0.01.000")
        self.assertEqual([], dp.validate_profile(doc))
        dp.write_profile(self.root / "dev", doc)
        self.assertEqual(doc, dp.read_profile(self.root / "dev"))

    def test_profile_without_batuta_version_is_refused(self):
        (self.root / "dev").mkdir()
        (self.root / "dev" / "device.json").write_text(json.dumps({"contract_version": "1.0"}), encoding="utf-8")
        with self.assertRaises(dp.ProfileError):
            dp.read_profile(self.root / "dev")


class ResolutionTests(Case):
    def test_flag_wins_over_batuta_home(self):
        env = {"BATUTA_HOME": str(self.root / "env")}
        self.assertEqual(self.root / "flag", dp.deploy_root(str(self.root / "flag"), env))

    def test_batuta_home_then_default(self):
        self.assertEqual(self.root / "env", dp.deploy_root(None, {"BATUTA_HOME": str(self.root / "env")}))
        self.assertEqual(Path.home() / ".batuta", dp.deploy_root(None, {}))

    def test_flag_with_unset_variable_is_an_error(self):
        with self.assertRaises(dp.ProfileError) as cm:
            dp.deploy_root("$NO_SUCH_VAR_U7/x", {})
        self.assertIn("NO_SUCH_VAR_U7", str(cm.exception))

    def test_roots_from_config_and_models_fallback(self):
        cfg = config.default_config({"BATUTA_HOME": str(self.root / "bh")})
        roots = dp.resolve_roots(cfg, {"BATUTA_HOME": str(self.root / "bh")}, home=self.home)
        self.assertEqual(Path(roots["temp_root"]), self.root / "bh" / "temp")
        self.assertEqual(Path(roots["models_root"]), self.root / "bh" / "models")

    def test_roots_follow_c01_roots_with_variables(self):
        env = {"BATUTA_HOME": str(self.root / "bh"), "U7_TEMP": str(self.root / "t")}
        cfg = config.default_config(env)
        cfg["roots"]["temp"] = "$U7_TEMP/scratch"
        # config.load expands the variables and falls back for an unset root variable; resolve_roots sees the result
        cfg_file = self.root / "batuta.json"
        cfg["roots"]["data"] = "$U7_UNSET_ROOT/data"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        loaded = config.load(str(cfg_file), env=env).config
        roots = dp.resolve_roots(loaded, env, home=self.home)
        self.assertEqual(Path(roots["temp_root"]), self.root / "t" / "scratch")
        self.assertEqual(Path(roots["data_root"]), self.root / "bh" / "data")

    def test_relative_root_is_refused(self):
        with self.assertRaises(dp.ProfileError) as cm:
            dp.validate_root("relative/dir", "root 'temp'", self.home)
        self.assertIn("absolute", str(cm.exception))

    def test_drive_root_is_refused(self):
        with self.assertRaises(dp.ProfileError):
            dp.validate_root(Path(self.root.anchor), "root 'data'", self.home)

    def test_root_inside_a_repository_is_refused(self):
        repo = self.root / "repo"
        (repo / ".git").mkdir(parents=True)
        with self.assertRaises(dp.ProfileError) as cm:
            dp.validate_root(repo / "state", "root 'temp'", self.home)
        self.assertIn("repository", str(cm.exception))

    def test_root_inside_a_worktree_with_git_file_is_refused(self):
        wt = self.root / "wt"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        with self.assertRaises(dp.ProfileError):
            dp.validate_root(wt / "x", "root 'temp'", self.home)

    def test_home_and_claude_folder_are_refused(self):
        for bad in (self.home, self.home / ".claude" / "x"):
            with self.assertRaises(dp.ProfileError):
                dp.validate_root(bad, "deploy root", self.home)

    def test_missing_drive_is_a_configuration_error_with_a_clear_message(self):
        with self.assertRaises(dp.ProfileError) as cm:
            dp.validate_root(self.root / "x", "deploy root", self.home, exists=lambda p: False)
        self.assertIn("not available", str(cm.exception))
        self.assertIn("deploy root", str(cm.exception))

    def test_path_with_spaces_is_accepted(self):
        got = dp.validate_root(self.root / "a folder" / "with spaces", "root 'temp'", self.home)
        self.assertEqual(self.root / "a folder" / "with spaces", got)

    def test_render_values_hold_the_device_roots(self):
        roots = {k: str(self.root / k) for k in ("temp_root", "data_root", "models_root", "worktrees_root")}
        doc = dp.build_profile(self.root / "dev", roots, sys.executable, "0.01.000")
        values = dp.render_values(doc)
        for key in ("python", "deploy_root", "temp_root", "data_root", "models_root", "worktrees_root"):
            self.assertIn(key, values)


if __name__ == "__main__":
    unittest.main()
