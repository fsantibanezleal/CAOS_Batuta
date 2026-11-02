"""The plugin manifest and the marketplace listing: official fields, version sync, reserved names, paths."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from _support import ROOT, display_to_semver

PLUGIN = ROOT / "plugins" / "batuta"
PLUGIN_JSON = PLUGIN / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
RESERVED = {
    "claude-code-marketplace", "claude-code-plugins", "claude-plugins-official", "anthropic-marketplace",
    "anthropic-plugins", "agent-skills", "knowledge-work-plugins", "life-sciences",
}
RESERVED_PREFIXES = ("claude", "anthropic")
PATH_KEYS = ("commands", "agents", "skills", "hooks", "mcpServers", "outputStyles", "lspServers")
USER_CONFIG_KEYS = {"type", "title", "description", "default", "required", "sensitive", "multiple", "min", "max"}
REPO_URL = "https://github.com/fsantibanezleal/CAOS_Batuta"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def path_values(manifest):
    for key in PATH_KEYS:
        value = manifest.get(key)
        if isinstance(value, str):
            yield key, value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield key, item


class PluginManifestTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PLUGIN_JSON.is_file(), f"{PLUGIN_JSON} is missing")
        self.manifest = load(PLUGIN_JSON)

    def test_identity(self):
        m = self.manifest
        self.assertEqual(m["name"], "batuta")
        self.assertEqual(m.get("displayName"), "Batuta")
        self.assertRegex(m["name"], KEBAB)

    def test_name_is_not_reserved(self):
        name = self.manifest["name"]
        self.assertNotIn(name, RESERVED)
        self.assertFalse(name.startswith(RESERVED_PREFIXES), name)

    def test_version_is_the_semver_form_of_version_file(self):
        display = (ROOT / "VERSION").read_text(encoding="utf-8")
        self.assertRegex(self.manifest["version"], SEMVER)
        self.assertEqual(self.manifest["version"], display_to_semver(display))

    def test_descriptive_fields(self):
        m = self.manifest
        self.assertTrue(m.get("description", "").strip())
        author = m.get("author")
        self.assertIsInstance(author, dict)
        self.assertTrue(author.get("name", "").strip())
        self.assertEqual(m.get("homepage"), REPO_URL)
        self.assertEqual(m.get("repository"), REPO_URL)
        self.assertEqual(m.get("license"), "Apache-2.0")
        keywords = m.get("keywords")
        self.assertIsInstance(keywords, list)
        self.assertTrue(keywords and all(isinstance(k, str) and k for k in keywords))

    def test_user_config_python_follows_decision_19(self):
        config = self.manifest.get("userConfig")
        self.assertIsInstance(config, dict)
        self.assertEqual(set(config), {"python"})
        option = config["python"]
        self.assertLessEqual(set(option), USER_CONFIG_KEYS)
        for key in ("type", "title", "description"):
            self.assertTrue(str(option.get(key, "")).strip(), key)
        self.assertEqual(option["type"], "string")
        self.assertEqual(option.get("default"), "python3")
        description = option["description"]
        self.assertIn("3.10", description)
        self.assertIn("py", re.findall(r"[A-Za-z.]+", description))
        self.assertIn("python.exe", description)

    def test_component_paths_start_with_dot_slash_and_stay_inside(self):
        for key, value in path_values(self.manifest):
            self.assertTrue(value.startswith("./"), f"{key}: {value}")
            self.assertNotIn("..", Path(value).parts, f"{key}: {value}")
            self.assertTrue((PLUGIN / value).exists(), f"{key}: {value} does not exist")

    def test_no_machine_path_in_the_manifest(self):
        text = PLUGIN_JSON.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]|/home/|/Users/", text))

    def test_only_official_fields(self):
        official = {
            "name", "displayName", "version", "description", "author", "homepage", "repository", "license",
            "keywords", "userConfig", "commands", "agents", "skills", "hooks", "mcpServers", "outputStyles",
            "lspServers", "$schema", "dependencies", "channels", "themes", "monitors",
        }
        self.assertLessEqual(set(self.manifest), official)


class MarketplaceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MARKETPLACE_JSON.is_file())
        self.market = load(MARKETPLACE_JSON)

    def test_marketplace_name_is_valid_and_not_reserved(self):
        name = self.market["name"]
        self.assertRegex(name, KEBAB)
        self.assertNotIn(name, RESERVED)
        self.assertTrue(self.market.get("owner", {}).get("name", "").strip())

    def test_lists_the_plugin_with_a_relative_source(self):
        entries = [p for p in self.market["plugins"] if p["name"] == "batuta"]
        self.assertEqual(len(entries), 1)
        source = entries[0]["source"]
        self.assertEqual(source, "./plugins/batuta")
        self.assertTrue((ROOT / source / ".claude-plugin" / "plugin.json").is_file())

    def test_entry_agrees_with_the_manifest(self):
        entry = [p for p in self.market["plugins"] if p["name"] == "batuta"][0]
        manifest = load(PLUGIN_JSON)
        self.assertEqual(entry["name"], manifest["name"])
        if "version" in entry:
            self.assertEqual(entry["version"], manifest["version"])


class ClaudeValidateTests(unittest.TestCase):
    def test_claude_plugin_validate_strict(self):
        claude = shutil.which("claude")
        if claude is None:
            print("WARN claude CLI not on PATH: `claude plugin validate --strict` skipped")
            self.skipTest("claude CLI not on PATH")
        result = subprocess.run([claude, "plugin", "validate", "--strict", str(PLUGIN)], capture_output=True, text=True,
                                timeout=120, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
