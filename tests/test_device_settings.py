"""Append-only settings merge with verification after the write (concurrent rewrites by running sessions)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
from batuta_lib import settings_merge as sm  # noqa: E402

PRESETS = ROOT / "templates" / "presets"
VALUES = {"spawn_depth": "1", "max_concurrent_agents": "4"}


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "settings.json"
        self.launcher = self.dir / "dev" / "scripts" / "hook.py"
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text("# launcher\n", encoding="utf-8")
        base = sm.render_preset(sm.load_preset(PRESETS / "base.json"), VALUES)
        hook = sm.render_preset(sm.load_preset(PRESETS / "session-check.json"),
                                {"python": (self.dir / "py" / "python").as_posix(), "deploy_root": (self.dir / "dev").as_posix()})
        self.preset = sm.combine([base, hook])
        self.sleeps = []

    def write(self, doc):
        self.path.write_text(json.dumps(doc), encoding="utf-8")

    def doc(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def run_write(self, **kw):
        return sm.write_verified(self.path, self.preset, sleep=self.sleeps.append, **kw)


class RenderedEntryTests(Case):
    """Decision 19: the rendered C31 profile, checked structurally until the contracts add the callable check."""

    def test_rendered_entry_satisfies_the_frozen_c31_rendered_profile(self):
        from batuta_lib import contract
        entry = self.preset["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertEqual([], contract.check_rendered_entry(entry, "SessionStart"))

    def test_unrendered_template_entry_fails_the_rendered_profile(self):
        from batuta_lib import contract
        raw = sm.load_preset(PRESETS / "session-check.json")["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertNotEqual([], contract.check_rendered_entry(raw, "SessionStart"))

    def test_rendered_entry_is_exec_form_with_absolute_paths_and_no_leftover(self):
        entry = self.preset["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertEqual("command", entry["type"])
        self.assertTrue(Path(entry["command"]).is_absolute())
        args = entry["args"]
        launcher = [a for a in args if a.endswith("/scripts/hook.py")]
        self.assertEqual(1, len(launcher))
        self.assertTrue(Path(launcher[0]).is_absolute())
        self.assertEqual("session-check", args[-1])
        self.assertRegex(args[-1], r"^[a-z][a-z0-9-]*$")
        self.assertNotIn("shell", entry)
        self.assertNotIn("{{", json.dumps(self.preset))
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", json.dumps(self.preset))

    def test_missing_placeholder_value_is_an_error(self):
        from batuta_lib import render
        with self.assertRaises(render.RenderError):
            sm.render_preset(sm.load_preset(PRESETS / "session-check.json"), {"python": "x"})


class MergeTests(Case):
    def test_absent_file_is_created_with_every_item(self):
        r = self.run_write()
        self.assertTrue(r["wrote"])
        self.assertIsNone(r["backup"])
        d = self.doc()
        self.assertEqual("sonnet", d["env"]["CLAUDE_CODE_SUBAGENT_MODEL"])
        self.assertEqual("1", d["env"]["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"])
        self.assertEqual("4", d["env"]["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"])
        self.assertEqual(["Agent(Explore)", "Agent(Plan)", "Agent(model:fable)"], d["permissions"]["deny"])
        self.assertEqual(["Agent(model:opus)"], d["permissions"]["ask"])
        self.assertEqual("session-check", d["hooks"]["SessionStart"][0]["hooks"][0]["args"][-1])

    def test_empty_object_reset_case(self):
        self.write({})
        self.run_write()
        self.assertEqual([], sm.gaps(self.doc(), self.preset))

    def test_user_entries_are_never_removed_or_reordered(self):
        user = {"env": {"MINE": "1"}, "permissions": {"deny": ["Bash(rm:*)"], "allow": ["Read"], "ask": ["Edit"]},
                "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}],
                          "Stop": [{"hooks": [{"type": "command", "command": "echo bye"}]}]}, "model": "opus"}
        self.write(user)
        self.run_write()
        d = self.doc()
        self.assertEqual("1", d["env"]["MINE"])
        self.assertEqual("Bash(rm:*)", d["permissions"]["deny"][0])
        self.assertEqual(["Read"], d["permissions"]["allow"])
        self.assertEqual("Edit", d["permissions"]["ask"][0])
        self.assertEqual("echo hi", d["hooks"]["SessionStart"][0]["hooks"][0]["command"])
        self.assertEqual(2, len(d["hooks"]["SessionStart"]))
        self.assertEqual(user["hooks"]["Stop"], d["hooks"]["Stop"])
        self.assertEqual("opus", d["model"])
        self.assertEqual(list(user), list(d)[:len(user)])

    def test_backup_is_made_before_the_first_write_only(self):
        self.write({"model": "opus"})
        r = self.run_write()
        self.assertIsNotNone(r["backup"])
        self.assertIn(".bak-", r["backup"].name)
        self.assertEqual({"model": "opus"}, json.loads(r["backup"].read_text(encoding="utf-8")))

    def test_second_run_changes_nothing_and_makes_no_backup(self):
        self.write({"a": 1})
        self.run_write()
        before = self.path.read_bytes()
        r = self.run_write()
        self.assertFalse(r["wrote"])
        self.assertIsNone(r["backup"])
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(1, len(list(self.dir.glob("settings.json.bak-*"))))

    def test_existing_env_value_is_kept_and_reported(self):
        self.write({"env": {"CLAUDE_CODE_SUBAGENT_MODEL": "opus"}})
        rows = sm.plan(self.doc(), self.preset)
        self.assertIn("WARN", [t for t, label in rows if "SUBAGENT_MODEL" in label])
        self.run_write()
        self.assertEqual("opus", self.doc()["env"]["CLAUDE_CODE_SUBAGENT_MODEL"])

    def test_bom_is_tolerated(self):
        self.path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"x": 1}).encode("utf-8"))
        self.run_write()
        d = self.doc()
        self.assertEqual(1, d["x"])
        self.assertFalse(self.path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_deny_of_the_wrong_type_is_refused_and_untouched(self):
        self.write({"permissions": {"deny": "Agent(Explore)"}})
        before = self.path.read_bytes()
        with self.assertRaises(sm.SettingsError) as cm:
            self.run_write()
        self.assertIn("permissions.deny", str(cm.exception))
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([], list(self.dir.glob("settings.json.bak-*")))

    def test_invalid_json_and_non_object_are_untouched(self):
        for raw in (b"{not json", b"[1, 2]"):
            self.path.write_bytes(raw)
            with self.assertRaises(sm.SettingsError):
                self.run_write()
            self.assertEqual(raw, self.path.read_bytes())

    def test_hook_with_a_missing_launcher_is_not_counted_present(self):
        stale = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "/gone/py",
                                                        "args": ["-I", "/gone/scripts/hook.py", "session-check"]}]}]}}
        self.write(stale)
        self.run_write()
        d = self.doc()
        self.assertEqual(2, len(d["hooks"]["SessionStart"]))
        self.assertEqual("/gone/py", d["hooks"]["SessionStart"][0]["hooks"][0]["command"])


class ConcurrentRewriteTests(Case):
    """The reads of one attempt: 1 initial, 2 before the replace, 3 verification."""

    def rewriting_read(self, on_calls, mutate):
        state = {"n": 0}

        def read(path):
            state["n"] += 1
            if state["n"] in on_calls:
                mutate()
            return sm._read(path)
        return read

    def test_a_key_dropped_once_is_repaired_and_another_sessions_allow_entry_survives(self):
        def other_session():
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            doc.pop("hooks", None)
            doc.setdefault("permissions", {})["allow"] = ["Bash(git status)"]
            self.path.write_text(json.dumps(doc), encoding="utf-8")
        self.write({"model": "opus"})
        notes = []
        r = sm.write_verified(self.path, self.preset, read=self.rewriting_read({3}, other_session),
                              sleep=self.sleeps.append, notes=notes)
        d = self.doc()
        self.assertEqual([], sm.gaps(d, self.preset))
        self.assertEqual(["Bash(git status)"], d["permissions"]["allow"])
        self.assertEqual(2, r["attempts"])
        self.assertEqual([0.5], self.sleeps)
        self.assertTrue(notes)

    def test_reset_to_empty_object_is_repaired(self):
        self.write({"model": "opus"})
        r = sm.write_verified(self.path, self.preset,
                              read=self.rewriting_read({3}, lambda: self.path.write_text("{}", encoding="utf-8")),
                              sleep=self.sleeps.append)
        self.assertEqual([], sm.gaps(self.doc(), self.preset))
        self.assertEqual(2, r["attempts"])

    def test_a_key_dropped_every_time_fails_and_names_the_items(self):
        def drop_hooks():
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            doc.pop("hooks", None)
            self.path.write_text(json.dumps(doc), encoding="utf-8")

        def read(path):
            if path.is_file() and "hooks" in json.loads(path.read_text(encoding="utf-8")):
                drop_hooks()   # a session rewrites the file right after every write of ours
            return sm._read(path)
        self.write({})
        with self.assertRaises(sm.VerifyError) as cm:
            sm.write_verified(self.path, self.preset, read=read, sleep=self.sleeps.append)
        self.assertTrue(any("hooks.SessionStart" in g for g in cm.exception.gaps))
        self.assertIn("hooks.SessionStart", str(cm.exception))
        self.assertIn("3 attempts", str(cm.exception))
        self.assertEqual(2, len(self.sleeps))

    def test_a_write_that_loses_a_race_before_the_replace_is_retried(self):
        def other_session():
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            doc["permissions"] = {"allow": ["Read"]}
            self.path.write_text(json.dumps(doc), encoding="utf-8")
        self.write({"model": "opus"})
        sm.write_verified(self.path, self.preset, read=self.rewriting_read({2}, other_session),
                          sleep=self.sleeps.append)
        d = self.doc()
        self.assertEqual(["Read"], d["permissions"]["allow"])
        self.assertEqual([], sm.gaps(d, self.preset))


class OsErrorTests(Case):
    """Review findings F4 and F6: a sharing violation or a half-written re-read is a lost race, never a traceback."""

    def counting_read(self, fail_on, exc):
        state = {"n": 0}

        def read(path):
            state["n"] += 1
            if fail_on(state["n"]):
                raise exc
            return sm._read(path)
        return read

    def test_permission_error_on_the_verification_read_is_retried(self):
        self.write({"model": "opus"})
        r = sm.write_verified(self.path, self.preset, sleep=self.sleeps.append,
                              read=self.counting_read(lambda n: n == 3, PermissionError(13, "Permission denied")))
        self.assertEqual([], sm.gaps(self.doc(), self.preset))
        self.assertEqual([0.5], self.sleeps)
        self.assertTrue(r["wrote"])

    def test_permission_error_every_time_ends_in_verify_error_naming_items_and_cause(self):
        self.write({"model": "opus"})
        with self.assertRaises(sm.VerifyError) as cm:
            sm.write_verified(self.path, self.preset, sleep=self.sleeps.append,
                              read=self.counting_read(lambda n: n >= 2, PermissionError(13, "Permission denied")))
        self.assertIn("PermissionError", str(cm.exception))
        self.assertIn("3 attempts", str(cm.exception))
        self.assertTrue(any("hooks.SessionStart" in g for g in cm.exception.gaps))

    def test_permission_error_on_the_replace_is_retried_and_leaves_no_temp_file(self):
        self.write({"model": "opus"})
        real = sm.os.replace
        calls = {"n": 0}

        def replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(13, "sharing violation")
            return real(src, dst)
        with mock.patch.object(sm.os, "replace", replace):
            sm.write_verified(self.path, self.preset, sleep=self.sleeps.append)
        self.assertEqual([], sm.gaps(self.doc(), self.preset))
        self.assertEqual([], list(self.dir.glob("settings.json.*.tmp")))

    def test_permission_error_on_every_replace_ends_in_verify_error(self):
        self.write({"model": "opus"})
        before = self.path.read_bytes()

        def replace(src, dst):
            raise PermissionError(13, "sharing violation")
        with mock.patch.object(sm.os, "replace", replace), self.assertRaises(sm.VerifyError) as cm:
            sm.write_verified(self.path, self.preset, sleep=self.sleeps.append)
        self.assertIn("PermissionError", str(cm.exception))
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([], list(self.dir.glob("settings.json.*.tmp")))

    def test_a_half_written_reread_is_retried(self):
        self.write({"model": "opus"})
        real = sm._read
        state = {"n": 0}

        def read(path):
            state["n"] += 1
            data = real(path)
            return data[:10] if state["n"] == 3 else data
        sm.write_verified(self.path, self.preset, sleep=self.sleeps.append, read=read)
        self.assertEqual([], sm.gaps(self.doc(), self.preset))

    def test_a_reread_that_stays_unreadable_does_not_claim_the_file_is_untouched(self):
        self.write({"model": "opus"})
        real = sm._read
        state = {"n": 0}

        def read(path):
            state["n"] += 1
            data = real(path)
            return data[:10] if state["n"] >= 3 else data
        with self.assertRaises(sm.VerifyError) as cm:
            sm.write_verified(self.path, self.preset, sleep=self.sleeps.append, read=read)
        self.assertNotIn("not touched", str(cm.exception))

    def test_an_invalid_file_at_the_start_is_still_refused_untouched(self):
        self.path.write_bytes(b"{broken")
        with self.assertRaises(sm.SettingsError) as cm:
            self.run_write()
        self.assertIn("not touched", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
