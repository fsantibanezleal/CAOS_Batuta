"""The doctor skill runs `init doctor` first and keeps its other checks."""
import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "plugins" / "batuta" / "skills" / "doctor" / "SKILL.md"


class DoctorSkill(unittest.TestCase):
    def test_the_first_step_is_init_doctor_for_the_plugin_channel_and_the_other_checks_stay(self):
        text = SKILL.read_text(encoding="utf-8")
        steps = re.findall(r"(?m)^(\d+)\. .*?(?=^\d+\. |\Z)", text, re.S)
        first = text[text.index("\n1. "):text.index("\n2. ")]
        self.assertIn('batuta.py" init doctor --channel plugin', first)
        for command in ("device check", "route check", "contract lint", "preflight limits", "guard automation --explain"):
            self.assertIn(f'batuta.py" {command}', text, command)
        self.assertTrue(steps)


if __name__ == "__main__":
    unittest.main()
