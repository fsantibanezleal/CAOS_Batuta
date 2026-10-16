"""`uninstall` and `update` for both scopes: dry run by default; uninstall restores backups and removes only files whose
hash is unchanged (an edited file is DIFFERENT and kept); update re-renders from the current templates, backing up
what it changes."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import FIXTURE_VARS, TEMPLATE_DIR, World, commit_all, make_repo, snapshot  # noqa: E402

from batuta_lib import install_manifest as im  # noqa: E402
from batuta_lib.areas import init  # noqa: E402


class ProjectUninstall(World):
    def prepare(self):
        """A scratch git repository with a CLAUDE.md and settings of its own; returns its snapshot."""
        make_repo(self.project)
        (self.project / "CLAUDE.md").write_text("# Mine\r\n\r\nCRLF kept.\r\n", encoding="utf-8", newline="")
        (self.project / "README.md").write_text("readme\n", encoding="utf-8")
        (self.project / ".claude").mkdir()
        (self.project / ".claude" / "settings.json").write_bytes(b'{\r\n  "model": "opus"\r\n}\r\n')
        commit_all(self.project, "start")
        return snapshot(self.project)

    def test_uninstall_leaves_the_project_as_it_was_byte_for_byte(self):
        before = self.prepare()
        self.init_project()
        self.assertNotEqual(snapshot(self.project), before)
        code, out, err = self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(snapshot(self.project), before)

    def test_uninstall_is_a_dry_run_by_default(self):
        self.prepare()
        self.init_project()
        before = snapshot(self.project)
        code, out, _ = self.cli("init", "uninstall", "--target", str(self.project))
        self.assertEqual(code, 0)
        self.assertEqual(snapshot(self.project), before)
        self.assertIn("REMOVED AGENTS.md", out)
        self.assertIn("dry run", out)

    def test_an_edited_file_is_kept_and_reported_different(self):
        self.prepare()
        self.init_project()
        agents = self.project / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8") + "\nmy own note\n", encoding="utf-8")
        code, out, _ = self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertEqual(code, 2, out)
        self.assertRegex(out, r"DIFFERENT AGENTS\.md")
        self.assertIn("my own note", agents.read_text(encoding="utf-8"))
        self.assertFalse((self.project / ".github").exists(), "every unchanged file is still removed")
        manifest = im.Manifest.load(self.project / ".batuta" / "installed.json")
        self.assertEqual([e["path"] for e in manifest.files], ["AGENTS.md"], "the manifest keeps what it could not remove")
        code, out, _ = self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertEqual(code, 2)
        self.assertRegex(out, r"DIFFERENT AGENTS\.md")

    def test_changed_settings_are_not_rolled_back(self):
        self.prepare()
        self.init_project()
        path = self.project / ".claude" / "settings.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["permissions"]["allow"] = ["Bash(git status)"]
        path.write_text(json.dumps(doc), encoding="utf-8")
        code, out, _ = self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertRegex(out, r"DIFFERENT \.claude/settings\.json")
        self.assertIn("Bash(git status)", path.read_text(encoding="utf-8"))

    def test_a_file_deleted_by_the_user_is_reported_missing_and_the_rest_is_removed(self):
        self.prepare()
        self.init_project()
        (self.project / "AGENTS.md").unlink()
        code, out, _ = self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertRegex(out, r"MISSING AGENTS\.md")
        self.assertFalse((self.project / "specs").exists())

    def test_without_a_manifest_uninstall_refuses(self):
        self.project.mkdir()
        code, out, _ = self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"(REFUSED|FAIL) .*installed\.json")

    def test_user_files_added_inside_a_folder_init_created_keep_that_folder(self):
        self.prepare()
        self.init_project()
        (self.project / "specs" / "my-notes.md").write_text("mine\n", encoding="utf-8")
        self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertTrue((self.project / "specs" / "my-notes.md").is_file())
        self.assertFalse((self.project / "specs" / "000-foundation").exists())

    def test_a_path_with_spaces_and_a_project_inside_another_repository(self):
        outer = make_repo(self.root / "outer repo")
        target = outer / "sub dir" / "app"
        before = snapshot(outer)
        self.init_project(target=target)
        code, out, _ = self.cli("init", "uninstall", "--target", str(target), "--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(snapshot(outer), before)
        self.assertFalse(target.exists(), "the folders init created are removed with it")


class ProjectUpdate(World):
    def altered_template(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        copy = Path(tmp.name) / "project"
        shutil.copytree(TEMPLATE_DIR, copy)
        agents = copy / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8") + "\nA line added in a newer release.\n", encoding="utf-8")
        return copy

    def test_update_with_nothing_new_is_all_same(self):
        make_repo(self.project)
        self.init_project()
        before = snapshot(self.project)
        code, out, _ = self.cli("init", "update", "--target", str(self.project), "--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(snapshot(self.project), before)

    def test_update_rewrites_from_the_current_template_and_backs_up_what_it_changes(self):
        make_repo(self.project)
        self.init_project()
        with mock.patch.object(init, "template_dir", lambda: self.altered_template()):
            code, out, _ = self.cli("init", "update", "--target", str(self.project), "--apply")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"CHANGED AGENTS\.md")
        self.assertIn("A line added in a newer release.", (self.project / "AGENTS.md").read_text(encoding="utf-8"))
        backups = sorted(self.project.glob("AGENTS.md.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertNotIn("A line added", backups[0].read_text(encoding="utf-8"))
        manifest = im.Manifest.load(self.project / ".batuta" / "installed.json")
        self.assertEqual(manifest.state(self.project, "AGENTS.md"), "SAME")

    def test_update_keeps_a_users_edit_in_a_backup_and_uninstall_still_restores_the_original(self):
        make_repo(self.project)
        (self.project / "AGENTS.md").write_bytes(b"original\n")
        before = snapshot(self.project)
        self.init_project()
        agents = self.project / "AGENTS.md"
        agents.write_text("my edit\n", encoding="utf-8")
        code, out, _ = self.cli("init", "update", "--target", str(self.project), "--apply")
        self.assertRegex(out, r"CHANGED AGENTS\.md")
        kept = [p.read_text(encoding="utf-8") for p in self.project.glob("AGENTS.md.bak-*")]
        self.assertIn("my edit\n", kept)
        code, out, _ = self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertEqual(code, 0, out)
        restored = {k: v for k, v in snapshot(self.project).items() if not k.startswith("AGENTS.md.bak-")}
        self.assertEqual(restored["AGENTS.md"], b"original\n")
        self.assertEqual({k: v for k, v in restored.items() if k in before}, before)

    def test_update_restores_a_deleted_file_and_is_a_dry_run_by_default(self):
        make_repo(self.project)
        self.init_project()
        (self.project / "CLAUDE.md").unlink()
        code, out, _ = self.cli("init", "update", "--target", str(self.project))
        self.assertIn("NEW CLAUDE.md", out)
        self.assertFalse((self.project / "CLAUDE.md").exists())
        self.cli("init", "update", "--target", str(self.project), "--apply")
        self.assertTrue((self.project / "CLAUDE.md").is_file())

    def test_update_without_a_manifest_refuses(self):
        self.project.mkdir()
        code, out, _ = self.cli("init", "update", "--target", str(self.project), "--apply")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
