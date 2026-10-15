"""The approval phrase counts only when the first line, trimmed, is exactly `approve <spec id> <12 hex>` (tdd review R3-06)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import SPEC_ID, make_project, messages, prefix_of, run, run_json  # noqa: E402
from batuta_lib import approval  # noqa: E402
from batuta_lib.areas import spec as spec_area  # noqa: E402


class ParsePhrase(unittest.TestCase):
    def test_exact_first_line_only(self):
        for text in ("approve 001-x abcdef012345", "  APPROVE 001-x ABCDEF012345  ", "\n\napprove 001-x abcdef012345\n",
                     "approve 001-x abcdef012345\nthanks, ship it", "approve\t001-x\tabcdef012345"):
            with self.subTest(text=text):
                self.assertEqual(approval.parse_phrase(text), ("001-x", "abcdef012345"))

    def test_other_text_on_the_first_line_is_not_the_phrase(self):
        for text in ("approve 001-x abcdef012345 thanks", "approve 001-x abcdef012345 -- no wait, do not",
                     "approve 001-x abcdef012345, please", "approve 001-x abcdef012345 approve 001-x abcdef012345"):
            with self.subTest(text=text):
                self.assertIsNone(approval.parse_phrase(text))
                attempt = approval.parse_attempt(text)
                self.assertEqual(attempt[:2], ("001-x", "abcdef012345"))
                self.assertTrue(attempt[2])

    def test_a_sentence_that_merely_contains_the_phrase_is_no_attempt(self):
        for text in ("do not approve 001-x abcdef012345", "I approve 001-x abcdef012345", "", "hello"):
            with self.subTest(text=text):
                self.assertIsNone(approval.parse_attempt(text))


class Refusal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_project(self._tmp.name)
        self.prefix = prefix_of(self.root / "specs" / SPEC_ID / "spec.md")

    def tearDown(self):
        self._tmp.cleanup()

    def records(self):
        return list((self.root / f"specs/{SPEC_ID}/approvals").glob("*.json"))

    def hook(self, prompt):
        return spec_area.HOOKS["spec-approval"]({"hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": str(self.root)})

    def test_the_handler_refuses_extra_text_with_a_message_and_writes_nothing(self):
        res = self.hook(f"approve {SPEC_ID} {self.prefix} -- no wait, do not")
        self.assertEqual(res["exit_code"], 0)
        ctx = res["output"]["hookSpecificOutput"]["additionalContext"]
        self.assertIn("REFUSED", ctx)
        self.assertIn("exactly", ctx)
        self.assertEqual(self.records(), [])

    def test_the_handler_accepts_the_exact_line_followed_by_more_lines(self):
        res = self.hook(f"  Approve {SPEC_ID} {self.prefix.upper()}  \nthe rest of my message is ignored")
        self.assertIn("recorded", res["output"]["systemMessage"])
        rec = json.loads(self.records()[0].read_text(encoding="utf-8"))
        self.assertTrue(rec["prompt_excerpt"].startswith(f"approve {SPEC_ID}".split()[0]) or rec["prompt_excerpt"].lower().startswith("approve"))
        self.assertNotIn("ignored", rec["prompt_excerpt"])

    def test_spec_approve_refuses_extra_text_on_the_console_line(self):
        with mock.patch.object(spec_area, "_read_console", return_value=f"approve {SPEC_ID} {self.prefix} yes\n"):
            code, doc, _ = run_json("spec", "approve", SPEC_ID, "--root", self.root)
        self.assertEqual(code, 1)
        self.assertTrue(any("exactly" in m for m in messages(doc, "REFUSED")), messages(doc))
        self.assertEqual(self.records(), [])

    def test_the_dry_run_reports_the_same_refusal(self):
        payload = json.dumps({"prompt": f"approve {SPEC_ID} {self.prefix} maybe", "cwd": str(self.root)})
        code, out, _ = run("spec", "hook-approval", stdin=payload)
        self.assertEqual(code, 1)
        self.assertIn("exactly", out)

    def test_a_long_trailing_text_is_clipped_in_the_message(self):
        res = self.hook(f"approve {SPEC_ID} {self.prefix} " + "z" * 20000)
        ctx = res["output"]["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(ctx), 10000)
        self.assertNotIn("z" * 250, ctx)
        self.assertEqual(self.records(), [])


if __name__ == "__main__":
    unittest.main()
