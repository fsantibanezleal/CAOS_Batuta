"""device backup: the learned state of this device into a bundle folder, refusing any secret pattern."""
import json
import unittest
from pathlib import Path

from test_device_support import DeviceCase, tree_digest  # noqa: E402

from batuta_lib import config  # noqa: E402
from batuta_lib.areas import device  # noqa: E402


def fake_token():
    """Built at run time so no secret-shaped literal sits in the repository."""
    return "ghp_" + "a1B2c3D4e5" * 4


class Backup(DeviceCase):
    def setUp(self):
        super().setUp()
        self.claude = self.home / ".claude"
        (self.claude / "agents").mkdir()
        (self.claude / "agents" / "reviewer.md").write_text("---\nname: reviewer\n---\nReview.\n", encoding="utf-8")
        mem = self.claude / "projects" / "-some-project" / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("- [A](a.md) - a lesson\n", encoding="utf-8")
        (mem / "a.md").write_text("A lesson learned.\n", encoding="utf-8")
        self.settings.write_text(json.dumps({"env": {"X": "1"}, "permissions": {"allow": ["Read"]}, "theme": "dark",
                                             "hooks": {"Stop": []}}), encoding="utf-8")
        (self.claude / "CLAUDE.md").write_text("# hand written core\n", encoding="utf-8")
        self.rules = self.claude / "rules"
        self.rules.mkdir()
        (self.rules / "mine.md").write_text("# my rule\n", encoding="utf-8")
        (self.rules / "stub.md").write_text("---\npaths:\n  - \"x/**\"\n---\n" + device.STUB_MARK + "\n# T\n", encoding="utf-8")
        self.bundle = self.root / "bundle"

    def backup(self, *extra, apply=True, env=None):
        args = ["device", "backup", "--out", str(self.bundle), "--home", str(self.home), *extra]
        return self.cli(*args, *(["--apply"] if apply else []), env=env)

    def test_dry_run_writes_nothing(self):
        code, out, _ = self.backup(apply=False)
        self.assertEqual(0, code, out)
        self.assertFalse(self.bundle.exists())

    def test_apply_collects_the_learned_state(self):
        code, out, _ = self.backup()
        self.assertEqual(0, code, out)
        files = set(tree_digest(self.bundle))
        self.assertIn("agents/reviewer.md", files)
        self.assertIn("memory/-some-project/MEMORY.md", files)
        self.assertIn("memory/-some-project/a.md", files)
        self.assertIn("rules/mine.md", files)
        self.assertIn("settings.agentic.json", files)
        self.assertIn("MANIFEST.json", files)
        subset = json.loads((self.bundle / "settings.agentic.json").read_text(encoding="utf-8"))
        self.assertEqual({"env", "hooks"}, set(subset))       # no permissions allow list, no theme

    def test_generated_stubs_are_never_collected(self):
        self.backup()
        self.assertNotIn("rules/stub.md", tree_digest(self.bundle))

    def test_user_core_is_collected_only_when_it_is_not_rendered_from_a_template(self):
        self.backup()
        self.assertIn("user/CLAUDE.md", tree_digest(self.bundle))
        cfg = config.default_config({"BATUTA_HOME": str(self.bh)})
        cfg["user_core"] = {"template": "templates/user/CLAUDE.template.md", "values": {}}
        path = self.root / "batuta.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        other = self.root / "bundle2"
        code, out, _ = self.cli("device", "backup", "--out", str(other), "--home", str(self.home), "--apply",
                                env={"BATUTA_CONFIG": str(path)})
        self.assertEqual(0, code, out)
        self.assertNotIn("user/CLAUDE.md", tree_digest(other))
        self.assertIn("rendered", out)

    def test_a_planted_token_is_refused_and_nothing_is_written(self):
        (self.claude / "agents" / "leaky.md").write_text(f"token = {fake_token()}\n", encoding="utf-8")
        code, out, _ = self.backup()
        self.assertEqual(1, code)
        self.assertIn("REFUSED", out)
        self.assertIn("leaky.md:1", out)
        self.assertNotIn(fake_token(), out)
        self.assertFalse(self.bundle.exists())

    def test_a_secret_in_a_memory_page_and_in_settings_is_refused(self):
        (self.claude / "projects" / "-some-project" / "memory" / "a.md").write_text(
            "key: " + fake_token() + "\n", encoding="utf-8")
        self.assertEqual(1, self.backup()[0])
        self.settings.write_text(json.dumps({"env": {"MY_API_TOKEN": "z" * 40}}), encoding="utf-8")
        code, out, _ = self.backup()
        self.assertEqual(1, code)
        self.assertFalse(self.bundle.exists())

    def test_utf16_file_with_a_token_is_scanned(self):
        (self.claude / "agents" / "wide.md").write_bytes(f"t {fake_token()}\n".encode("utf-16"))
        self.assertEqual(1, self.backup()[0])

    def test_variable_placeholders_are_not_secrets(self):
        (self.claude / "agents" / "ok.md").write_text('{"api_token": "${MY_TOKEN_VALUE_FROM_ENV_X}"}\n', encoding="utf-8")
        self.assertEqual(0, self.backup()[0])

    def test_a_reviewed_line_can_be_allowed_by_its_sha256(self):
        line = f"token = {fake_token()}"
        (self.claude / "agents" / "leaky.md").write_text(line + "\n", encoding="utf-8")
        sha = device.line_sha(line)
        code, out, _ = self.backup("--allow", sha)
        self.assertEqual(0, code, out)

    def test_second_apply_changes_nothing(self):
        self.backup()
        before = tree_digest(self.bundle)
        code, out, _ = self.backup()
        self.assertEqual(before, tree_digest(self.bundle))
        self.assertNotIn("NEW", out)

    def test_a_file_that_left_the_device_leaves_the_bundle(self):
        self.backup()
        (self.claude / "agents" / "reviewer.md").unlink()
        code, out, _ = self.backup()
        self.assertIn("REMOVED", out)
        self.assertNotIn("agents/reviewer.md", tree_digest(self.bundle))

    def test_home_without_claude_folder_collects_nothing_and_says_so(self):
        bare = self.root / "bare"
        bare.mkdir()
        code, out, _ = self.cli("device", "backup", "--out", str(self.bundle), "--home", str(bare), "--apply")
        self.assertEqual(2, code)
        self.assertIn("nothing", out)


if __name__ == "__main__":
    unittest.main()
