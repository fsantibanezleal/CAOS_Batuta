"""route: the role table from C01 and the agent-file check against C18 and the roles (unit U2, D1 and D4)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import CONTRACTS, PLUGIN, TempCase, run, run_json, write_config  # noqa: E402

AGENTS = PLUGIN / "agents"
EXPECTED = {  # agent -> (model, effort, omitClaudeMd)
    "searcher": ("haiku", "low", True),
    "runner": ("haiku", "low", True),
    "implementer": ("sonnet", "medium", None),
    "doc-writer": ("sonnet", "medium", None),
    "reviewer": ("opus", "high", None),
}


def agent_file(name, model, extra="", hooks=False):
    text = f"---\nname: {name}\ndescription: A test agent.\nmodel: {model}\neffort: low\n{extra}"
    if hooks:
        text += "hooks:\n  Stop: []\n"
    return text + "---\n\nBody.\n"


class RouteShow(TempCase):
    def test_prints_the_role_table_of_the_defaults_with_a_warn_line_on_stderr(self):
        code, out, err = run("route", "show", "--root", self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("searcher", out)
        self.assertRegex(out, r"searcher.*haiku.*low.*true")
        self.assertRegex(out, r"reviewer.*opus.*high")
        self.assertIn("WARN", err)  # no configuration file: the defaults, announced

    def test_json_is_the_c20_object_and_lists_every_role(self):
        code, data, _ = run_json("route", "show", "--root", self.root)
        self.assertEqual((code, data["tool"], data["area"], data["verb"]), (0, "batuta", "route", "show"))
        text = json.dumps(data)
        for role in ("searcher", "runner", "implementer", "doc-writer", "reviewer"):
            self.assertIn(role, text)

    def test_reads_the_roles_from_a_configuration_file(self):
        write_config(self.root, roles={"implementer": {"model": "opus", "effort": "high"}})
        code, out, err = run("route", "show", "--root", self.root)
        self.assertEqual(code, 0, (out, err))
        self.assertRegex(out, r"implementer.*opus.*high")
        self.assertNotIn("WARN", err)

    def test_an_invalid_configuration_is_a_failure(self):
        cfg = self.root / ".batuta"
        cfg.mkdir()
        (cfg / "batuta.json").write_text("{not json", encoding="utf-8")
        code, out, err = run("route", "show", "--root", self.root)
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out + err)


class RouteCheck(TempCase):
    def agents_dir(self, **files):
        d = self.root / "agents"
        d.mkdir(exist_ok=True)
        for name, text in files.items():
            (d / f"{name}.md").write_text(text, encoding="utf-8")
        return d

    def check(self, d):
        return run("route", "check", "--root", self.root, "--agents-dir", d)

    def test_the_shipped_agents_pass(self):
        code, out, err = run("route", "check", "--root", self.root)
        self.assertEqual(code, 0, (out, err))
        self.assertNotIn("FAIL", out)

    def test_every_shipped_agent_conforms_to_c18_and_the_spec(self):
        from batuta_lib import contract
        schema = contract.find_schema(CONTRACTS, "C18")
        for name, (model, effort, omit) in EXPECTED.items():
            path = AGENTS / f"{name}.md"
            self.assertTrue(path.is_file(), name)
            self.assertEqual(contract.validate_file(path, schema), [], name)
            text = path.read_text(encoding="utf-8")
            head = text.split("---")[1]
            self.assertIn(f"name: {name}\n", head)
            self.assertIn(f"model: {model}\n", head)
            self.assertIn(f"effort: {effort}\n", head)
            self.assertNotIn("hooks:", head, name)
            self.assertEqual("omitClaudeMd: true" in head, bool(omit), name)
            self.assertIn("BRIEF: <absolute brief path>", text, name)  # the shared delegation contract text

    def test_a_model_that_differs_from_its_role_is_reported(self):
        d = self.agents_dir(implementer=agent_file("implementer", "opus"))
        code, out, _ = self.check(d)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL.*implementer.*model.*opus.*sonnet")

    def test_a_haiku_role_without_omit_claude_md_is_reported(self):
        d = self.agents_dir(searcher=agent_file("searcher", "haiku"))
        code, out, _ = self.check(d)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL.*searcher.*omitClaudeMd")

    def test_a_haiku_role_with_omit_claude_md_false_is_reported(self):
        d = self.agents_dir(runner=agent_file("runner", "haiku", "omitClaudeMd: false\n"))
        code, out, _ = self.check(d)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL.*runner.*omitClaudeMd")

    def test_a_hooks_key_is_refused_by_c18(self):
        d = self.agents_dir(reviewer=agent_file("reviewer", "opus", hooks=True))
        code, out, _ = self.check(d)
        self.assertEqual(code, 1)
        self.assertIn("hooks", out)

    def test_a_name_that_differs_from_the_file_stem_is_reported(self):
        d = self.agents_dir(reviewer=agent_file("other", "opus"))
        code, out, _ = self.check(d)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL.*name")

    def test_an_agent_without_a_role_is_a_warning(self):
        d = self.agents_dir(**{"stranger": agent_file("stranger", "sonnet")})
        code, out, _ = self.check(d)
        self.assertEqual(code, 2)
        self.assertRegex(out, r"WARN.*stranger.*role")

    def test_a_missing_front_matter_is_reported(self):
        d = self.agents_dir(reviewer="no front matter\n")
        code, out, _ = self.check(d)
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_a_missing_agents_folder_is_reported(self):
        code, out, _ = self.check(self.root / "nope")
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_the_role_model_comes_from_the_configuration(self):
        write_config(self.root, roles={"implementer": {"model": "opus", "effort": "high"}})
        d = self.agents_dir(implementer=agent_file("implementer", "opus"))
        self.assertEqual(self.check(d)[0], 0)
        d2 = self.agents_dir(implementer=agent_file("implementer", "sonnet"))
        self.assertEqual(self.check(d2)[0], 1)


if __name__ == "__main__":
    unittest.main()
