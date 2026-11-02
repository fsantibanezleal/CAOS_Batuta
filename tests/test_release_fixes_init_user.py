"""Release review fix F-14: `init user --apply` says what it did with the user core instead of a false WARN."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import World  # noqa: E402

from batuta_lib.areas import init as init_area  # noqa: E402


class UserCoreMessage(World):
    def test_the_default_core_is_reported_as_rendered_with_how_to_change_it(self):
        code, out, err = self.init_user()
        self.assertTrue((self.home / ".claude" / "CLAUDE.md").is_file(), out + err)
        self.assertNotIn("user core skipped", out + err)
        self.assertRegex(out, r"OK user core rendered from the default template templates/user/CLAUDE\.template\.md")
        self.assertIn("user_core.template", out)

    def test_the_exit_code_does_not_come_from_a_false_user_core_warning(self):
        code, out, err = self.init_user()
        warns = [line for line in out.splitlines() if line.startswith("WARN")]
        self.assertFalse([w for w in warns if "user core" in w], warns)
        self.assertEqual(code, 2 if warns else 0, out + err)

    def test_a_configuration_without_a_user_core_says_nothing_was_rendered(self):
        doc = init_area.user_config_doc(init_area._user_variables({}))
        doc.pop("user_core")
        cfg = self.root / "no-core.json"
        cfg.write_text(json.dumps(doc), encoding="utf-8")
        code, out, err = self.cli("--config", str(cfg), "init", "user", "--home", str(self.home), "--apply")
        self.assertFalse((self.home / ".claude" / "CLAUDE.md").exists(), out + err)
        self.assertRegex(out, r"(SKIP|OK) user core: nothing rendered")
        self.assertNotIn("user core skipped", out)
        self.assertIn("user_core.template", out)


if __name__ == "__main__":
    unittest.main()
