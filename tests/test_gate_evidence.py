"""gate evidence-lint: C09 plus the rules of the contract's prose (open findings, reproductions, routing, comments)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import CONTRACTS, FEATURE, TODAY, Case, evidence_text, run  # noqa: E402


class EvidenceLint(Case):
    def lint(self, text, name="L7-build.md", *extra):
        d = self.tmp / "specs" / FEATURE / "evidence"
        d.mkdir(parents=True, exist_ok=True)
        p = d / name
        p.write_bytes(text.encode("utf-8"))
        return run("gate", "evidence-lint", str(p), "--today", TODAY, *extra)

    def test_valid_routine_evidence_passes(self):
        code, out = self.lint(evidence_text("L7-build"))
        self.assertEqual(0, code, out)
        self.assertIn("OK", out)

    def test_pass_with_an_open_major_finding_is_refused(self):
        code, out = self.lint(evidence_text("L7-build", findings=[("F-1", "major", "off by one", "run x", "open")]))
        self.assertEqual(1, code, out)
        self.assertIn("no open critical or major finding", out)

    def test_pass_with_an_open_critical_finding_is_refused(self):
        code, out = self.lint(evidence_text("L7-build", findings=[("F-1", "critical", "data loss", "run x", "open")]))
        self.assertEqual(1, code, out)

    def test_pass_with_open_minor_is_accepted(self):
        code, out = self.lint(evidence_text("L7-build", findings=[("F-1", "minor", "typo", "run x", "open")]))
        self.assertEqual(0, code, out)

    def test_pass_with_fixes_needs_a_recheck_line_per_fixed_finding(self):
        rows = [("F-2", "major", "off by one", "run x", "fixed")]
        code, out = self.lint(evidence_text("L7-build", verdict="PASS-WITH-FIXES", findings=rows))
        self.assertEqual(1, code, out)
        self.assertIn("Re-check", out)
        code, out = self.lint(evidence_text("L7-build", verdict="PASS-WITH-FIXES", findings=rows,
                                            extra_body="Re-check: F-2 verified at abc1234.\n"))
        self.assertEqual(0, code, out)

    def test_pass_with_fixes_with_an_open_major_is_refused(self):
        rows = [("F-2", "major", "off by one", "run x", "open")]
        code, out = self.lint(evidence_text("L7-build", verdict="PASS-WITH-FIXES", findings=rows))
        self.assertEqual(1, code, out)

    def test_fail_verdict_with_open_critical_is_valid_evidence(self):
        code, out = self.lint(evidence_text("L7-build", verdict="FAIL", findings=[("F-1", "critical", "x", "run x", "open")]))
        self.assertEqual(0, code, out)

    def test_a_finding_without_a_reproduction_is_refused(self):
        for repro in ("-", "none", "n/a", "TODO"):
            code, out = self.lint(evidence_text("L7-build", findings=[("F-1", "minor", "vague", repro, "open")]))
            self.assertEqual(1, code, (repro, out))
            self.assertIn("no reproduction", out)

    def test_a_dropped_finding_may_have_a_placeholder_reproduction(self):
        code, out = self.lint(evidence_text("L7-build", findings=[("F-1", "minor", "vague", "-", "dropped-no-repro")]))
        self.assertEqual(0, code, out)

    def test_duplicate_finding_ids_are_refused(self):
        rows = [("F-1", "minor", "a", "run a", "open"), ("F-1", "minor", "b", "run b", "open")]
        code, out = self.lint(evidence_text("L7-build", findings=rows))
        self.assertEqual(1, code, out)
        self.assertIn("appears twice", out)

    def test_builder_role_is_refused_by_the_contract(self):
        code, out = self.lint(evidence_text("L7-build", role="implementer"))
        self.assertEqual(1, code, out)

    def test_a_script_is_not_an_independent_check(self):
        code, out = self.lint(evidence_text("L7-build", role="script"))
        self.assertEqual(1, code, out)
        self.assertIn("independent", out)

    def test_critical_gate_needs_the_reviewer_role_on_the_critical_model(self):
        code, out = self.lint(evidence_text("L9-promote", role="adversary", model="sonnet"), "L9-promote.md")
        self.assertEqual(1, code, out)
        self.assertIn("reviewer", out)
        self.assertIn("opus", out)
        code, out = self.lint(evidence_text("L9-promote"), "L9-promote.md")
        self.assertEqual(0, code, out)

    def test_routine_gate_with_the_wrong_model_is_refused(self):
        code, out = self.lint(evidence_text("L7-build", model="opus"))
        self.assertEqual(1, code, out)
        self.assertIn("routes to model 'sonnet'", out)

    def test_a_full_model_name_matches_its_family(self):
        code, out = self.lint(evidence_text("L7-build", model="claude-sonnet-5-5"))
        self.assertEqual(0, code, out)
        code, out = self.lint(evidence_text("L7-build", model="claude-opus-4-7"))
        self.assertEqual(1, code, out)

    def test_critical_units_route_their_build_gate_to_the_reviewer(self):
        design = json.loads((CONTRACTS / "fixtures" / "C01" / "valid-design-example.json").read_text(encoding="utf-8"))
        design = {k: v for k, v in design.items() if not k.startswith("_")}
        design["gates"]["critical_units"] = ["widget"]
        cfg = self.tmp / "batuta.json"
        cfg.write_text(json.dumps(design), encoding="utf-8")
        code, out = self.lint(evidence_text("L7-build"), "L7-build.md", "--config", str(cfg))
        self.assertEqual(1, code, out)
        code, out = self.lint(evidence_text("L7-build", role="reviewer", model="opus"), "L7-build.md", "--config", str(cfg))
        self.assertEqual(0, code, out)

    def test_file_name_must_name_the_gate(self):
        code, out = self.lint(evidence_text("L7-build"), "L8-integrate.md")
        self.assertEqual(1, code, out)

    def test_expected_gate_and_feature_are_checked_when_given(self):
        code, out = self.lint(evidence_text("L7-build"), "L7-build.md", "--gate", "L8-integrate")
        self.assertEqual(1, code, out)
        code, out = self.lint(evidence_text("L7-build"), "L7-build.md", "--feature", "002-other")
        self.assertEqual(1, code, out)

    def test_a_future_date_is_refused(self):
        code, out = self.lint(evidence_text("L7-build", date="2026-12-31"))
        self.assertEqual(1, code, out)
        self.assertIn("after today", out)

    def test_comments_are_stripped_before_reading(self):
        # an open major finding inside a comment does not count, and a findings table inside a comment is not a table
        commented = ("<!--\n| Id | Severity | Claim | Reproduction | Status |\n|---|---|---|---|---|\n"
                     "| F-9 | major | hidden | run x | open |\n-->\n")
        code, out = self.lint(evidence_text("L7-build", comment="<!-- why: example -->\n", extra_body=commented))
        self.assertEqual(0, code, out)
        text = evidence_text("L7-build").replace(
            "| Id | Severity | Claim | Reproduction | Status |\n|---|---|---|---|---|\n",
            "<!-- | Id | Severity | Claim | Reproduction | Status |\n|---|---|---|---|---|\n-->\n")
        code, out = self.lint(text)
        self.assertEqual(1, code, out)

    def test_front_matter_inside_a_comment_is_not_evidence(self):
        text = "<!--\n" + evidence_text("L7-build") + "\n-->\n"
        code, out = self.lint(text)
        self.assertEqual(1, code, out)

    def test_missing_file_is_a_failure(self):
        code, out = run("gate", "evidence-lint", str(self.tmp / "nope.md"), "--today", TODAY)
        self.assertEqual(1, code, out)

    def test_json_output_is_a_c20_object(self):
        code, out = self.lint(evidence_text("L7-build"), "L7-build.md", "--json")
        doc = json.loads(out)
        self.assertEqual(["batuta", "gate", "evidence-lint"], [doc["tool"], doc["area"], doc["verb"]])
        self.assertEqual(code, doc["exit_code"])


class StripComments(unittest.TestCase):
    def test_strip_keeps_line_count_and_fenced_code(self):
        from batuta_lib import evidence
        text = "a <!-- x --> b\n<!-- multi\nline -->\nc\n```\n<!-- kept -->\n```\n"
        out = evidence.strip_comments(text)
        self.assertEqual(text.count("\n"), out.count("\n"))
        self.assertIn("a  b", out)
        self.assertIn("<!-- kept -->", out)
        self.assertNotIn("multi", out)


if __name__ == "__main__":
    unittest.main()
