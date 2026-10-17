"""`init user` never replaces the user's own files whole: an existing `~/.claude/CLAUDE.md` gets a marker-delimited managed
block and keeps its content; an agent file the user changed is kept unless `--force` (then backed up)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import World, snapshot  # noqa: E402

from batuta_lib import install_manifest as im  # noqa: E402


class UserCore(World):
    def core(self):
        return self.home / ".claude" / "CLAUDE.md"

    def test_an_existing_claude_md_keeps_the_users_text_and_gains_one_managed_block(self):
        mine = "# My global rules\n\nAlways answer briefly.\n"
        self.core().write_text(mine, encoding="utf-8")
        before = snapshot(self.root)
        code, out, err = self.init_user("--var", "user_name=Ada")
        self.assertIn(code, (0, 2), out + err)
        text = self.core().read_text(encoding="utf-8")
        self.assertTrue(text.startswith(mine))
        self.assertEqual(text.count("<!-- batuta:begin"), 1)
        self.assertEqual(text.count("<!-- batuta:end -->"), 1)
        self.assertIn("Ada", text)
        self.assertRegex(out, r"MERGED CLAUDE\.md")
        backups = list((self.home / ".claude").glob("CLAUDE.md.bak-*"))
        self.assertEqual([b.read_text(encoding="utf-8") for b in backups], [mine])
        again = snapshot(self.root)
        code, out, err = self.init_user("--var", "user_name=Ada")
        self.assertEqual(snapshot(self.root), again, "a second run changes nothing")
        code, out, err = self.cli("init", "uninstall", "--scope", "user", "--home", str(self.home), "--apply")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(snapshot(self.root), before)

    def test_the_block_follows_a_changed_value_and_leaves_text_around_it(self):
        self.core().write_text("# Mine\n", encoding="utf-8")
        self.init_user("--var", "user_name=Ada")
        self.core().write_text(self.core().read_text(encoding="utf-8") + "\nadded below\n", encoding="utf-8")
        cfg = self.bh / "batuta.json"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("Ada", "Grace"), encoding="utf-8")   # the config is yours
        self.cli("init", "update", "--scope", "user", "--home", str(self.home), "--apply")
        text = self.core().read_text(encoding="utf-8")
        self.assertIn("Grace", text)
        self.assertNotIn("Ada", text)
        self.assertIn("added below", text)
        self.assertEqual(text.count("<!-- batuta:begin"), 1)

    def test_a_fresh_home_gets_the_plain_rendering_without_markers(self):
        self.init_user("--var", "user_name=Ada")
        text = self.core().read_text(encoding="utf-8")
        self.assertNotIn("batuta:begin", text)
        self.assertIn("Ada", text)

    def test_doctor_calls_the_user_core_current_when_it_is_a_managed_block(self):
        self.core().write_text("# Mine\n", encoding="utf-8")
        self.init_user()
        code, out, err = self.cli("init", "doctor", "--home", str(self.home), "--channel", "device")
        self.assertNotRegex(out, r"(?m)^FAIL .*user core", out)
        self.assertRegex(out, r"OK user core current")


class Agents(World):
    def agent(self):
        return self.home / ".claude" / "agents" / "searcher.md"

    def test_an_agent_file_the_user_changed_is_kept_unless_forced(self):
        (self.home / ".claude" / "agents").mkdir()
        self.agent().write_text("my own searcher\n", encoding="utf-8")
        code, out, _ = self.init_user()
        self.assertEqual(self.agent().read_text(encoding="utf-8"), "my own searcher\n")
        self.assertRegex(out, r"DIFFERENT agents/searcher\.md")
        self.assertEqual(code, 2, out)
        self.assertEqual(list((self.home / ".claude" / "agents").glob("searcher.md.bak-*")), [])
        code, out, _ = self.init_user("--force")
        self.assertRegex(out, r"CHANGED agents/searcher\.md")
        self.assertNotEqual(self.agent().read_text(encoding="utf-8"), "my own searcher\n")
        backups = list((self.home / ".claude" / "agents").glob("searcher.md.bak-*"))
        self.assertEqual([b.read_text(encoding="utf-8") for b in backups], ["my own searcher\n"])

    def test_an_installed_agent_file_the_user_did_not_touch_is_updated_by_update(self):
        self.init_user()
        manifest = im.Manifest.load(self.bh / "installed.json")
        self.assertEqual(manifest.state(self.home / ".claude", "agents/searcher.md"), "SAME")
        self.agent().write_text("older release text\n", encoding="utf-8")
        manifest.record("claude", "agents/searcher.md", b"older release text\n")
        manifest.save()
        code, out, err = self.cli("init", "update", "--scope", "user", "--home", str(self.home), "--apply")
        self.assertRegex(out, r"CHANGED agents/searcher\.md")
        self.assertNotEqual(self.agent().read_text(encoding="utf-8"), "older release text\n")


if __name__ == "__main__":
    unittest.main()
