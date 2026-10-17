"""device restore: presets merged append-only and verified, the user core, the path-scoped stubs."""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from test_device_support import DeviceCase, ROOT  # noqa: E402

from batuta_lib import config, contract, settings_merge  # noqa: E402
from batuta_lib.areas import device  # noqa: E402

TEMPLATES = ROOT / "plugins" / "batuta" / "templates"


class Restore(DeviceCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(0, self.deploy()[0])

    def items(self, out):
        return [line.split(" ", 1)[0] for line in out.splitlines()]

    def test_without_a_device_copy_it_fails_with_the_fix(self):
        code, out, _ = self.cli("device", "restore", "--deploy-root", str(self.root / "none"), "--home", str(self.home))
        self.assertEqual(1, code)
        self.assertIn("device deploy --apply", out)

    def test_dry_run_writes_nothing(self):
        self.add_launcher()
        code, out, _ = self.restore(apply=False)
        self.assertEqual(2, code, out)   # the user core is not configured: a WARN
        self.assertIn("NEW", out)
        self.assertFalse(self.settings.exists())

    def test_apply_writes_the_presets_into_settings(self):
        launcher = self.add_launcher()
        code, out, _ = self.restore(env={"BATUTA_CONFIG": ""})
        self.assertEqual(2, code, out)   # the user core is not configured: a WARN
        d = self.settings_doc()
        self.assertEqual("sonnet", d["env"]["CLAUDE_CODE_SUBAGENT_MODEL"])
        self.assertEqual("1", d["env"]["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"])
        self.assertIn("Agent(model:fable)", d["permissions"]["deny"])
        self.assertIn("Agent(model:opus)", d["permissions"]["ask"])
        entry = d["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertTrue(Path(entry["command"]).is_absolute())
        self.assertEqual(launcher.as_posix(), entry["args"][1])
        self.assertEqual("session-check", entry["args"][-1])
        self.assertNotIn("{{", self.settings.read_text(encoding="utf-8"))

    def test_second_apply_is_idempotent_with_no_new_backup(self):
        self.add_launcher()
        self.settings.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
        self.restore()
        before = self.settings.read_bytes()
        code, out, _ = self.restore()
        self.assertEqual(before, self.settings.read_bytes())
        self.assertEqual(1, len(list(self.settings.parent.glob("settings.json.bak-*"))))
        self.assertNotIn("NEW", out)

    def test_missing_launcher_skips_only_the_session_check_with_a_warn(self):
        # the device copy is made inside the test's temp folder; it is the copy that loses its launcher, so the branch is
        # tested whatever the repository holds
        (self.deploy_dir / "scripts" / "hook.py").unlink(missing_ok=True)
        self.assertFalse((self.deploy_dir / "scripts" / "hook.py").exists())
        code, out, _ = self.restore()
        self.assertEqual(2, code)
        self.assertIn("WARN", out)
        self.assertIn("hook.py", out)
        d = self.settings_doc()
        self.assertEqual("sonnet", d["env"]["CLAUDE_CODE_SUBAGENT_MODEL"])
        self.assertNotIn("hooks", d)

    def test_user_entries_survive(self):
        self.add_launcher()
        user = {"permissions": {"deny": ["Bash(rm:*)"], "allow": ["Read"]},
                "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
        self.settings.write_text(json.dumps(user), encoding="utf-8")
        self.restore()
        d = self.settings_doc()
        self.assertEqual("Bash(rm:*)", d["permissions"]["deny"][0])
        self.assertEqual(["Read"], d["permissions"]["allow"])
        self.assertEqual("echo hi", d["hooks"]["SessionStart"][0]["hooks"][0]["command"])

    def test_wrong_type_refuses_and_leaves_the_file_alone(self):
        self.add_launcher()
        self.settings.write_text(json.dumps({"permissions": {"deny": "x"}}), encoding="utf-8")
        before = self.settings.read_bytes()
        code, out, _ = self.restore()
        self.assertEqual(1, code)
        self.assertIn("permissions.deny", out)
        self.assertEqual(before, self.settings.read_bytes())

    def test_home_without_claude_folder_is_created(self):
        self.add_launcher()
        bare = self.root / "bare"
        bare.mkdir()
        code, out, _ = self.cli("device", "restore", "--deploy-root", str(self.deploy_dir), "--home", str(bare), "--apply")
        self.assertTrue((bare / ".claude" / "settings.json").is_file(), out)

    def test_bom_settings_are_merged(self):
        self.add_launcher()
        self.settings.write_bytes(b"\xef\xbb\xbf" + json.dumps({"x": 1}).encode("utf-8"))
        self.restore()
        self.assertEqual(1, self.settings_doc()["x"])

    def test_concurrent_rewrite_once_is_repaired_and_success_means_nothing_is_missing(self):
        self.add_launcher()
        self.settings.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
        state = {"n": 0}
        real = settings_merge._read

        def read(path):
            state["n"] += 1
            if state["n"] == 4:   # reads: 1 plan, 2 first attempt, 3 before the replace, 4 verification: a session drops the hooks
                doc = json.loads(Path(path).read_text(encoding="utf-8"))
                doc.pop("hooks")
                doc["permissions"]["allow"] = ["Bash(git status)"]
                Path(path).write_text(json.dumps(doc), encoding="utf-8")
            return real(path)
        with mock.patch.object(device, "_settings_read", read), mock.patch.object(device, "_settings_sleep", lambda s: None):
            code, out, _ = self.restore()
        d = self.settings_doc()
        self.assertIn("SessionStart", d["hooks"])
        self.assertEqual(["Bash(git status)"], d["permissions"]["allow"])
        self.assertIn(code, (0, 2))

    def test_concurrent_rewrite_every_time_exits_1_naming_the_items(self):
        self.add_launcher()
        real = settings_merge._read

        def read(path):
            p = Path(path)
            if p.is_file() and "hooks" in json.loads(p.read_text(encoding="utf-8")):
                doc = json.loads(p.read_text(encoding="utf-8"))
                doc.pop("hooks")
                p.write_text(json.dumps(doc), encoding="utf-8")
            return real(path)
        with mock.patch.object(device, "_settings_read", read), mock.patch.object(device, "_settings_sleep", lambda s: None):
            code, out, _ = self.restore()
        self.assertEqual(1, code)
        self.assertIn("hooks.SessionStart", out)
        self.assertIn("3 attempts", out)
        self.assertNotIn("OK settings", out)


class RestoreOsErrors(DeviceCase):
    """Review finding F4: a sharing violation is a FAIL item naming the items, never a traceback."""

    def setUp(self):
        super().setUp()
        self.assertEqual(0, self.deploy()[0])
        self.add_launcher()

    def test_permission_error_on_every_read_after_the_plan_is_a_fail_item_not_a_traceback(self):
        real = settings_merge._read
        state = {"n": 0}

        def read(path):
            state["n"] += 1
            if state["n"] >= 2:
                raise PermissionError(13, "Permission denied")
            return real(path)
        with mock.patch.object(device, "_settings_read", read), mock.patch.object(device, "_settings_sleep", lambda s: None):
            code, out, _ = self.restore()
        self.assertEqual(1, code)
        self.assertIn("FAIL", out)
        self.assertIn("PermissionError", out)
        self.assertIn("hooks.SessionStart", out)

    def test_permission_error_once_on_the_verification_read_is_repaired(self):
        real = settings_merge._read
        state = {"n": 0}

        def read(path):
            state["n"] += 1
            if state["n"] == 4:
                raise PermissionError(13, "Permission denied")
            return real(path)
        with mock.patch.object(device, "_settings_read", read), mock.patch.object(device, "_settings_sleep", lambda s: None):
            code, out, _ = self.restore()
        self.assertIn(code, (0, 2), out)
        self.assertIn("SessionStart", self.settings_doc()["hooks"])

    def test_permission_error_on_the_first_read_is_a_fail_item(self):
        def read(path):
            raise PermissionError(13, "Permission denied")
        with mock.patch.object(device, "_settings_read", read):
            code, out, _ = self.restore()
        self.assertEqual(1, code)
        self.assertIn("PermissionError", out)


class UserCoreRefusals(DeviceCase):
    """Review finding F8: the template is a relative path inside the device copy and the values are strings."""

    def setUp(self):
        super().setUp()
        self.assertEqual(0, self.deploy()[0])
        from batuta_lib import device_profile as dp
        self.profile = dp.read_profile(self.deploy_dir)

    def core(self, uc):
        items = []
        text = device._user_core({"user_core": uc}, self.profile, self.deploy_dir, items)
        return text, items

    def test_absolute_dotdot_and_non_string_values_are_refused(self):
        good = {"user_name": "T", "language": "English", "tone": "Direct."}
        real = (self.deploy_dir / "templates" / "user" / "CLAUDE.template.md")
        for uc in ({"template": real.as_posix(), "values": good},                 # absolute, and it exists
                   {"template": "C:/abs/CLAUDE.template.md"}, {"template": "/etc/passwd"},
                   {"template": "\\\\host\\share\\t.md"}, {"template": "../../outside.md"},
                   {"template": "templates/../templates/user/CLAUDE.template.md", "values": good},   # `..`, resolves
                   {"template": "templates/user/CLAUDE.template.md", "values": {**good, "user_name": 3}},
                   {"template": "templates/user/CLAUDE.template.md", "values": ["x"]}, {"template": 5}):
            with self.subTest(uc=uc):
                text, items = self.core(uc)
                self.assertIsNone(text)
                self.assertEqual(["REFUSED"], [i["tag"] for i in items])

    def test_a_valid_user_core_still_renders(self):
        text, items = self.core({"template": "templates/user/CLAUDE.template.md",
                                 "values": {"user_name": "T", "language": "English", "tone": "Direct."}})
        self.assertIsNotNone(text, items)

    def test_the_frozen_c01_refuses_the_same_values_at_load(self):
        cfg = config.default_config({"BATUTA_HOME": str(self.bh)})
        cfg["user_core"] = {"template": "C:/abs/CLAUDE.template.md"}
        path = self.root / "batuta.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        code, out, _ = self.restore(env={"BATUTA_CONFIG": str(path)})
        self.assertEqual(1, code)
        self.assertIn("C01", out)


class UserCore(DeviceCase):
    def setUp(self):
        super().setUp()
        self.deploy()
        self.add_launcher()
        cfg = config.default_config({"BATUTA_HOME": str(self.bh)})
        cfg["user_core"] = {"template": "templates/user/CLAUDE.template.md",
                            "values": {"user_name": "Test User", "language": "English", "tone": "Direct."}}
        self.cfg_path = self.root / "batuta.json"
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        self.core = self.home / ".claude" / "CLAUDE.md"

    def go(self, apply=True):
        return self.restore(apply=apply, env={"BATUTA_CONFIG": str(self.cfg_path)})

    def test_core_is_rendered_with_device_values(self):
        code, out, _ = self.go()
        self.assertEqual(0, code, out)
        text = self.core.read_text(encoding="utf-8")
        self.assertNotIn("{{", text)
        self.assertIn("Test User", text)
        self.assertIn(self.deploy_dir.as_posix() + "/reference/deep-work.md", text)

    def test_second_apply_is_same(self):
        self.go()
        code, out, _ = self.go()
        self.assertIn("SAME", out)
        self.assertEqual(0, code)

    def test_a_different_existing_core_is_backed_up_then_replaced(self):
        self.core.write_text("# hand written\n", encoding="utf-8")
        self.go()
        backups = list(self.core.parent.glob("CLAUDE.md.bak-*"))
        self.assertEqual(1, len(backups))
        self.assertEqual("# hand written\n", backups[0].read_text(encoding="utf-8"))
        self.assertIn("Test User", self.core.read_text(encoding="utf-8"))

    def test_missing_value_is_refused_and_nothing_written(self):
        cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        del cfg["user_core"]["values"]["tone"]
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        code, out, _ = self.go()
        self.assertEqual(1, code)
        self.assertIn("tone", out)
        self.assertFalse(self.core.exists())

    def test_no_template_configured_is_a_warn_naming_the_key(self):
        code, out, _ = self.restore(env={"BATUTA_CONFIG": ""})
        self.assertEqual(2, code)
        self.assertIn("user_core.template", out)
        self.assertFalse(self.core.exists())

    def test_template_that_does_not_exist_is_refused(self):
        cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        cfg["user_core"]["template"] = "templates/user/none.md"
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        code, out, _ = self.go()
        self.assertEqual(1, code)


class Stubs(DeviceCase):
    LINK = re.compile(r"`([^`\n]+\.md)`")

    def setUp(self):
        super().setUp()
        self.deploy()
        self.add_launcher()
        self.out = self.root / "build"
        code, text, _ = self.cli("context", "build", "--manifest", str(TEMPLATES / "knowledge" / "manifest.json"),
                                 "--out", str(self.out), "--apply")
        self.assertEqual(0, code, text)
        self.rules = self.home / ".claude" / "rules"

    def install(self, *extra):
        return self.restore("--stubs", str(self.out / "rules"), *extra, env={"BATUTA_CONFIG": ""})

    def test_every_installed_stub_link_resolves_from_its_installed_location(self):
        code, out, _ = self.install()
        stubs = sorted(self.rules.glob("*.md"))
        self.assertTrue(stubs, out)
        for stub in stubs:
            links = self.LINK.findall("\n".join(
                line for line in stub.read_text(encoding="utf-8").splitlines()
                if line.startswith(("Full text:", "Also read:"))))
            self.assertTrue(links, stub.name)
            for link in links:
                self.assertTrue((stub.parent / link).resolve().is_file(), f"{stub.name}: {link}")

    def test_the_build_layout_link_alone_would_not_resolve_after_install(self):
        built = next((self.out / "rules").glob("*.md")).read_text(encoding="utf-8")
        link = self.LINK.findall(built)[0]
        self.assertFalse((self.rules / link).resolve().is_file())   # why the rewrite exists
        self.install()
        installed = next(self.rules.glob("*.md")).read_text(encoding="utf-8")
        self.assertNotIn(f"`{link}`", installed)

    def test_second_install_is_same(self):
        self.install()
        before = {p.name: p.read_bytes() for p in self.rules.glob("*.md")}
        code, out, _ = self.install()
        self.assertNotIn("NEW", out)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.rules.glob("*.md")})

    def test_an_unmarked_file_is_not_overwritten_without_force(self):
        self.rules.mkdir(parents=True)
        name = next((self.out / "rules").glob("*.md")).name
        (self.rules / name).write_text("mine\n", encoding="utf-8")
        code, out, _ = self.install()
        self.assertIn("DIFFERENT", out)
        self.assertEqual("mine\n", (self.rules / name).read_text(encoding="utf-8"))
        self.install("--force")
        self.assertNotEqual("mine\n", (self.rules / name).read_text(encoding="utf-8"))
        self.assertEqual(1, len(list(self.rules.glob(name + ".bak-*"))))

    def test_a_link_that_does_not_resolve_is_reported(self):
        (self.out / "rules" / "broken.md").write_text(
            "---\npaths:\n  - \"x/**\"\n---\n" + device.STUB_MARK + "\n# T\n\nS\n\nFull text: `../../nowhere/x.md`; read it.\n",
            encoding="utf-8")
        code, out, _ = self.install()
        self.assertIn("nowhere/x.md", out)
        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
