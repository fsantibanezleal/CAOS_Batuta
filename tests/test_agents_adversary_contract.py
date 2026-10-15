"""The adversary and test-author agent files: C18 conformance and the rules their bodies must carry (ADV-2)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
from batuta_lib import contract as core  # noqa: E402
from batuta_lib import frontmatter as fm  # noqa: E402

AGENTS = ROOT / "plugins" / "batuta" / "agents"
SCHEMA = ROOT / "plugins" / "batuta" / "contracts" / "C18-agent-definition.schema.json"


def load(name):
    path = AGENTS / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    meta, body = fm.parse(text)
    return path, text, meta, body


def tool_names(meta):
    tools = meta.get("tools", [])
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",")]
    return {t.split("(")[0].strip() for t in tools if t.strip()}


class AgentFiles(unittest.TestCase):
    def test_both_files_satisfy_c18(self):
        for name in ("adversary", "test-author"):
            path, _, meta, _ = load(name)
            self.assertEqual([], core.validate_file(path, SCHEMA, "C18"), name)
            self.assertEqual(name, meta["name"])

    def test_models_and_effort_follow_the_default_roles(self):
        _, _, adv, _ = load("adversary")
        _, _, ta, _ = load("test-author")
        self.assertEqual(("sonnet", "high"), (adv["model"], adv["effort"]))
        self.assertEqual(("sonnet", "medium"), (ta["model"], ta["effort"]))

    def test_no_frontmatter_hooks_are_declared(self):
        for name in ("adversary", "test-author"):
            self.assertNotIn("hooks", load(name)[2])

    def test_no_machine_paths_dashes_or_emoji(self):
        for name in ("adversary", "test-author"):
            text = load(name)[1]
            self.assertNotIn(chr(0x2014), text)   # built from code points so this file passes the content check itself
            self.assertNotIn(chr(0x2192), text)
            self.assertIsNone(re.search(r"[A-Za-z]:[\\/]", text), name)
            self.assertFalse(any(0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF for c in text), name)


class Adversary(unittest.TestCase):
    def setUp(self):
        self.path, self.text, self.meta, self.body = load("adversary")
        self.tools = tool_names(self.meta)

    def test_it_cannot_edit_product_files(self):
        self.assertNotIn("Edit", self.tools)
        self.assertNotIn("NotebookEdit", self.tools)
        disallowed = self.meta.get("disallowedTools", [])
        disallowed = {t.strip() for t in (disallowed.split(",") if isinstance(disallowed, str) else disallowed)}
        self.assertTrue({"Edit", "NotebookEdit"} <= disallowed, disallowed)

    def test_it_has_the_read_tools_and_write_for_its_evidence_file_only(self):
        self.assertTrue({"Read", "Grep", "Glob", "Bash", "Write"} <= self.tools, self.tools)
        self.assertNotIn("Agent", self.tools)
        flat = " ".join(self.body.split())
        self.assertRegex(flat, r"Write\b[^.]*\bonly\b[^.]*evidence file|only[^.]*Write[^.]*evidence file")
        self.assertIn("specs/<feature>/evidence/<gate>.md", self.body)

    def test_it_never_grants_waivers_and_never_edits_product_files(self):
        low = " ".join(self.body.lower().split())
        self.assertIn("never grant", low)
        self.assertIn("waiver", low)
        self.assertRegex(low, r"never (edit|modif)[a-z]* (any )?(product|repository) file")

    def test_the_procedure_is_in_the_body_step_by_step(self):
        steps = [
            "Restate the gate's definition of done from the gate file and the approved plan, never from the builder's summary.",
            "Reproduce every \"done\" claim by running the command; a claim without command and output is UNVERIFIED and counts as failure.",
            "Pre-mortem: list the five likeliest ways the artifact is wrong, then test each.",
            "Oracle tampering check: diff tests, goldens, thresholds and lock files against the previous gate; any weakening is a BLOCKER unless justified by a trailer plus a spec change.",
            "Score each criterion against its threshold; below threshold fails; \"do not rationalize\".",
            "Each finding needs severity, evidence, minimal reproduction and a fix; findings without reproduction are dropped (no nitpicks).",
            "Research gate: re-fetch a random sample of at least 5 or 20 percent of cited URLs; run one counter-evidence search per key recommendation.",
            "Public-surface honesty: run a guard script and include its output.",
        ]
        positions = []
        for number, step in enumerate(steps, 1):
            line = f"{number}. {step}"
            self.assertIn(line, self.body, f"step {number} is not verbatim")
            positions.append(self.body.index(line))
        self.assertEqual(sorted(positions), positions)

    def test_it_starts_from_fresh_context_and_never_reads_the_builders_reasoning(self):
        low = " ".join(self.body.lower().split())
        self.assertIn("fresh context", low)
        self.assertRegex(low, r"never (read|use|ask for)[^.]*builder's (reasoning|summary|transcript)")

    def test_the_evidence_format_is_the_c09_one(self):
        for fragment in ("Definition of done restated", "Commands and output", "Findings", "Waivers requested",
                         "gate:", "feature:", "verdict:", "role: adversary", "model:", "commit:", "date:",
                         "PASS-WITH-FIXES", "Re-check:", "dropped-no-repro", "reviewed commit"):
            self.assertIn(fragment, self.body, fragment)

    def test_the_routing_of_critical_gates_is_stated(self):
        self.assertIn("reviewer", self.body)
        self.assertIn("critical", self.body)

    def test_the_reply_is_short(self):
        self.assertRegex(self.body, r"5[- ]line|five[- ]line|five lines|5 lines")

    def test_an_evidence_example_in_the_body_does_not_validate_as_a_real_verdict(self):
        # the example in the body sits inside a code fence or comment, never as live front matter
        self.assertIsNone(re.match(r"\s*---\s*\ngate:", self.body))


class TestAuthor(unittest.TestCase):
    def setUp(self):
        self.path, self.text, self.meta, self.body = load("test-author")
        self.tools = tool_names(self.meta)

    def test_it_writes_tests_and_runs_them(self):
        self.assertTrue({"Read", "Grep", "Glob", "Bash", "Write", "Edit"} <= self.tools, self.tools)

    def test_it_never_writes_implementation_code(self):
        low = self.body.lower()
        self.assertRegex(low, r"never write[s]? (any )?implementation")

    def test_it_proves_the_tests_fail_for_the_right_reason(self):
        low = self.body.lower()
        self.assertIn("fail for the right reason", low)
        self.assertIn("red", low)
        self.assertIn("exit code", low)

    def test_it_starts_from_the_spec_and_the_contract_fixtures(self):
        low = self.body.lower()
        self.assertIn("spec", low)
        self.assertIn("contract fixtures", low)

    def test_the_test_order_follows_the_method(self):
        low = self.body.lower()
        self.assertLess(low.index("contract conformance"), low.index("availability state"))
        self.assertLess(low.index("availability state"), low.index("then behavior"))

    def test_the_red_commit_grammar_is_named(self):
        self.assertIn("[red] T-NNN", self.body)

    def test_it_never_edits_a_locked_test_and_never_grants_anything(self):
        low = self.body.lower()
        self.assertIn("locked", low)
        self.assertIn("test-change-requests", low)


if __name__ == "__main__":
    unittest.main()
