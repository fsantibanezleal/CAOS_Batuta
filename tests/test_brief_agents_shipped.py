"""brief new accepts every agent the plugin ships, read from plugins/batuta/agents/ (integration fix of unit U9a)."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import TempCase  # noqa: E402

from batuta_lib import delegation  # noqa: E402

AGENTS_DIR = Path(__file__).resolve().parents[1] / "plugins" / "batuta" / "agents"
SHIPPED = sorted(p.stem for p in AGENTS_DIR.glob("*.md"))


def file_model(name):
    return re.search(r"^model: (\S+)$", (AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8"), re.M).group(1)


class ShippedAgents(TempCase):
    def test_the_agent_choices_are_the_shipped_files_plus_general_purpose(self):
        self.assertEqual(sorted(delegation.AGENTS), sorted(SHIPPED + ["general-purpose"]))
        self.assertIn("adversary", SHIPPED)
        self.assertIn("test-author", SHIPPED)

    def test_every_shipped_agent_gets_its_own_model_in_the_brief(self):
        for agent in SHIPPED:
            text = self.new_brief(f"t-{agent}", agent).read_text(encoding="utf-8")
            self.assertIn(f"- agent: {agent}\n", text)
            self.assertIn(f"- model: {file_model(agent)} (", text)

    def test_default_kinds_of_the_two_roles_the_workaround_covered(self):
        text = self.new_brief("t-ta", "test-author").read_text(encoding="utf-8")
        self.assertIn("- kind: implement\n", text)
        text = self.new_brief("t-adv", "adversary").read_text(encoding="utf-8")
        self.assertIn("- kind: review\n", text)

    def test_the_brief_skill_names_the_real_agents(self):
        skill = (AGENTS_DIR.parent / "skills" / "brief" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("--agent test-author", skill)
        self.assertIn("--agent adversary", skill)
        self.assertNotIn("--agent reviewer --model sonnet", skill)


if __name__ == "__main__":
    unittest.main()
