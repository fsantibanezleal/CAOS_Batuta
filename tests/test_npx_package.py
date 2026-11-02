"""`package.json` `files` ships everything the npx entry needs: the entry, the plugin folder (scripts, contracts, agents,
templates, skills, manifest), `copier.yml`, VERSION and LICENSE. Checked with `npm pack --dry-run --json` when npm is
present, else against the `files` entries and the tree."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEEDED = [
    "bin/batuta.mjs",
    "plugins/batuta/scripts/batuta.py",
    "plugins/batuta/scripts/hook.py",
    "plugins/batuta/scripts/batuta_lib/areas/init.py",
    "plugins/batuta/contracts/C01-batuta-config.schema.json",
    "plugins/batuta/agents/implementer.md",
    "plugins/batuta/templates/project/AGENTS.md",
    "plugins/batuta/templates/project/.github/workflows/batuta-gates.yml",
    "plugins/batuta/templates/presets/base.json",
    "plugins/batuta/templates/user/CLAUDE.template.md",
    "plugins/batuta/templates/spec/spec.md",
    "plugins/batuta/templates/gates/status.md",
    "plugins/batuta/templates/brief.md",
    "copier.yml",
    "VERSION",
    "LICENSE",
]


def covered(entry, path):
    entry = entry.strip("/")
    return path == entry or path.startswith(entry + "/")


class PackageFiles(unittest.TestCase):
    def setUp(self):
        self.files = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["files"]

    def test_every_needed_file_exists_in_the_tree(self):
        for rel in NEEDED:
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_files_entries_cover_every_needed_path(self):
        for rel in NEEDED:
            self.assertTrue(any(covered(e, rel) for e in self.files), f"{rel} is not covered by package.json files {self.files}")

    def test_the_plugin_folder_ships_whole_so_skills_and_the_manifest_come_with_it(self):
        self.assertIn("plugins/batuta", [e.strip("/") for e in self.files])

    def test_npm_pack_lists_every_needed_file(self):
        npm = shutil.which("npm")
        if npm is None:
            self.skipTest("npm is not installed; the files entries were checked against the tree above")
        with tempfile.TemporaryDirectory() as cache:
            done = subprocess.run([npm, "pack", "--dry-run", "--json", "--ignore-scripts", "--cache", cache],
                                  cwd=ROOT, capture_output=True, text=True, timeout=240)
        self.assertEqual(done.returncode, 0, done.stderr)
        listed = {f["path"].replace("\\", "/") for f in json.loads(done.stdout)[0]["files"]}
        for rel in NEEDED:
            self.assertIn(rel, listed, f"npm pack leaves out {rel}")


if __name__ == "__main__":
    unittest.main()
