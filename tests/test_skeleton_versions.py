"""VERSION, package.json and plugin.json agree (display form vs semver form, ADR-0068)."""
import json
import re
import unittest

from _support import ROOT, display_to_semver


class VersionTests(unittest.TestCase):
    def test_version_file_is_display_form(self):
        text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(text, r"^\d+\.\d{2}\.\d{3}$")
        self.assertEqual(text, "0.01.000")

    def test_package_json_holds_semver_form(self):
        display = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["version"], display_to_semver(display))
        self.assertEqual(pkg["version"], "0.1.0")

    def test_plugin_json_holds_semver_form(self):
        display = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        plugin = json.loads(
            (ROOT / "plugins/batuta/.claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(plugin["version"], display_to_semver(display))

    def test_marketplace_entry_does_not_duplicate_the_version(self):
        market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        for entry in market["plugins"]:
            self.assertNotIn("version", entry, "version lives in plugin.json only")

    def test_changelog_has_unreleased_and_keep_a_changelog_reference(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]", text)
        self.assertIn("keepachangelog.com", text)
        self.assertRegex(text, re.compile(r"^### Added", re.M))


if __name__ == "__main__":
    unittest.main()
