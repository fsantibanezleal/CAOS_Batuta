"""The plugin and marketplace manifests parse and carry the documented fields only."""
import json
import unittest

from _support import ROOT

PLUGIN_FIELDS = {
    "name", "version", "description", "author", "homepage", "repository", "license", "keywords",
}
HOMEPAGE = "https://github.com/fsantibanezleal/CAOS_Batuta"
RESERVED_PREFIXES = ("claude-", "anthropic-", "cc-plugin-")


class PluginManifestTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "plugins/batuta/.claude-plugin/plugin.json"
        self.data = json.loads(path.read_text(encoding="utf-8"))

    def test_required_fields(self):
        for key in ("name", "version", "description", "author", "homepage", "license"):
            self.assertIn(key, self.data)
        self.assertEqual(self.data["name"], "batuta")
        self.assertEqual(self.data["homepage"], HOMEPAGE)
        self.assertEqual(self.data["license"], "Apache-2.0")
        self.assertIn("name", self.data["author"])

    def test_only_documented_fields(self):
        self.assertLessEqual(set(self.data), PLUGIN_FIELDS)

    def test_name_is_not_reserved(self):
        self.assertFalse(self.data["name"].startswith(RESERVED_PREFIXES))
        self.assertRegex(self.data["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")


class MarketplaceManifestTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))

    def test_required_fields(self):
        for key in ("name", "owner", "plugins"):
            self.assertIn(key, self.data)
        self.assertIn("name", self.data["owner"])
        self.assertRegex(self.data["name"], r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
        self.assertFalse(self.data["name"].startswith(RESERVED_PREFIXES))

    def test_lists_plugin_batuta_at_relative_path(self):
        entries = {e["name"]: e for e in self.data["plugins"]}
        self.assertIn("batuta", entries)
        self.assertEqual(entries["batuta"]["source"], "./plugins/batuta")

    def test_entry_name_equals_plugin_manifest_name(self):
        plugin = json.loads(
            (ROOT / "plugins/batuta/.claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        self.assertIn(plugin["name"], [e["name"] for e in self.data["plugins"]])

    def test_source_directory_exists(self):
        for entry in self.data["plugins"]:
            self.assertTrue((ROOT / entry["source"]).is_dir())


class PackageJsonTests(unittest.TestCase):
    def setUp(self):
        self.pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    def test_npx_entry(self):
        self.assertEqual(self.pkg["bin"], {"batuta": "bin/batuta.mjs"})
        self.assertEqual(self.pkg["type"], "module")
        self.assertEqual(self.pkg["engines"], {"node": ">=18"})
        self.assertEqual(self.pkg["license"], "Apache-2.0")

    def test_files_limited_to_what_the_cli_needs(self):
        files = self.pkg["files"]
        self.assertIn("bin", files)
        self.assertIn("VERSION", files)
        for entry in files:
            self.assertFalse(entry.startswith(("tests", "docs", ".github")), entry)
            self.assertTrue((ROOT / entry).exists(), entry)

    def test_no_dependencies(self):
        self.assertNotIn("dependencies", self.pkg)
        self.assertNotIn("devDependencies", self.pkg)


if __name__ == "__main__":
    unittest.main()
