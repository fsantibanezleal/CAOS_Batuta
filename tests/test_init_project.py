"""`init project`: dry run by default, the rendered files, the install manifest, an existing CLAUDE.md or settings.json
(backed up with a stamp, settings merged append-only), a second run (all SAME), a path with spaces, a project inside
another repository, no git, and Windows line endings in existing files."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import FIXTURE_VARS, VAR_ARGS, World, commit_all, make_repo, sha, snapshot  # noqa: E402

from batuta_lib import install_manifest as im  # noqa: E402
from batuta_lib.areas import init  # noqa: E402


def tags(out):
    return [line.split(" ", 1)[0] for line in out.splitlines() if line.split(" ", 1)[0].isupper()]


class DryRun(World):
    def test_dry_run_writes_nothing_and_lists_every_file_as_new(self):
        code, out, err = self.init_project(apply=False)
        self.assertEqual(code, 2, out + err)   # no git in the target: a WARN, shown in a dry run too
        self.assertFalse(self.project.exists(), "a dry run creates not even the target folder")
        for rel in init.render_project(dict(FIXTURE_VARS)):
            self.assertRegex(out, rf"NEW {rel.replace('.', r'[.]')}\b")
        self.assertIn("dry run", out)

    def test_dry_run_of_a_project_with_files_reports_same_and_changed(self):
        self.init_project()
        (self.project / "AGENTS.md").write_text("mine\n", encoding="utf-8")
        before = snapshot(self.project)
        code, out, _ = self.init_project(apply=False)
        self.assertIn("CHANGED AGENTS.md", out)
        self.assertIn("SAME CLAUDE.md", out)
        self.assertEqual(snapshot(self.project), before)


class Apply(World):
    def test_apply_writes_the_template_with_the_variables_and_a_manifest(self):
        code, out, err = self.init_project()
        self.assertEqual(code, 2, out + err)   # no git in the target: a WARN, exit 2
        for rel, text in init.render_project(dict(FIXTURE_VARS)).items():
            self.assertEqual((self.project / rel).read_text(encoding="utf-8"), text, rel)
        manifest = im.Manifest.load(self.project / ".batuta" / "installed.json")
        self.assertEqual(manifest.kind, "project")
        paths = {e["path"] for e in manifest.files}
        self.assertTrue(set(init.render_project(dict(FIXTURE_VARS))) <= paths)
        for e in manifest.files:
            self.assertEqual(e["sha256"], im.sha256_bytes((self.project / e["path"]).read_bytes()), e["path"])

    def test_the_manifest_of_a_project_holds_no_machine_path(self):
        make_repo(self.project)
        self.init_project()
        text = (self.project / ".batuta" / "installed.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.root), text)
        self.assertNotIn(self.root.as_posix(), text)
        self.assertNotRegex(text, r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/Users/|/home/")
        commit_all(self.project, "init")
        code, out, err = self.cli("leaks", "scan", "--root", str(self.project))
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("installed.json", out)

    def test_no_git_warns_and_still_writes_the_ci_file(self):
        code, out, _ = self.init_project()
        self.assertIn("WARN", out)
        self.assertRegex(out, r"(?i)no git repository")
        self.assertTrue((self.project / ".github/workflows/batuta-gates.yml").is_file())

    def test_a_git_repository_gives_no_warning(self):
        make_repo(self.project)
        code, out, err = self.init_project()
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("WARN", out)

    def test_a_project_inside_another_repository_warns_that_github_reads_the_root_only(self):
        outer = make_repo(self.root / "outer")
        code, out, _ = self.init_project(target=outer / "sub dir" / "app")
        self.assertEqual(code, 2)
        self.assertRegex(out, r"(?i)inside the repository")
        self.assertTrue((outer / "sub dir" / "app" / ".github/workflows/batuta-gates.yml").is_file())

    def test_second_run_is_all_same_and_changes_nothing(self):
        make_repo(self.project)
        self.init_project()
        before = snapshot(self.project)
        code, out, err = self.init_project()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(snapshot(self.project), before)
        self.assertEqual(set(tags(out)) - {"SAME", "OK", "SKIP"}, set(), out)
        self.assertNotIn("backup", out)

    def test_default_variables_come_from_the_target_folder(self):
        code, out, _ = self.cli("init", "project", "--target", str(self.project), "--apply")
        self.assertIn(code, (0, 2), out)
        text = (self.project / ".batuta" / "batuta.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(text)["tdd"]["test_command"], init.DEFAULTS["test_command"])
        self.assertIn("my project", (self.project / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertRegex((self.project / ".github/workflows/batuta-gates.yml").read_text(encoding="utf-8"),
                         r"group: batuta-gates-my-project")

    def test_a_bad_variable_is_refused_with_nothing_written(self):
        code, out, err = self.cli("init", "project", "--target", str(self.project), "--var", "project_slug=Bad Slug",
                                  "--apply")
        self.assertEqual(code, 1)
        self.assertIn("project_slug", out + err)
        self.assertFalse(self.project.exists())
        code, out, err = self.cli("init", "project", "--target", str(self.project), "--var", "nope=1", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("nope", out + err)

    def test_json_output_is_the_c20_object(self):
        code, out, _ = self.cli("init", "project", "--target", str(self.project), *VAR_ARGS, "--json")
        doc = json.loads(out)
        self.assertEqual((doc["tool"], doc["area"], doc["verb"]), ("batuta", "init", "project"))
        self.assertTrue(any(i["tag"] == "NEW" for i in doc["items"]))

    def test_a_file_that_is_a_symlink_or_a_folder_in_the_way_is_refused(self):
        self.project.mkdir()
        (self.project / "AGENTS.md").mkdir()
        code, out, _ = self.init_project()
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED .*AGENTS\.md")
        self.assertFalse((self.project / "CLAUDE.md").exists(), "a refusal writes nothing")


class ExistingFiles(World):
    def test_an_existing_claude_md_is_backed_up_with_a_stamp_before_it_is_replaced(self):
        self.project.mkdir()
        mine = "# My own rules\n\nKeep tabs.\n"
        (self.project / "CLAUDE.md").write_text(mine, encoding="utf-8")
        code, out, _ = self.init_project()
        self.assertIn("CHANGED CLAUDE.md", out)
        backups = sorted(self.project.glob("CLAUDE.md.bak-*"))
        self.assertEqual(len(backups), 1, out)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), mine)
        self.assertRegex(backups[0].name, r"^CLAUDE\.md\.bak-\d{8}-\d{6}(-\d+)?$")
        manifest = im.Manifest.load(self.project / ".batuta" / "installed.json")
        entry = next(e for e in manifest.files if e["path"] == "CLAUDE.md")
        self.assertEqual(entry["backup"], backups[0].name)

    def test_existing_settings_are_merged_append_only_and_backed_up(self):
        (self.project / ".claude").mkdir(parents=True)
        mine = {"permissions": {"deny": ["Bash(rm:*)"], "allow": ["Read"]}, "model": "opus"}
        path = self.project / ".claude" / "settings.json"
        path.write_text(json.dumps(mine, indent=2) + "\n", encoding="utf-8")
        code, out, err = self.init_project()
        merged = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(merged["model"], "opus")
        self.assertEqual(merged["permissions"]["allow"], ["Read"])
        self.assertEqual(merged["permissions"]["deny"][0], "Bash(rm:*)")
        self.assertGreater(len(merged["permissions"]["deny"]), 1)
        self.assertEqual(len(list((self.project / ".claude").glob("settings.json.bak-*"))), 1)
        self.assertRegex(out, r"MERGED|NEW settings\.json")
        before = path.read_bytes()
        code, out, _ = self.init_project()
        self.assertEqual(path.read_bytes(), before, "a second merge changes nothing")
        self.assertEqual(len(list((self.project / ".claude").glob("settings.json.bak-*"))), 1)

    def test_settings_that_are_not_json_are_refused_and_nothing_is_written(self):
        (self.project / ".claude").mkdir(parents=True)
        (self.project / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
        code, out, _ = self.init_project()
        self.assertEqual(code, 1)
        self.assertRegex(out, r"(FAIL|REFUSED) .*settings")
        self.assertFalse((self.project / "AGENTS.md").exists())

    def test_crlf_files_equal_to_the_rendering_count_as_same(self):
        self.init_project()
        for rel in ("AGENTS.md", "CLAUDE.md"):
            p = self.project / rel
            p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        code, out, _ = self.init_project()
        self.assertNotIn("CHANGED", out)
        self.assertEqual(len(list(self.project.glob("*.bak-*"))), 0)
        manifest = im.Manifest.load(self.project / ".batuta" / "installed.json")
        self.assertEqual(manifest.state(self.project, "AGENTS.md"), "SAME")

    def test_crlf_settings_are_merged_and_the_original_is_kept_byte_for_byte(self):
        (self.project / ".claude").mkdir(parents=True)
        original = b'{\r\n  "model": "opus"\r\n}\r\n'
        (self.project / ".claude" / "settings.json").write_bytes(original)
        self.init_project()
        backups = list((self.project / ".claude").glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)

    def test_files_the_template_does_not_own_are_never_touched(self):
        self.project.mkdir()
        (self.project / "README.md").write_text("mine\n", encoding="utf-8")
        (self.project / "src").mkdir()
        (self.project / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        before = snapshot(self.project)
        self.init_project()
        after = snapshot(self.project)
        for rel, data in before.items():
            self.assertEqual(after[rel], data, rel)


if __name__ == "__main__":
    unittest.main()
