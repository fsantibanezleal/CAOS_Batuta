"""A manifest committed with a project is untrusted input: `Manifest.load` refuses a base that leaves the project or the
Batuta home it was installed into, and `init uninstall` refuses the whole manifest, deleting nothing, for a base, a path or
a link that points elsewhere (the sibling-folder case of the adversary check)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_device_support import make_link  # noqa: E402
from test_init_support import World, make_repo, sha, snapshot  # noqa: E402

from batuta_lib import install_manifest as im  # noqa: E402


def write_manifest(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


class LoadRefusesForeignBases(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.path = self.root / "proj" / ".batuta" / "installed.json"

    def doc(self, bases, kind="project"):
        return {"manifest_version": 1, "kind": kind, "bases": bases, "variables": {}, "files": [], "dirs": []}

    def test_a_project_manifest_accepts_the_project_and_an_ancestor_anchor(self):
        for bases in ({"project": "."}, {"project": ".", "anchor": ".."}, {"project": ".", "anchor": "../.."},
                      {"project": ".", "anchor": "."}):
            write_manifest(self.path, self.doc(bases))
            self.assertIsNotNone(im.Manifest.load(self.path), bases)

    def test_a_project_manifest_refuses_every_base_that_is_not_the_project_or_an_ancestor(self):
        hostile = ({"project": ".", "evil": "../victim"}, {"project": "../victim"}, {"project": ".", "anchor": "../victim"},
                   {"project": ".", "anchor": "sub"}, {"project": str(self.root)}, {"project": ".", "anchor": str(self.root)},
                   {"project": ".", "anchor": "C:/elsewhere"}, {"project": ".", "anchor": "a/../.."})
        for bases in hostile:
            write_manifest(self.path, self.doc(bases))
            with self.assertRaises(im.ManifestError, msg=str(bases)):
                im.Manifest.load(self.path)

    def test_a_user_manifest_must_name_the_deploy_root_it_sits_in_and_the_expected_claude_folder(self):
        deploy, claude = self.root / "bh", self.root / "home" / ".claude"
        path = deploy / "installed.json"
        write_manifest(path, self.doc({"deploy": deploy.as_posix(), "claude": claude.as_posix()}, "user"))
        self.assertIsNotNone(im.Manifest.load(path, expect={"deploy": deploy, "claude": claude}))
        for bases in ({"deploy": (self.root / "other").as_posix(), "claude": claude.as_posix()},
                      {"deploy": deploy.as_posix(), "claude": (self.root / "victim").as_posix()},
                      {"deploy": deploy.as_posix(), "claude": "../victim"},
                      {"deploy": deploy.as_posix(), "claude": claude.as_posix(), "evil": (self.root / "victim").as_posix()}):
            write_manifest(path, self.doc(bases, "user"))
            with self.assertRaises(im.ManifestError, msg=str(bases)):
                im.Manifest.load(path, expect={"deploy": deploy, "claude": claude})


class AnchorIsForFoldersOnTheProjectsOwnPath(unittest.TestCase):
    """The anchor (the nearest folder that existed when a nested project was created) holds only folders, and only folders on
    the project's own path or inside it; `..` with a sibling folder is the reviewer's variant E."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.path = self.root / "outer" / "sub dir" / "app" / ".batuta" / "installed.json"

    def write(self, anchor, files=(), dirs=()):
        write_manifest(self.path, {"manifest_version": 1, "kind": "project", "bases": {"project": ".", "anchor": anchor},
                                   "variables": {}, "files": [{"base": b, "path": p, "sha256": "0" * 64, "backup": None}
                                                              for b, p in files],
                                   "dirs": [{"base": "anchor", "path": d} for d in dirs]})

    def test_the_folders_a_nested_install_created_load(self):
        self.write("../..", dirs=[".", "sub dir", "sub dir/app", "sub dir/app/.batuta", "sub dir/app/specs/000-foundation"])
        self.assertIsNotNone(im.Manifest.load(self.path))

    def test_a_sibling_folder_under_a_dotdot_anchor_is_refused(self):
        for anchor, dirs in ((".." , ["victim/sub", "victim"]), ("../..", ["victim"]), ("..", ["../victim"]),
                             ("../..", ["sub dir/other"]), ("..", ["app2"])):
            self.write(anchor, dirs=dirs)
            with self.assertRaises(im.ManifestError, msg=f"{anchor} {dirs}"):
                im.Manifest.load(self.path)

    def test_a_file_entry_on_the_anchor_is_refused(self):
        self.write("../..", files=[("anchor", "sub dir/app/AGENTS.md")])
        with self.assertRaises(im.ManifestError):
            im.Manifest.load(self.path)


class UninstallRefusesTheWholeManifest(World):
    def setUp(self):
        super().setUp()
        make_repo(self.project)
        self.init_project()
        self.victim = self.root / "victim"
        (self.victim / "sub" / "__pycache__").mkdir(parents=True)
        (self.victim / "v.txt").write_text("precious\n", encoding="utf-8")
        (self.victim / "sub" / "__pycache__" / "x.pyc").write_bytes(b"x")
        self.manifest_path = self.project / ".batuta" / "installed.json"

    def tamper(self, change):
        doc = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        change(doc)
        self.manifest_path.write_text(json.dumps(doc), encoding="utf-8")

    def uninstall(self):
        before_project, before_victim = snapshot(self.project), snapshot(self.victim)
        code, out, _ = self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"REFUSED .*installed\.json")
        self.assertEqual(snapshot(self.project), before_project, "nothing of the project is deleted")
        self.assertEqual(snapshot(self.victim), before_victim, "nothing outside the project is deleted")

    def test_a_sibling_folder_base_with_a_matching_hash_deletes_nothing(self):
        def change(doc):
            doc["bases"]["evil"] = "../victim"
            doc["files"].append({"base": "evil", "path": "v.txt", "sha256": sha(b"precious\n"), "backup": None, "previous": []})
            doc["dirs"].append({"base": "evil", "path": "."})
        self.tamper(change)
        self.uninstall()

    def test_variant_e_a_dotdot_anchor_with_a_sibling_folder_and_a_file_deletes_nothing(self):
        def change(doc):
            doc["bases"]["anchor"] = ".."
            doc["dirs"].append({"base": "anchor", "path": "victim/sub"})
            doc["files"].append({"base": "anchor", "path": "victim/v.txt", "sha256": sha(b"precious\n"), "backup": None,
                                 "previous": []})
        self.tamper(change)
        self.uninstall()

    def test_variant_e_with_a_folder_entry_only(self):
        def change(doc):
            doc["bases"]["anchor"] = ".."
            doc["dirs"].append({"base": "anchor", "path": "victim/sub"})
        self.tamper(change)
        self.uninstall()

    def test_an_absolute_anchor_is_refused(self):
        def change(doc):
            doc["bases"]["anchor"] = self.victim.as_posix()
            doc["dirs"].append({"base": "anchor", "path": "sub"})
        self.tamper(change)
        self.uninstall()

    def test_a_recorded_folder_that_is_now_a_link_leaving_the_project_is_refused(self):
        entry = None
        doc = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        entry = next(e for e in doc["files"] if e["path"] == "tests/__init__.py")
        (self.victim / "tests").mkdir()
        (self.victim / "tests" / "__init__.py").write_bytes((self.project / "tests" / "__init__.py").read_bytes())
        for p in sorted((self.project / "tests").rglob("*"), reverse=True):
            p.unlink()
        (self.project / "tests").rmdir()
        make_link(self.project / "tests", self.victim / "tests")
        self.assertEqual(entry["sha256"], sha(b""))
        before = snapshot(self.victim)
        code, out, _ = self.cli("init", "uninstall", "--target", str(self.project), "--apply")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"REFUSED")
        self.assertEqual(snapshot(self.victim), before)
        self.assertTrue((self.project / "AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()
