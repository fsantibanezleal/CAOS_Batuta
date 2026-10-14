"""Approval capture, spec approve, spec freeze --check: hash-bound, typed, voided by any later edit."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_project import (CONTRACTS, SPEC, SPEC_ID, make_project, messages, prefix_of, run, run_json, sha, write)  # noqa: E402
from batuta_lib import approval  # noqa: E402
from batuta_lib import contract as core  # noqa: E402
from batuta_lib.areas import spec as spec_area  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_project(self._tmp.name)
        self.spec = self.root / f"specs/{SPEC_ID}/spec.md"

    def tearDown(self):
        self._tmp.cleanup()

    def phrase(self):
        return f"approve {SPEC_ID} {prefix_of(self.spec)}"

    def approvals(self):
        return sorted((self.root / f"specs/{SPEC_ID}/approvals").glob("*.json"))

    def approve(self, typed=None):
        """`spec approve` with the human's console patched in process (never an environment switch an agent could set)."""
        with mock.patch.object(spec_area, "_read_console", return_value=(typed or self.phrase()) + "\n"):
            return run_json("spec", "approve", SPEC_ID, "--root", self.root)

    def check(self):
        return run_json("spec", "freeze", "--check", SPEC_ID, "--root", self.root)

    def hook(self, prompt, cwd=None):
        return spec_area.HOOKS["spec-approval"]({"hook_event_name": "UserPromptSubmit", "prompt": prompt,
                                                 "cwd": str(cwd or self.root)})


class Phrase(unittest.TestCase):
    def test_phrase_parsing(self):
        good = ["approve 001-x abcdef012345", "  APPROVE 001-x ABCDEF012345", "\n\napprove 001-x abcdef012345 thanks",
                "approve 001-x abcdef012345\nsecond line"]
        for text in good:
            with self.subTest(text=text):
                self.assertEqual(approval.parse_phrase(text), ("001-x", "abcdef012345"))
        for text in ["do not approve 001-x abcdef012345", "I approve 001-x abcdef012345", "approved 001-x abcdef012345",
                     "approve of this", "", "line one\napprove 001-x abcdef012345"]:
            with self.subTest(text=text):
                self.assertIsNone(approval.parse_phrase(text))

    def test_prefix_shape_is_judged_at_approval_not_parsing(self):
        self.assertEqual(approval.parse_phrase("approve 001-x abc"), ("001-x", "abc"))
        self.assertEqual(approval.parse_phrase("approve 001-x"), ("001-x", ""))

    def test_valid_prefix(self):
        self.assertTrue(approval.valid_prefix("abcdef012345"))
        for bad in ("abcdef01234", "abcdef0123456", "abcdef01234g", ""):
            self.assertFalse(approval.valid_prefix(bad))


class Approve(Base):
    def test_typed_phrase_writes_a_c06_record(self):
        code, doc, _ = self.approve()
        self.assertEqual(code, 0, messages(doc))
        files = self.approvals()
        self.assertEqual(len(files), 1)
        self.assertEqual(core.validate_file(files[0], core.find_schema(CONTRACTS, "C06")), [])
        rec = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(rec["spec_sha256"], sha(self.spec))
        self.assertEqual(rec["approved_spec_sha256_prefix"], sha(self.spec)[:12])
        self.assertEqual(sorted(rec["contracts_sha256"]), ["docs/contracts/alert-event.schema.json", "docs/contracts/alert-list.schema.json"])
        self.assertEqual(list(rec["adrs_sha256"]), ["docs/decisions/ADR-0001-alert-transport.md"])
        self.assertEqual(sorted(rec["named_tests_sha256"]), ["tests/api.test.js", "tests/test_alerts.py"])
        self.assertTrue(rec["prompt_excerpt"].startswith("approve 001-alerts"))

    def test_upper_case_phrase_is_accepted_and_prefix_stored_lower_case(self):
        code, doc, _ = self.approve(f"APPROVE {SPEC_ID} {prefix_of(self.spec).upper()}")
        self.assertEqual(code, 0, messages(doc))
        self.assertEqual(json.loads(self.approvals()[0].read_text(encoding="utf-8"))["approved_spec_sha256_prefix"], prefix_of(self.spec))

    def test_stale_prefix_is_refused_with_the_current_one_and_nothing_is_written(self):
        old = prefix_of(self.spec)
        write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace("Empty file.", "Empty file and a zero-byte file."))
        code, doc, _ = self.approve(f"approve {SPEC_ID} {old}")
        self.assertEqual(code, 1)
        text = " ".join(messages(doc, "REFUSED"))
        self.assertIn(prefix_of(self.spec), text)
        self.assertEqual(self.approvals(), [])

    def test_short_non_hex_and_long_prefixes_are_refused(self):
        for bad in (prefix_of(self.spec)[:8], "zzzzzzzzzzzz", prefix_of(self.spec) + "a", ""):
            with self.subTest(prefix=bad):
                code, doc, _ = self.approve(f"approve {SPEC_ID} {bad}".strip())
                self.assertEqual(code, 1)
                self.assertEqual(self.approvals(), [])

    def test_phrase_for_another_spec_or_without_the_keyword_is_refused(self):
        for typed in (f"approve 002-other {prefix_of(self.spec)}", f"yes {SPEC_ID} {prefix_of(self.spec)}",
                      f"do not approve {SPEC_ID} {prefix_of(self.spec)}", ""):
            code, doc, _ = self.approve(typed or " ")
            self.assertEqual(code, 1, typed)
        self.assertEqual(self.approvals(), [])

    def test_empty_console_line_is_refused(self):
        with mock.patch.object(spec_area, "_read_console", return_value=""):
            code, doc, _ = run_json("spec", "approve", SPEC_ID, "--root", self.root)
        self.assertEqual(code, 1)

    def test_output_states_what_is_hashed_and_that_it_is_the_hookless_path(self):
        with mock.patch.object(spec_area, "_read_console", return_value=self.phrase() + "\n"):
            code, out, _ = run("spec", "approve", SPEC_ID, "--root", self.root)
        self.assertIn("docs/contracts/alert-event.schema.json", out)
        self.assertIn("tests/test_alerts.py", out)
        self.assertIn("hooks", out.lower())

    def test_draft_and_retired_specs_cannot_be_approved(self):
        for status in ("Draft", "Retired"):
            write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace("status: Review", f"status: {status}"))
            code, doc, _ = self.approve()
            self.assertEqual(code, 1, status)
        self.assertEqual(self.approvals(), [])

    def test_unfrozen_contract_refuses_the_freeze(self):
        write(self.root, "docs/contracts/catalog.md", (self.root / "docs/contracts/catalog.md").read_text(encoding="utf-8")
              .replace("| active | yes |\n| alert-list", "| active | no |\n| alert-list", 1))
        code, doc, _ = self.approve()
        self.assertEqual(code, 1)
        self.assertTrue(any("alert-event" in m and "frozen" in m for m in messages(doc, "REFUSED")), messages(doc))
        self.assertEqual(self.approvals(), [])

    def test_missing_contract_file_or_named_test_refuses(self):
        (self.root / "docs/contracts/alert-list.schema.json").unlink()
        self.assertEqual(self.approve()[0], 1)
        write(self.root, "docs/contracts/alert-list.schema.json", "{}\n")
        (self.root / "tests/api.test.js").unlink()
        self.assertEqual(self.approve()[0], 1)
        self.assertEqual(self.approvals(), [])

    def test_a_spec_failing_lint_cannot_be_approved(self):
        write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace("`pytest tests/test_alerts.py`", "TBD"))
        code, doc, _ = self.approve()
        self.assertEqual(code, 1)
        self.assertEqual(self.approvals(), [])

    def test_show_prints_the_files_and_the_phrase(self):
        code, doc, _ = run_json("spec", "show", SPEC_ID, "--root", self.root)
        self.assertEqual(code, 0, messages(doc))
        text = "\n".join(messages(doc))
        self.assertIn(self.phrase(), text)
        self.assertIn("docs/decisions/ADR-0001-alert-transport.md", text)
        self.assertEqual(self.approvals(), [])


class Hook(Base):
    def test_typed_prompt_is_captured_and_never_blocks(self):
        res = self.hook(self.phrase())
        self.assertEqual(res["exit_code"], 0)
        self.assertEqual(res["contract_version"], "1.0")
        self.assertEqual(len(self.approvals()), 1)
        out = res["output"]
        self.assertTrue(out is None or "recorded" in json.dumps(out))

    def test_other_prompts_write_nothing_and_return_a_null_output(self):
        for prompt in ("hello", "do not approve " + self.phrase()[8:], "please approve this plan", ""):
            res = self.hook(prompt)
            self.assertEqual(res, {"contract_version": "1.0", "exit_code": 0, "output": None})
        self.assertEqual(self.approvals(), [])

    def test_stale_prefix_is_refused_without_blocking_and_with_the_current_prefix(self):
        res = self.hook(f"approve {SPEC_ID} 000000000000")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn(prefix_of(self.spec), json.dumps(res["output"]))
        self.assertEqual(self.approvals(), [])

    def test_unknown_spec_and_broken_project_never_block_or_raise(self):
        res = self.hook("approve 009-none 000000000000")
        self.assertEqual(res["exit_code"], 0)
        with tempfile.TemporaryDirectory() as empty:
            res = self.hook(self.phrase(), cwd=empty)
            self.assertEqual(res["exit_code"], 0)

    def test_payload_without_a_prompt_is_ignored(self):
        res = spec_area.HOOKS["spec-approval"]({"hook_event_name": "UserPromptSubmit"})
        self.assertEqual(res["exit_code"], 0)

    def test_cli_twin_is_a_dry_run_that_never_writes(self):
        payload = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": self.phrase(), "cwd": str(self.root)})
        code, out, _ = run("spec", "hook-approval", stdin=payload)
        self.assertEqual(code, 0)
        self.assertEqual(self.approvals(), [])
        self.assertIn("would record", out)
        self.assertIn("dry run", out)

    def test_cli_twin_dry_run_reports_a_refusal(self):
        payload = json.dumps({"prompt": f"approve {SPEC_ID} 000000000000", "cwd": str(self.root)})
        code, out, _ = run("spec", "hook-approval", stdin=payload)
        self.assertEqual(code, 1)
        self.assertEqual(self.approvals(), [])

    def test_handler_result_satisfies_c31_through_the_full_check(self):
        res = self.hook(self.phrase())
        schema = core.load_schema(core.find_schema(CONTRACTS, "C31"))
        self.assertEqual(core.validate_instance("C31", res, schema), [])

    def test_handler_output_has_the_official_shape_with_a_system_message(self):
        res = self.hook(self.phrase())
        out = res["output"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("recorded", out["hookSpecificOutput"]["additionalContext"])
        self.assertIn("recorded", out["systemMessage"])

    def test_console_refusal_without_a_tty_writes_nothing(self):
        code, doc, _ = run_json("spec", "approve", SPEC_ID, "--root", self.root, stdin=self.phrase() + "\n")
        self.assertEqual(code, 1)
        self.assertTrue(any("console" in m for m in messages(doc, "REFUSED")), messages(doc))
        self.assertEqual(self.approvals(), [])

    def test_console_reader_refuses_when_stdin_is_not_a_tty_and_names_the_device(self):
        with mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: False)):
            with self.assertRaises(spec_area.ConsoleError):
                spec_area._read_console()

    def test_console_reader_opens_the_console_device_not_stdin(self):
        opened = []

        def fake_open(path, *a, **k):
            opened.append(path)
            return mock.MagicMock(__enter__=lambda s: mock.Mock(readline=lambda: "typed\n"), __exit__=lambda *x: False)

        with mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: True)), \
                mock.patch.object(spec_area, "_console_mode_ok", return_value=True), mock.patch("builtins.open", fake_open):
            self.assertEqual(spec_area._read_console(), "typed\n")
        self.assertEqual(opened, ["CONIN$" if sys.platform == "win32" else "/dev/tty"])

    def test_refusals_never_write_even_on_a_record_that_fails_c06(self):
        # F-12: a ValueError from write_record is a REFUSED item, never a traceback
        with mock.patch.object(approval, "write_record", side_effect=ValueError("the approval record does not satisfy C06: x")):
            code, doc, _ = self.approve()
        self.assertEqual(code, 1)
        self.assertTrue(any("C06" in m for m in messages(doc, "REFUSED")))

    def test_forged_record_dated_in_the_future_is_ignored_and_a_later_real_approval_stands(self):
        # F-10
        old = prefix_of(self.spec)
        write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace("Empty file.", "Changed."))
        self.assertEqual(self.approve()[0], 0)
        real = self.approvals()[0]
        rec = json.loads(real.read_text(encoding="utf-8"))
        rec["approved_at"] = "2099-01-01T00:00:00Z"
        rec["spec_sha256"] = "a" * 64
        rec["approved_spec_sha256_prefix"] = "a" * 12
        rec["prompt_excerpt"] = f"approve {SPEC_ID} " + "a" * 12
        write(self.root, f"specs/{SPEC_ID}/approvals/a.json", json.dumps(rec))
        code, doc, _ = self.check()
        self.assertEqual(code, 2, messages(doc))
        self.assertTrue(any("future" in m for m in messages(doc, "WARN")))
        self.assertIn("VALID", " ".join(messages(doc)))

    def test_hooks_dict_is_a_literal_discoverable_by_the_launcher(self):
        found, problems = core.discover_hook_ids(Path(spec_area.__file__).parent)
        self.assertEqual(problems, [])
        self.assertEqual(found.get("spec-approval"), ["spec"])


class Freeze(Base):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.approve()[0], 0)

    def state(self):
        code, doc, _ = self.check()
        return code, messages(doc)

    def test_valid_after_approval(self):
        code, msgs = self.state()
        self.assertEqual(code, 0, msgs)
        self.assertTrue(any(m.startswith("VALID") for m in msgs), msgs)

    def test_editing_the_spec_voids(self):
        write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace("Empty file.", "Two files."))
        code, msgs = self.state()
        self.assertEqual(code, 1)
        self.assertTrue(any("VOID" in m and "spec.md" in m for m in msgs), msgs)

    def test_editing_a_referenced_contract_voids_and_names_it(self):
        write(self.root, "docs/contracts/alert-event.schema.json", '{"title": "changed"}\n')
        code, msgs = self.state()
        self.assertEqual(code, 1)
        self.assertTrue(any("VOID" in m and "alert-event.schema.json" in m for m in msgs), msgs)

    def test_editing_an_accepted_adr_voids(self):
        p = self.root / "docs/decisions/ADR-0001-alert-transport.md"
        write(self.root, "docs/decisions/ADR-0001-alert-transport.md", p.read_text(encoding="utf-8").replace("Typed models.", "Untyped."))
        code, msgs = self.state()
        self.assertEqual(code, 1)
        self.assertTrue(any("ADR-0001" in m for m in msgs), msgs)

    def test_editing_a_named_test_voids(self):
        write(self.root, "tests/test_alerts.py", "# REQ: REQ-ALR-001, REQ-ALR-002\ndef test_listing():\n    assert 1 == 2\n")
        code, msgs = self.state()
        self.assertEqual(code, 1)
        self.assertTrue(any("tests/test_alerts.py" in m for m in msgs), msgs)

    def test_deleting_a_hashed_file_voids(self):
        for rel in ("tests/api.test.js", "docs/contracts/alert-list.schema.json", "docs/decisions/ADR-0001-alert-transport.md"):
            data = (self.root / rel).read_bytes()
            (self.root / rel).unlink()
            code, msgs = self.state()
            self.assertEqual(code, 1, rel)
            self.assertTrue(any("missing" in m or "deleted" in m for m in msgs), msgs)
            (self.root / rel).write_bytes(data)
            self.assertEqual(self.state()[0], 0, rel)

    def test_crlf_and_lf_variants_hash_equal(self):
        for rel in ("tests/test_alerts.py", f"specs/{SPEC_ID}/spec.md", "docs/contracts/alert-event.schema.json"):
            p = self.root / rel
            p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        code, msgs = self.state()
        self.assertEqual(code, 0, msgs)

    def test_unfreezing_a_contract_voids(self):
        write(self.root, "docs/contracts/catalog.md", (self.root / "docs/contracts/catalog.md").read_text(encoding="utf-8")
              .replace("| active | yes |\n| alert-list", "| active | no |\n| alert-list", 1))
        code, msgs = self.state()
        self.assertEqual(code, 1)

    def test_an_adr_the_spec_does_not_reference_does_not_matter(self):
        p = self.root / f"specs/{SPEC_ID}/spec.md"
        # Spec text changes anyway; the point is the set of hashed files is recomputed from the current spec.
        write(self.root, "docs/decisions/ADR-0002-x.md", (self.root / "docs/decisions/ADR-0001-alert-transport.md").read_text(encoding="utf-8")
              .replace("ADR-0001", "ADR-0002").replace("tech_evaluations: [fastapi]", "tech_evaluations: []"))
        write(self.root, f"specs/{SPEC_ID}/spec.md", p.read_text(encoding="utf-8"))
        self.assertEqual(self.state()[0], 0)

    def test_newest_valid_approval_wins_and_older_ones_stay(self):
        old = self.approvals()[0]
        write(self.root, f"specs/{SPEC_ID}/spec.md", SPEC.replace("Empty file.", "Two files."))
        self.assertEqual(self.state()[0], 1)
        self.assertEqual(self.approve()[0], 0)
        self.assertEqual(len(self.approvals()), 2)
        self.assertTrue(old.is_file())
        self.assertEqual(self.state()[0], 0)

    def test_a_hand_written_record_without_the_typed_phrase_is_ignored(self):
        files = self.approvals()
        rec = json.loads(files[0].read_text(encoding="utf-8"))
        rec["prompt_excerpt"] = "looks good"
        write(self.root, f"specs/{SPEC_ID}/approvals/99991231T000000000000Z.json", json.dumps(rec, indent=2) + "\n")
        code, doc, _ = self.check()
        self.assertTrue(any("99991231" in i.get("path", "") or "ignored" in i["message"] for i in doc["items"] if i["tag"] == "WARN"))
        self.assertIn("VALID", " ".join(messages(doc)))

    def test_no_approval_is_void_with_a_reason(self):
        for f in self.approvals():
            f.unlink()
        code, msgs = self.state()
        self.assertEqual(code, 1)
        self.assertTrue(any("no approval" in m.lower() for m in msgs), msgs)

    def test_freeze_without_check_only_checks(self):
        before = self.approvals()
        code, doc, _ = run_json("spec", "freeze", SPEC_ID, "--root", self.root)
        self.assertEqual(code, 0)
        self.assertEqual(before, self.approvals())

    def test_c06_fixtures_that_are_invalid_are_never_taken_as_an_approval(self):
        for fx in sorted((CONTRACTS / "fixtures" / "C06").glob("invalid-*.json")):
            with self.subTest(fixture=fx.name):
                for f in self.approvals():
                    f.unlink()
                meta = json.loads(fx.read_text(encoding="utf-8"))
                expect = meta.pop("_expect", "")
                meta.pop("_why", None)
                write(self.root, f"specs/{SPEC_ID}/approvals/20261013T000000000000Z.json", json.dumps(meta))
                code, doc, _ = self.check()
                self.assertEqual(code, 1)
                warns = " ".join(messages(doc, "WARN")).lower()
                self.assertIn(expect.lower(), warns)
                self.assertNotIn("VALID", " ".join(m for m in messages(doc) if m.startswith("VALID")))


if __name__ == "__main__":
    unittest.main()
