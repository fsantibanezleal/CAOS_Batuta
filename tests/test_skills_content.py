"""The thirteen skills: front matter, sizes, listing budget, and every command and agent they name exists."""
import re
import unittest

from _support import ROOT, load_batuta

PLUGIN = ROOT / "plugins" / "batuta"
SKILLS = PLUGIN / "skills"
AGENTS = PLUGIN / "agents"
NAMES = ["route", "brief", "delegate", "spec", "freeze", "red", "green", "gate", "verify", "promote",
         "context-audit", "doctor", "lessons"]
HUMAN_ONLY = {"freeze", "promote"}
GATES = re.compile(r"\bL(?:[0-9]|10)-[a-z]+\b")
GATE_NAMES = {"L0-understand", "L1-size", "L2-decide", "L3-contracts", "L4-boundaries", "L5-freeze", "L6-skeleton",
              "L7-build", "L8-integrate", "L9-promote", "L10-lessons"}
LISTING_FIELD_CAP = 1536
LISTING_BUDGET = 3000
DESCRIPTION_TARGET = 300
COMMAND_FORM = re.compile(r'python "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/batuta\.py" ([^\n`]*)')
GLOBAL_FLAGS = {"--config", "--json", "--version", "-h", "--help"}


def read_skill(name):
    from batuta_lib import frontmatter
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    meta, body = frontmatter.parse(text)
    return text, meta, body


def cli_parser():
    batuta = load_batuta()
    areas, warnings = batuta.load_areas()
    assert not warnings, warnings
    return batuta.build_parser(areas, "0.0.0")


def sub_choices(parser):
    for action in parser._actions:
        if action.__class__.__name__ == "_SubParsersAction":
            return action.choices
    return None


def resolve(parser, tokens):
    """Walk the sub-command words of a command; return (leaf parser, words consumed) or raise AssertionError."""
    consumed = 0
    while True:
        choices = sub_choices(parser)
        if choices is None:
            return parser, consumed
        word = tokens[consumed] if consumed < len(tokens) else None
        if word is None or word.startswith(("-", "<", "[")):
            if consumed < 2:
                raise AssertionError(f"command needs an area and a verb: {tokens}")
            return parser, consumed
        if word not in choices:
            raise AssertionError(f"'{word}' is not one of {sorted(choices)}")
        parser = choices[word]
        consumed += 1


def commands_in(body):
    for lineno, line in enumerate(body.splitlines(), 1):
        for m in COMMAND_FORM.finditer(line):
            text = m.group(1).split(" #")[0].strip()
            yield lineno, text


class SkillFilesTests(unittest.TestCase):
    def test_exactly_the_thirteen_skills_exist(self):
        found = sorted(p.name for p in SKILLS.iterdir() if p.is_dir()) if SKILLS.is_dir() else []
        self.assertEqual(found, sorted(NAMES))
        for name in NAMES:
            self.assertTrue((SKILLS / name / "SKILL.md").is_file(), name)

    def test_front_matter(self):
        load_batuta()
        for name in NAMES:
            _, meta, _ = read_skill(name)
            self.assertEqual(meta.get("name"), name)
            self.assertTrue(str(meta.get("description", "")).strip(), f"{name}: description")
            self.assertLessEqual(set(meta), {"name", "description", "when_to_use", "disable-model-invocation",
                                             "allowed-tools", "argument-hint"}, name)
            self.assertTrue(str(meta.get("allowed-tools", "")).strip(), f"{name}: allowed-tools")

    def test_only_freeze_and_promote_are_human_started(self):
        load_batuta()
        for name in NAMES:
            _, meta, _ = read_skill(name)
            self.assertEqual(meta.get("disable-model-invocation") is True, name in HUMAN_ONLY, name)

    def test_sizes(self):
        load_batuta()
        for name in NAMES:
            text, meta, _ = read_skill(name)
            self.assertLess(len(text.splitlines()), 500, name)
            listing = len(str(meta["description"])) + len(str(meta.get("when_to_use", "")))
            self.assertLessEqual(listing, LISTING_FIELD_CAP, name)
            self.assertLessEqual(len(str(meta["description"])), DESCRIPTION_TARGET, f"{name}: description over target")

    def test_listing_budget_of_all_thirteen(self):
        load_batuta()
        total = 0
        for name in NAMES:
            _, meta, _ = read_skill(name)
            total += len(name) + len(str(meta["description"])) + len(str(meta.get("when_to_use", "")))
        print(f"skill listing size: {total} characters for {len(NAMES)} skills (budget {LISTING_BUDGET})")
        self.assertLessEqual(total, LISTING_BUDGET)

    def test_description_is_trigger_first(self):
        load_batuta()
        for name in NAMES:
            _, meta, _ = read_skill(name)
            self.assertRegex(str(meta["description"]), r"^(Use|When|After|Before|At|On) ", name)

    def test_procedure_is_at_the_top_in_numbered_steps(self):
        load_batuta()
        for name in NAMES:
            _, _, body = read_skill(name)
            head = "\n".join(body.splitlines()[:25])
            self.assertRegex(head, r"(?m)^1\. ", f"{name}: numbered steps must start in the first 25 lines")

    def test_each_skill_names_a_lifecycle_gate_or_says_it_has_none(self):
        load_batuta()
        for name in NAMES:
            _, _, body = read_skill(name)
            gates = set(GATES.findall(body))
            self.assertLessEqual(gates, GATE_NAMES, f"{name}: unknown gate names {gates - GATE_NAMES}")
            self.assertTrue(gates or "Gate: none" in body, f"{name}: names no gate and has no 'Gate: none' line")

    def test_each_skill_says_what_to_do_on_a_non_zero_exit(self):
        load_batuta()
        for name in NAMES:
            _, _, body = read_skill(name)
            self.assertRegex(body, r"(?i)non-zero|exit (code )?[12]", name)

    def test_no_machine_path_and_no_python3_alias(self):
        load_batuta()
        for name in NAMES:
            text, _, _ = read_skill(name)
            self.assertIsNone(re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]|/home/|/Users/", text), name)
            self.assertNotIn("python3 ", text, name)


class SkillCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = cli_parser()

    def test_every_batuta_command_uses_the_plugin_root_form(self):
        load_batuta()
        for name in NAMES:
            _, _, body = read_skill(name)
            for lineno, line in enumerate(body.splitlines(), 1):
                if "batuta.py" in line and "hook.py" not in line:
                    self.assertRegex(line, COMMAND_FORM, f"{name}:{lineno} writes batuta.py outside the plugin-root form")

    def test_every_named_verb_and_flag_exists_in_the_dispatcher(self):
        load_batuta()
        seen = 0
        for name in NAMES:
            _, _, body = read_skill(name)
            for lineno, text in commands_in(body):
                tokens = text.split()
                seen += 1
                try:
                    leaf, consumed = resolve(self.parser, tokens)
                except AssertionError as exc:
                    self.fail(f"{name}:{lineno} `{text}`: {exc}")
                known = set(leaf._option_string_actions) | GLOBAL_FLAGS
                for token in tokens[consumed:]:
                    if token.startswith("--"):
                        flag = token.split("=")[0]
                        self.assertIn(flag, known, f"{name}:{lineno} `{text}`: unknown option {flag}")
        self.assertGreaterEqual(seen, 30, "the skills name too few commands to be procedures")

    def test_the_parser_walk_refuses_an_invented_verb(self):
        with self.assertRaises(AssertionError):
            resolve(self.parser, ["gate", "frobnicate"])
        leaf, consumed = resolve(self.parser, ["tdd", "change-request", "new", "--feature", "x"])
        self.assertEqual(consumed, 3)

    def test_every_area_used_by_the_lifecycle_has_a_skill_that_names_it(self):
        load_batuta()
        used = set()
        for name in NAMES:
            _, _, body = read_skill(name)
            used.update(text.split()[0] for _, text in commands_in(body))
        self.assertLessEqual({"route", "brief", "report", "dispatch", "spec", "size", "tech", "adr", "contract", "tdd",
                              "gate", "skeleton", "provider", "context", "memory", "device", "lessons"}, used)


class SkillAgentTests(unittest.TestCase):
    def test_every_named_agent_exists(self):
        load_batuta()
        agents = {p.stem for p in AGENTS.glob("*.md")}
        self.assertEqual(agents, {"adversary", "doc-writer", "implementer", "reviewer", "runner", "searcher",
                                  "test-author"})
        named = set()
        for name in NAMES:
            text, _, _ = read_skill(name)
            for agent in re.findall(r"batuta:([a-z][a-z-]*)", text):
                named.add(agent)
                self.assertIn(agent, agents, f"{name}: names agent batuta:{agent}, which has no file")
        self.assertLessEqual({"implementer", "test-author", "adversary", "reviewer"}, named)

    def test_delegate_says_explicit_model_and_the_lanes(self):
        load_batuta()
        text, _, _ = read_skill("delegate")
        for needle in ("model", "brief lint", "subagent", "sdk", "provider:", "subagent_type"):
            self.assertIn(needle, text)

    def test_verify_uses_the_adversary_and_checks_its_report(self):
        load_batuta()
        text, _, _ = read_skill("verify")
        self.assertIn("batuta:adversary", text)
        self.assertIn("gate evidence-lint", text)

    def test_promote_merges_only_on_green_gates(self):
        load_batuta()
        text, _, _ = read_skill("promote")
        self.assertIn("gate check", text)
        self.assertIn("gate promote", text)
        self.assertRegex(text, r"(?i)only (on|when) green|never (merge|override)")

    def test_freeze_leaves_the_approval_to_the_human(self):
        load_batuta()
        text, _, _ = read_skill("freeze")
        self.assertRegex(text, r"(?i)type[sd]? the (approval )?phrase")
        for _, line in commands_in(text):
            self.assertFalse(line.startswith(("spec approve", "spec hook-approval", "tdd change-request decide")), line)


class SkillReviewFixes(unittest.TestCase):
    """Findings M2, M3, M4 and M5 of the adversary check of unit U9a."""

    def test_bash_grants_are_narrowed_to_the_plugin_script(self):
        load_batuta()
        for name in NAMES:
            _, meta, _ = read_skill(name)
            grants = re.findall(r"Bash\(([^)]*)\)", str(meta["allowed-tools"]))
            self.assertTrue(grants, f"{name}: no Bash grant")
            for grant in grants:
                self.assertNotEqual(grant.strip(), "python *", name)
                self.assertIn("batuta.py", grant, f"{name}: the Bash grant must name the plugin script: {grant}")

    def test_doctor_says_how_to_choose_the_interpreter_in_the_bash_tool(self):
        load_batuta()
        text, _, _ = read_skill("doctor")
        self.assertIn("CLAUDE_PLUGIN_OPTION_PYTHON", text)
        self.assertRegex(text, r"(?i)bash tool")
        self.assertRegex(text, r"(?i)not exported|is not set|does not export")
        self.assertNotIn("never fire", text)
        self.assertRegex(text, r"(?i)block")

    def test_spec_hands_over_by_asking_the_human_to_run_the_freeze_skill(self):
        load_batuta()
        text, _, _ = read_skill("spec")
        self.assertIn("/batuta:freeze", text)
        self.assertNotIn("with the `freeze` skill", text)

    def test_the_readme_fragment_states_the_minimum_claude_code_version_for_on_failure(self):
        fragment = (ROOT / "changes" / "u9a-plugin-readme.md").read_text(encoding="utf-8")
        self.assertIn("v2.1.295", fragment)
        self.assertIn("https://code.claude.com/docs/en/hooks", fragment)
        self.assertIn("onFailure", fragment)


if __name__ == "__main__":
    unittest.main()
