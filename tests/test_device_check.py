"""device check and the session-check hook handler (C31 handler result carrying the C16 SessionStart output)."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from test_device_support import DeviceCase, ROOT  # noqa: E402

from batuta_lib import config, contract  # noqa: E402
from batuta_lib.areas import device  # noqa: E402

PAYLOAD = {"hook_event_name": "SessionStart", "source": "startup"}


def schema(cid):
    return contract.load_schema(contract.find_schema(config.contracts_dir(), cid))


class Check(DeviceCase):
    def ready(self, core=False):
        """A fully restored device; returns the config path when `core` is set."""
        self.assertEqual(0, self.deploy()[0])
        self.add_launcher()
        env = {"BATUTA_CONFIG": ""}
        if core:
            cfg = config.default_config({"BATUTA_HOME": str(self.bh)})
            cfg["user_core"] = {"template": "templates/user/CLAUDE.template.md",
                                "values": {"user_name": "T", "language": "English", "tone": "Direct."}}
            path = self.root / "batuta.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            env = {"BATUTA_CONFIG": str(path)}
        for role in config.default_config()["roles"]:
            agents = self.home / ".claude" / "agents"
            agents.mkdir(parents=True, exist_ok=True)
            (agents / f"{role}.md").write_text("---\nname: x\n---\n", encoding="utf-8")
        self.restore(env=env)
        return env

    def check(self, *extra, env=None):
        return self.cli("device", "check", "--deploy-root", str(self.deploy_dir), "--home", str(self.home), *extra, env=env)

    def result(self, env=None):
        with mock.patch.dict(os.environ, {**self.env, **(env or {})}):
            return device.session_check(PAYLOAD, home=self.home, deploy_root=self.deploy_dir)

    def test_complete_device_is_ok(self):
        env = self.ready(core=True)
        code, out, _ = self.check(env=env)
        self.assertEqual(0, code, out)
        for word in ("device copy", "settings", "agents", "user core"):
            self.assertIn(word, out)

    def test_hook_result_is_a_c31_handler_result_and_its_output_is_c16(self):
        env = self.ready(core=True)
        res = self.result(env)
        self.assertEqual([], contract.validate_instance("C31", res, schema("C31")))
        self.assertEqual(0, res["exit_code"])
        out = res["output"]
        self.assertEqual([], contract.validate_instance("C16", out, schema("C16")))
        self.assertIn("OK", out["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("INCOMPLETE", out["hookSpecificOutput"]["additionalContext"])

    def test_payload_fixture_is_c16_input(self):
        self.assertEqual([], contract.validate_instance("C16", PAYLOAD, schema("C16")))

    def test_hooks_table_is_a_literal_dict_with_the_session_check_id(self):
        found, problems = contract.discover_hook_ids(ROOT / "plugins" / "batuta" / "scripts" / "batuta_lib" / "areas")
        self.assertEqual([], problems)
        self.assertIn("device", found["session-check"])
        self.assertIs(device.HOOKS["session-check"], device.handler)

    def test_no_device_copy_is_incomplete_with_the_exact_fix(self):
        res = self.result()
        text = res["output"]["hookSpecificOutput"]["additionalContext"]
        self.assertIn("INCOMPLETE", text)
        self.assertIn("device deploy --apply", text)
        self.assertEqual(0, res["exit_code"])

    def test_missing_settings_items_name_the_restore_fix(self):
        self.ready()
        self.settings.write_text("{}", encoding="utf-8")     # the reset case
        text = self.result()["output"]["hookSpecificOutput"]["additionalContext"]
        self.assertIn("INCOMPLETE", text)
        self.assertIn("device restore --apply", text)
        self.assertIn("hooks.SessionStart", text)

    def test_missing_agents_are_reported(self):
        env = self.ready()
        for p in (self.home / ".claude" / "agents").glob("*.md"):
            p.unlink()
        code, out, _ = self.check(env=env)
        self.assertEqual(1, code)
        self.assertIn("agents", out)

    def test_changed_user_core_is_reported_different(self):
        env = self.ready(core=True)
        (self.home / ".claude" / "CLAUDE.md").write_text("# edited\n", encoding="utf-8")
        code, out, _ = self.check(env=env)
        self.assertEqual(1, code)
        self.assertIn("user core", out)

    def test_hook_cli_prints_the_same_object(self):
        env = self.ready(core=True)
        code, out, _ = self.check("--hook", env=env)
        self.assertEqual(0, code)
        printed = json.loads(out)
        self.assertEqual([], contract.validate_instance("C16", printed, schema("C16")))
        self.assertEqual(self.result(env)["output"], printed)

    def test_hook_cli_exits_0_even_when_incomplete(self):
        code, out, _ = self.check("--hook")
        self.assertEqual(0, code)
        self.assertIn("INCOMPLETE", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_output_is_capped_at_10000_characters(self):
        self.ready()
        with mock.patch.object(device, "_check_items", return_value=[
                {"tag": "FAIL", "message": "x" * 400} for _ in range(100)]):
            text = self.result()["output"]["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(text), 10000)
        self.assertIn("INCOMPLETE", text)

    def test_an_internal_error_still_yields_a_valid_incomplete_object(self):
        with mock.patch.object(device, "_check_items", side_effect=RuntimeError("boom")):
            res = self.result()
        self.assertEqual([], contract.validate_instance("C31", res, schema("C31")))
        self.assertIn("boom", res["output"]["hookSpecificOutput"]["additionalContext"])

    def test_check_in_process_is_well_under_two_seconds(self):
        env = self.ready(core=True)
        start = time.perf_counter()
        self.result(env)
        self.assertLess(time.perf_counter() - start, 2.0)

    def test_first_hook_check_after_a_fresh_deploy_is_under_two_seconds_net_of_interpreter_start(self):
        env = self.ready(core=True)
        # The user-visible start: the first `device check --hook` after a deploy, whose copy holds no bytecode yet
        # (every deploy drops it), so the interpreter compiles the modules. The requirement's two seconds are
        # Batuta's own work, so the machine's interpreter start-up is measured right before (best of 3) and subtracted.
        assert not list(self.deploy_dir.rglob("__pycache__")), "the fresh copy must hold no bytecode"
        run_env = {**os.environ, **self.env, **env}

        def timed(argv):
            t = time.perf_counter()
            proc = subprocess.run(argv, capture_output=True, text=True, env=run_env)
            return time.perf_counter() - t, proc

        empty = min(timed([sys.executable, "-I", "-c", "pass"])[0] for _ in range(3))
        if empty > 1.0:
            self.skipTest(f"machine too loaded to time a cold start: an empty interpreter alone took {empty:.2f} s")
        wall, proc = timed([sys.executable, "-I", str(self.deploy_dir / "scripts" / "batuta.py"), "device", "check",
                            "--hook", "--deploy-root", str(self.deploy_dir), "--home", str(self.home)])
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertLess(wall - empty, 2.0, f"first hook check after a deploy: wall {wall:.2f} s, empty interpreter "
                                           f"{empty:.2f} s, net {wall - empty:.2f} s")
        self.assertIn("OK", json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_fix_for_a_broken_copy_never_deploys_the_copy_into_itself(self):
        """Review finding F5: run from the copy, the fix names the source it was deployed from or the reinstall step."""
        self.assertEqual(0, self.deploy()[0])
        (self.deploy_dir / "device.json").write_text("{broken", encoding="utf-8")
        with mock.patch.object(device, "PLUGIN_ROOT", self.deploy_dir):   # the copy's own CLI runs from the copy
            text = device.session_check(PAYLOAD, home=self.home, deploy_root=self.deploy_dir)[
                "output"]["hookSpecificOutput"]["additionalContext"]
        own = (self.deploy_dir / "scripts" / "batuta.py").as_posix()
        self.assertNotIn(own, text)
        self.assertIn("reinstall", text.lower())

    def test_fix_names_the_deployed_from_source_when_the_profile_is_readable(self):
        self.assertEqual(0, self.deploy()[0])
        source = (ROOT / "plugins" / "batuta").as_posix()
        profile = json.loads((self.deploy_dir / "device.json").read_text(encoding="utf-8"))
        profile.pop("batuta_version")                      # no longer C15, but deployed_from is readable
        (self.deploy_dir / "device.json").write_text(json.dumps(profile), encoding="utf-8")
        with mock.patch.object(device, "PLUGIN_ROOT", self.deploy_dir):
            text = device.session_check(PAYLOAD, home=self.home, deploy_root=self.deploy_dir)[
                "output"]["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"{source}/scripts/batuta.py".lower(), text.lower())
        self.assertIn("device deploy --apply", text)
        self.assertNotIn((self.deploy_dir / "scripts" / "batuta.py").as_posix(), text)

    def test_a_deliberate_env_override_does_not_make_the_line_incomplete(self):
        """Review finding F10: a user value kept on purpose is a note, not a gap."""
        env = self.ready(core=True)
        doc = self.settings_doc()
        doc["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] = "opus"
        self.settings.write_text(json.dumps(doc), encoding="utf-8")
        text = self.result(env)["output"]["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(text.startswith("Batuta device check: OK"), text)
        self.assertIn("CLAUDE_CODE_SUBAGENT_MODEL", text)      # still reported, as a note

    def test_a_skipped_preset_does_not_make_the_line_incomplete(self):
        env = self.ready(core=True)
        (self.deploy_dir / "scripts" / "hook.py").unlink()     # the launcher of the hooks unit is not there
        doc = self.settings_doc()
        doc.pop("hooks")
        self.settings.write_text(json.dumps(doc), encoding="utf-8")
        text = self.result(env)["output"]["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(text.startswith("Batuta device check: OK"), text)
        self.assertIn("hook.py", text)


if __name__ == "__main__":
    unittest.main()
