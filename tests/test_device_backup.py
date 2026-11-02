"""device backup: the learned state of this device into a bundle folder, refusing any secret pattern."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_device_support import DeviceCase, make_file_link, make_link, tree_digest  # noqa: E402

from batuta_lib import config  # noqa: E402
from batuta_lib.areas import device  # noqa: E402


def fake_token():
    """Built at run time so no secret-shaped literal sits in the repository."""
    return "ghp_" + "a1B2c3D4e5" * 4


def samples():
    """One fake secret line per scan pattern, by label, built at run time (no secret-shaped literal in the repository)."""
    a = "a1B2c3D4e5"
    return {
        "GitHub token": "token = ghp_" + a * 4,
        "GitHub fine-grained token": "token = github_pat_" + "A1b2C3d4E5" * 6,
        "Anthropic key": "key = sk-ant-" + "abcDEF123_-" * 3,
        "Slack token": "slack = xoxb-" + "1234567890abc",
        "Google API key": "key = AIza" + "A1b2C3d4E5" * 3 + "A1b2C",
        "GitLab token": "token = glpat-" + a * 2,
        "npm token": "token = npm_" + a * 3 + "a1B2c3",
        "AWS access key": "id = AKIA" + "ABCDEFGHIJKLMNOP",
        "private key": "-----BEGIN RSA PRIVATE" + " KEY-----",   # built at run time: the repository scans clean
        "git access token in URL": "url = https://x-access-token:abcDEF123456@github.com/x/y",
        "credentials in URL": "url = https://someone:" + "a1B2c3D4e5f6G7h8i9" + "@host.example/path",
        "bearer token": "Authorization: Bearer " + a * 3,
        "secret-named value": '{"my_api_token": "' + "z" * 20 + '"}',
    }


class BackupBase(DeviceCase):
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


class Backup(BackupBase):
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


class SecretScanEncodings(BackupBase):
    """Review finding F1: every plausible decoding of every file is scanned."""

    ENCODINGS = {
        "utf-8": lambda text: text.encode("utf-8"),
        "utf-8 with a NUL byte first": lambda text: b"\x00" + text.encode("utf-8"),
        "utf-16 with a BOM": lambda text: text.encode("utf-16"),
        "utf-16-le without a BOM": lambda text: text.encode("utf-16-le"),
        "utf-16-be without a BOM": lambda text: text.encode("utf-16-be"),
    }

    def test_the_samples_really_match_their_pattern(self):
        self.assertEqual(13, len(samples()))
        for label, line in samples().items():
            self.assertIn(label, [lab for _, lab in device.find_secrets(line)], label)

    def test_scan_function_finds_every_pattern_in_every_encoding(self):
        for label, line in samples().items():
            for enc, encode in self.ENCODINGS.items():
                with self.subTest(pattern=label, encoding=enc):
                    hits = device.scan_secrets(encode("note\n" + line + "\n"))
                    self.assertIn(label, [lab for _, lab in hits])

    def test_backup_refuses_the_two_missed_encodings_for_every_pattern_in_agents_and_memory(self):
        memory = self.claude / "projects" / "-some-project" / "memory"
        for where, folder in (("agent", self.claude / "agents"), ("memory", memory)):
            for enc in ("utf-8 with a NUL byte first", "utf-16-be without a BOM"):
                for label, line in samples().items():
                    with self.subTest(pattern=label, encoding=enc, where=where):
                        leak = folder / "leak.md"
                        leak.write_bytes(self.ENCODINGS[enc]("note\n" + line + "\n"))
                        try:
                            code, out, _ = self.backup(apply=False)
                        finally:
                            leak.unlink()
                        self.assertEqual(1, code, out)
                        self.assertIn("REFUSED", out)

    def test_a_clean_file_with_a_nul_byte_is_still_collected(self):
        (self.claude / "agents" / "binary.md").write_bytes(b"\x00\x01 just bytes, no secret\n")
        self.assertEqual(0, self.backup()[0])


class NestedLinks(BackupBase):
    """Re-check of F2: a link or junction nested below an area of an existing bundle is never followed or deleted through."""

    def setUp(self):
        super().setUp()
        self.assertEqual(0, self.backup()[0])               # an existing bundle, with its MANIFEST.json
        self.victim = self.root / "victim"
        (self.victim / "precious").mkdir(parents=True)
        (self.victim / "precious" / "thesis.md").write_text("irreplaceable\n", encoding="utf-8")
        self.before = tree_digest(self.victim)

    def refused(self, label):
        code, out, _ = self.backup()
        self.assertEqual(1, code, out)
        self.assertIn("REFUSED", out)
        self.assertNotIn("REMOVED", out)
        self.assertEqual(self.before, tree_digest(self.victim), label)
        self.assertTrue((self.victim / "precious" / "thesis.md").exists())

    def test_a_junction_directly_below_an_area_root(self):
        make_link(self.bundle / "memory" / "old", self.victim)           # the reviewer's exact case
        self.refused("memory/old")

    def test_a_junction_two_levels_down(self):
        (self.bundle / "rules" / "sub").mkdir()
        make_link(self.bundle / "rules" / "sub" / "old", self.victim)
        self.refused("rules/sub/old")

    def test_a_symlink_file_where_a_managed_file_belongs(self):
        outside = self.root / "outside.md"
        outside.write_text("keep\n", encoding="utf-8")
        (self.bundle / "agents" / "reviewer.md").unlink()
        make_file_link(self.bundle / "agents" / "reviewer.md", outside)
        self.refused("agents/reviewer.md")
        self.assertEqual("keep\n", outside.read_text(encoding="utf-8"))

    def test_a_stale_symlink_file_in_an_area_is_reported_not_followed(self):
        outside = self.root / "outside.md"
        outside.write_text("keep\n", encoding="utf-8")
        make_file_link(self.bundle / "agents" / "ghost.md", outside)
        self.refused("agents/ghost.md")
        self.assertEqual("keep\n", outside.read_text(encoding="utf-8"))

    def test_a_file_link_is_refused_even_where_the_account_cannot_create_symlinks(self):
        # the same check as the two symlink-file cases above, with the link test faked: an account without the
        # symlink privilege (the review machine) cannot create the real thing
        (self.bundle / "agents" / "ghost.md").write_text("stale\n", encoding="utf-8")
        with mock.patch.object(device, "_is_link", lambda p: Path(p).name == "ghost.md"):
            code, out, _ = self.backup()
        self.assertEqual(1, code, out)
        self.assertIn("ghost.md", out)
        self.assertNotIn("REMOVED", out)
        self.assertTrue((self.bundle / "agents" / "ghost.md").exists())

    def test_the_removal_guard_refuses_a_path_that_resolves_outside(self):
        items = []
        make_link(self.bundle / "memory" / "old", self.victim)
        self.assertTrue(device._refuse_escape(self.bundle, ["memory/old/precious/thesis.md"], items))
        self.assertEqual(self.before, tree_digest(self.victim))


class ReviewedTokenOneHash(BackupBase):
    """N1: one hash allows a reviewed token, whatever the encoding it was found in."""

    def leak(self, data):
        (self.claude / "agents" / "reviewed.md").write_bytes(data)

    def hashes(self, out):
        import re
        return re.findall(r"--allow ([0-9a-f]{64})", out)

    def test_utf16_with_a_bom_is_reported_once_and_one_hash_allows_it(self):
        self.leak(("token = " + fake_token() + "\n").encode("utf-16"))
        code, out, _ = self.backup()
        self.assertEqual(1, code)
        self.assertEqual(1, out.count("REFUSED"), out)
        hashes = self.hashes(out)
        self.assertEqual(1, len(hashes))
        code, out, _ = self.backup("--allow", hashes[0])
        self.assertEqual(0, code, out)

    def test_utf16_without_a_bom_and_a_nul_first_file_are_one_hit_each(self):
        for encode in (lambda s: s.encode("utf-16-be"), lambda s: s.encode("utf-16-le"), lambda s: b"\x00" + s.encode()):
            with self.subTest():
                self.leak(encode("token = " + fake_token() + "\n"))
                code, out, _ = self.backup()
                self.assertEqual(1, code)
                hashes = self.hashes(out)
                self.assertEqual(1, len(hashes), out)
                self.assertEqual(0, self.backup("--allow", hashes[0])[0])

    def test_both_decodings_stay_scanned_an_allowed_line_does_not_exempt_another_token(self):
        self.leak(("token = " + fake_token() + "\n").encode("utf-16"))
        sha = self.hashes(self.backup()[1])[0]
        self.leak(("token = " + fake_token() + "\nsecond = ghp_" + "Z9y8X7w6V5" * 4 + "\n").encode("utf-16"))
        code, out, _ = self.backup("--allow", sha)
        self.assertEqual(1, code)
        self.assertEqual(1, out.count("REFUSED"), out)


class BundleSafety(BackupBase):
    """Review findings F2, F3 and F9."""

    def test_a_junction_or_symlink_inside_the_bundle_never_leads_outside_it(self):
        self.assertEqual(0, self.backup()[0])
        victim = self.root / "victim"
        (victim / "precious").mkdir(parents=True)
        (victim / "precious" / "thesis.md").write_text("irreplaceable\n", encoding="utf-8")
        import shutil
        shutil.rmtree(self.bundle / "user")
        make_link(self.bundle / "user", victim)
        before = tree_digest(victim)
        code, out, _ = self.backup()
        self.assertEqual(1, code, out)
        self.assertIn("REFUSED", out)
        self.assertEqual(before, tree_digest(victim))
        self.assertTrue((victim / "precious" / "thesis.md").exists())

    def test_a_non_empty_folder_that_is_not_a_bundle_is_refused_and_untouched(self):
        for rel in ("config/app.yaml", "user/notes.md", "memory/old/keep.md", "src/main.py"):
            p = self.bundle / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("mine\n", encoding="utf-8")
        before = tree_digest(self.bundle)
        for apply in (False, True):
            code, out, _ = self.backup(apply=apply)
            self.assertEqual(1, code, out)
            self.assertIn("MANIFEST.json", out)
            self.assertEqual(before, tree_digest(self.bundle))

    def test_an_existing_empty_folder_is_a_fine_bundle(self):
        self.bundle.mkdir()
        self.assertEqual(0, self.backup()[0])

    def test_a_bundle_path_that_is_a_file_is_refused(self):
        self.bundle.write_text("not a folder\n", encoding="utf-8")
        self.assertEqual(1, self.backup()[0])

    def test_a_token_in_a_file_name_is_refused_and_not_echoed(self):
        name = fake_token() + ".md"
        (self.claude / "projects" / "-some-project" / "memory" / name).write_text("harmless\n", encoding="utf-8")
        code, out, _ = self.backup()
        self.assertEqual(1, code)
        self.assertIn("REFUSED", out)
        self.assertNotIn(fake_token(), out)
        self.assertFalse(self.bundle.exists())


if __name__ == "__main__":
    unittest.main()
