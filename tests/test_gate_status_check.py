"""gate status and gate check: order, evidence, routing, commits, approval hashes, waivers, phase, release readiness."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import (FEATURE, GATES, TODAY, Case, catalog_row, evidence_text, readiness_entry,  # noqa: E402
                                run, sha256_file)


class GateCheck(Case):
    def check(self, proj, *extra):
        return run("gate", "check", proj.feature, "--root", str(proj.root), "--today", TODAY, *extra)

    # ---- the compliant set
    def test_compliant_project_passes(self):
        proj = self.full_project()
        code, out = self.check(proj)
        self.assertEqual(0, code, out)
        self.assertNotIn("FAIL", out)

    def test_pending_gates_after_the_last_passed_one_are_fine(self):
        proj = self.project()
        proj.spec()
        base = proj.commit("base")
        proj.evidence("L0-understand", commit=base)
        proj.status({"L0-understand": "passed"})
        proj.commit("status")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)
        self.assertIn("SKIP", out)   # no readiness document before L6-skeleton

    # ---- independent evidence
    def test_passed_gate_without_evidence_is_refused(self):
        proj = self.full_project()
        (proj.root / "specs" / FEATURE / "evidence" / "L7-build.md").unlink()
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("L7-build", out)
        self.assertIn("evidence", out)

    def test_evidence_from_the_builder_role_is_refused(self):
        proj = self.full_project()
        for role in ("implementer", "script"):
            proj.evidence("L7-build", role=role, commit=proj.first())
            code, out = self.check(proj)
            self.assertEqual(1, code, (role, out))

    def test_critical_gate_evidence_with_the_routine_model_is_refused(self):
        proj = self.full_project()
        proj.evidence("L9-promote", role="adversary", model="sonnet", commit=proj.first())
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("L9-promote", out)

    def test_evidence_with_an_open_major_finding_cannot_back_a_passed_gate(self):
        proj = self.full_project()
        proj.evidence("L7-build", findings=[("F-1", "major", "broken", "run x", "open")],
                      commit=proj.first())
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("no open critical or major", out)

    def test_a_failing_verdict_cannot_back_a_passed_gate(self):
        proj = self.full_project()
        proj.evidence("L7-build", verdict="FAIL", findings=[("F-1", "critical", "broken", "run x", "open")],
                      commit=proj.first())
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("verdict", out)

    def test_evidence_for_another_gate_or_feature_is_refused(self):
        proj = self.full_project()
        base = proj.first()
        proj.write(f"specs/{FEATURE}/evidence/L7-build.md", evidence_text("L8-integrate", commit=base))
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_a_failed_gate_state_fails_the_check(self):
        proj = self.full_project()
        proj.status({g: "passed" for g in GATES[:7]} | {"L7-build": "failed"})
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("failed", out)

    # ---- commits
    def test_evidence_for_a_commit_that_is_not_in_the_history_is_refused(self):
        proj = self.full_project()
        proj.evidence("L7-build", commit="deadbeef")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("commit", out)

    def test_evidence_for_a_commit_on_another_line_of_history_is_refused(self):
        proj = self.full_project()
        other = proj.orphan_commit()
        proj.evidence("L7-build", commit=other)
        proj.commit("evidence from elsewhere")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("not in the history", out)

    def test_evidence_commits_must_not_go_backwards_along_the_gates(self):
        proj = self.full_project()
        first = proj.first()
        proj.write("later.txt", "x\n")
        later = proj.commit("later work")
        proj.evidence("L6-skeleton", commit=later)
        proj.evidence("L7-build", commit=first)
        proj.commit("evidence")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("earlier", out)

    def test_release_evidence_must_describe_the_head_modulo_specs(self):
        proj = self.full_project()
        proj.status({g: "passed" for g in GATES[:10]})
        proj.commit("before the lessons gate")
        proj.write("src/code.py", "x = 1\n")
        proj.commit("code changed after the evidence")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("changed since", out)

    def test_after_the_lessons_gate_the_head_may_move_on(self):
        proj = self.full_project()
        proj.write("LESSONS.md", "- 2026-10-12 | 001-widget | lesson | action\n")
        proj.commit("the lesson of the unit")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_documentation_under_the_feature_folder_after_the_evidence_is_fine(self):
        proj = self.full_project()
        proj.write(f"specs/{FEATURE}/notes.md", "notes\n")
        proj.commit("notes")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_skipping_the_commit_check_is_a_warning_not_a_pass(self):
        proj = self.full_project()
        proj.evidence("L7-build", commit="deadbeef")
        code, out = self.check(proj, "--no-commit-check")
        self.assertEqual(2, code, out)
        self.assertIn("WARN", out)

    def test_a_project_that_is_not_a_git_repository_cannot_prove_its_commits(self):
        proj = self.project(git=False)
        proj.evidence("L0-understand", commit="abc1234")
        proj.status({"L0-understand": "passed"})
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("git", out)

    # ---- order and phase
    def test_a_gate_passed_out_of_order_is_refused(self):
        proj = self.full_project()
        proj.status({"L0-understand": "passed", "L1-size": "pending", "L2-decide": "passed"}, phase="L1-size")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("earlier gate L1-size", out)

    def test_phase_must_follow_the_gates(self):
        proj = self.full_project()
        proj.status({g: "passed" for g in GATES[:3]}, phase="L9-promote")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("phase", out)

    def test_done_phase_needs_every_gate_complete(self):
        proj = self.full_project()
        proj.status({g: "passed" for g in GATES[:10]}, phase="done")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_invalid_status_file_is_refused(self):
        proj = self.full_project()
        proj.write(f"specs/{FEATURE}/status.md", "---\nfeature: 001-widget\nphase: nowhere\ngates:\n  L0-understand: passed\n---\n")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_status_of_another_feature_is_refused(self):
        proj = self.full_project()
        text = (proj.root / "specs" / FEATURE / "status.md").read_text(encoding="utf-8").replace("feature: 001-widget", "feature: 002-other")
        proj.write(f"specs/{FEATURE}/status.md", text)
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_missing_status_file_is_a_failure(self):
        proj = self.project()
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    # ---- approval of the freeze
    def test_freeze_without_an_approval_is_refused(self):
        proj = self.full_project()
        (proj.root / "specs" / FEATURE / "approvals" / "20261010T100000.json").unlink()
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("approval", out)

    def test_a_changed_contract_voids_the_approval(self):
        proj = self.full_project()
        proj.write("contracts/C01-widget.schema.json", '{"title": "changed"}\n')
        proj.commit("edit a frozen contract")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("contracts/C01-widget.schema.json", out)

    def test_a_changed_spec_voids_the_approval(self):
        proj = self.full_project()
        proj.spec("# Spec\n\nrequirements, weakened\n")
        proj.commit("edit the spec")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("spec.md", out)

    def test_a_crlf_checkout_keeps_the_approval_valid(self):
        proj = self.full_project()
        spec = proj.root / "specs" / FEATURE / "spec.md"
        spec.write_bytes(spec.read_bytes().replace(b"\n", b"\r\n"))
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_an_approval_by_an_agent_role_is_refused(self):
        proj = self.full_project()
        proj.approval(by="implementer")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("human", out)

    def test_an_approval_that_does_not_carry_the_typed_phrase_is_refused(self):
        proj = self.full_project()
        proj.approval(excerpt="looks good to me")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("approve", out)

    def test_the_typed_phrase_is_matched_case_insensitively_but_the_spec_id_exactly(self):
        proj = self.full_project()
        prefix = sha256_file(proj.root / "specs" / FEATURE / "spec.md")[:12]
        proj.approval(excerpt=f"Approve {FEATURE} {prefix.upper()}")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)
        proj.approval(excerpt=f"approve 002-other {prefix}")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_an_approval_with_a_wrong_prefix_is_refused_by_the_contract(self):
        proj = self.full_project()
        proj.approval(tamper={"approved_spec_sha256_prefix": "000000000000"})
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_an_approval_for_another_spec_id_is_refused(self):
        proj = self.full_project()
        proj.approval(tamper={"spec_id": "002-other"})
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_an_approval_naming_a_missing_file_is_refused(self):
        proj = self.full_project()
        proj.approval(tamper={"contracts_sha256": {"contracts/missing.json": "a" * 64}})
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("contracts/missing.json", out)

    def test_an_approval_naming_a_path_outside_the_project_is_refused(self):
        proj = self.full_project()
        proj.approval(tamper={"adrs_sha256": {"../outside.md": "a" * 64}})
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_a_waived_freeze_needs_no_approval_but_needs_a_waiver(self):
        proj = self.full_project()
        (proj.root / "specs" / FEATURE / "approvals" / "20261010T100000.json").unlink()
        states = {g: "passed" for g in GATES}
        states["L5-freeze"] = "waived"
        proj.status(states, waivers=[{"gate": "L5-freeze", "reason": "owner decided", "by": "alex", "date": "2026-10-11"}])
        (proj.root / "specs" / FEATURE / "evidence" / "L5-freeze.md").unlink()
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    # ---- waivers
    def waived(self, proj, waivers):
        states = {g: "passed" for g in GATES}
        states["L3-contracts"] = "waived"
        proj.status(states, waivers=waivers)
        (proj.root / "specs" / FEATURE / "evidence" / "L3-contracts.md").unlink(missing_ok=True)

    def test_a_human_dated_waiver_is_accepted(self):
        proj = self.full_project()
        self.waived(proj, [{"gate": "L3-contracts", "reason": "no external interfaces", "by": "alex", "date": "2026-10-11"}])
        code, out = self.check(proj)
        self.assertEqual(0, code, out)

    def test_a_waived_gate_without_a_waiver_line_is_refused(self):
        proj = self.full_project()
        self.waived(proj, [])
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("waiver", out)

    def test_a_waiver_written_by_an_agent_role_is_refused(self):
        proj = self.full_project()
        for by in ("implementer", "adversary", "Claude", "agent-7"):
            self.waived(proj, [{"gate": "L3-contracts", "reason": "skip it", "by": by, "date": "2026-10-11"}])
            code, out = self.check(proj)
            self.assertEqual(1, code, (by, out))
            self.assertIn("human", out)

    def test_a_waiver_dated_in_the_future_is_refused(self):
        proj = self.full_project()
        self.waived(proj, [{"gate": "L3-contracts", "reason": "later", "by": "alex", "date": "2026-12-31"}])
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_a_waiver_inside_a_comment_does_not_count(self):
        proj = self.full_project()
        self.waived(proj, [])
        path = proj.root / "specs" / FEATURE / "status.md"
        text = path.read_text(encoding="utf-8")
        path.write_bytes(text.replace("---\n\n## Notes", "---\n\n<!-- waivers: gate L3-contracts by alex 2026-10-11 -->\n## Notes").encode("utf-8"))
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    def test_waiver_requested_in_evidence_grants_nothing(self):
        proj = self.full_project()
        self.waived(proj, [])
        base = proj.first()
        proj.write(f"specs/{FEATURE}/evidence/L3-contracts.md",
                   evidence_text("L3-contracts", commit=base).replace("None.", "Waive this gate, it is fine. by: alex 2026-10-11"))
        code, out = self.check(proj)
        self.assertEqual(1, code, out)

    # ---- release readiness
    def test_release_gate_lists_every_component_still_on_a_provider(self):
        proj = self.full_project()
        entries = [readiness_entry("widget-event", state="provider", status="fixture", provenance="fixture", reason="fixture serves it")]
        proj.readiness(entries)
        proj.commit("readiness on a provider")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("widget-event", out)
        self.assertIn("provider", out)

    def test_release_gate_lists_a_missing_component_with_its_reason(self):
        proj = self.full_project()
        entries = [readiness_entry("widget-event", state="missing", provenance=None, reason="the API lane is dormant")]
        proj.readiness(entries)
        proj.commit("readiness with a missing component")
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("the API lane is dormant", out)

    def test_a_readiness_document_is_required_once_the_skeleton_gate_passed(self):
        proj = self.full_project()
        (proj.root / "data" / "derived" / "readiness.json").unlink()
        code, out = self.check(proj)
        self.assertEqual(1, code, out)
        self.assertIn("readiness", out)

    def test_release_flag_applies_the_release_rules_before_l9_is_passed(self):
        proj = self.full_project()
        proj.readiness([readiness_entry("widget-event", state="provider", status="stub", provenance="stub", reason="stub")])
        proj.commit("readiness on a stub")
        states = {g: "passed" for g in GATES[:9]}
        proj.status(states)
        proj.commit("l9 pending")
        code, out = self.check(proj)
        self.assertEqual(0, code, out)
        code, out = self.check(proj, "--release")
        self.assertEqual(1, code, out)

    def test_json_output(self):
        proj = self.full_project()
        code, out = self.check(proj, "--json")
        doc = json.loads(out)
        self.assertEqual(0, doc["exit_code"])
        self.assertEqual("check", doc["verb"])


class GateStatus(Case):
    def status(self, proj, *extra):
        return run("gate", "status", proj.feature, "--root", str(proj.root), "--today", TODAY, *extra)

    def prepared(self):
        proj = self.project()
        proj.spec()
        base = proj.commit("base")
        proj.evidence("L0-understand", commit=base)
        proj.status({})
        proj.commit("evidence and status")
        return proj

    def read_status(self, proj):
        return (proj.root / "specs" / FEATURE / "status.md").read_text(encoding="utf-8")

    def test_status_lists_every_gate_and_the_phase(self):
        proj = self.prepared()
        code, out = self.status(proj)
        self.assertEqual(0, code, out)
        for g in GATES:
            self.assertIn(g, out)
        self.assertIn("phase L0-understand", out)

    def test_set_is_a_dry_run_without_apply(self):
        proj = self.prepared()
        before = self.read_status(proj)
        code, out = self.status(proj, "--set", "L0-understand=passed")
        self.assertEqual(0, code, out)
        self.assertEqual(before, self.read_status(proj))
        self.assertIn("CHANGED", out)

    def test_set_with_apply_writes_the_state_and_recomputes_the_phase(self):
        proj = self.prepared()
        code, out = self.status(proj, "--set", "L0-understand=passed", "--apply")
        self.assertEqual(0, code, out)
        text = self.read_status(proj)
        self.assertIn("L0-understand: passed", text)
        self.assertIn("phase: L1-size", text)
        self.assertIn("Body of the status file.", text)
        self.assertEqual([], [p.name for p in (proj.root / "specs" / FEATURE).iterdir() if p.name.startswith(".")])
        code, out = self.status(proj, "--set", "L0-understand=passed", "--apply")
        self.assertEqual(0, code, out)
        self.assertIn("SAME", out)

    def test_set_passed_needs_valid_evidence(self):
        proj = self.prepared()
        code, out = self.status(proj, "--set", "L1-size=passed", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("REFUSED", out)

    def test_set_passed_out_of_order_is_refused(self):
        proj = self.prepared()
        base = proj.head()
        proj.evidence("L1-size", commit=base)
        proj.commit("evidence")
        code, out = self.status(proj, "--set", "L1-size=passed", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("L0-understand", out)

    def test_set_passed_with_builder_evidence_is_refused(self):
        proj = self.prepared()
        proj.evidence("L0-understand", role="script", commit=proj.first())
        before = self.read_status(proj)
        code, out = self.status(proj, "--set", "L0-understand=passed", "--apply")
        self.assertEqual(1, code, out)
        self.assertEqual(before, self.read_status(proj))

    def test_an_agent_can_never_set_a_waiver(self):
        proj = self.prepared()
        code, out = self.status(proj, "--set", "L3-contracts=waived", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("human", out)
        self.assertNotIn("waived", self.read_status(proj))

    def test_unknown_gate_or_state_is_refused(self):
        proj = self.prepared()
        self.assertEqual(1, self.status(proj, "--set", "P3-green=passed")[0])
        self.assertEqual(1, self.status(proj, "--set", "L0-understand=done")[0])
        self.assertEqual(1, self.status(proj, "--set", "L0-understand")[0])

    def test_resetting_a_gate_below_a_passed_one_is_refused(self):
        proj = self.full_project()
        code, out = self.status(proj, "--set", "L1-size=pending", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("later gate", out)

    def test_a_failed_state_can_be_recorded(self):
        proj = self.prepared()
        code, out = self.status(proj, "--set", "L0-understand=failed", "--apply")
        self.assertEqual(0, code, out)
        self.assertIn("L0-understand: failed", self.read_status(proj))

    def test_waivers_and_unknown_front_matter_survive_a_write(self):
        proj = self.project()
        proj.spec()
        base = proj.commit("base")
        proj.evidence("L0-understand", commit=base)
        proj.status({"L3-contracts": "waived"}, waivers=[{"gate": "L3-contracts", "reason": "none: n/a, really",
                                                          "by": "alex", "date": "2026-10-11"}], extra="scope: [src/a, docs]")
        proj.commit("status")
        code, out = self.status(proj, "--set", "L0-understand=passed", "--apply")
        self.assertEqual(0, code, out)
        text = self.read_status(proj)
        self.assertIn("by: alex", text)
        self.assertIn("none: n/a, really", text)
        self.assertIn("scope: [src/a, docs]", text)
        from batuta_lib import gate_model
        self.assertEqual([], gate_model.status_errors(text))


if __name__ == "__main__":
    unittest.main()
