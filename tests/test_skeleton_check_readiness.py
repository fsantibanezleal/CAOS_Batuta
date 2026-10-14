"""skeleton check: the readiness document (C27) is current and states what is real; previews (C29); contract tests."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import Case, catalog_row, readiness_entry, run  # noqa: E402

TESTS = ("tests/test_widget_producer.py", "tests/test_widget_consumer.py")


def record(proj, results=None):
    results = results or {t: "pass" for t in TESTS}
    p = proj.root / "docs" / "design" / "contract-tests.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"contract_version": "1.0", "commit": proj.head(), "generated": "2026-10-12", "results": results}), encoding="utf-8")
    return p


class SkeletonCheck(Case):
    def setUp(self):
        super().setUp()
        self.proj = self.project()
        self.proj.catalog()
        self.proj.readiness()
        self.proj.commit("skeleton")

    def check(self, *extra, recorded=True):
        args = ["skeleton", "check", "--root", str(self.proj.root)]
        if recorded:
            args += ["--tests-record", str(record(self.proj))]
        return run(*args, *extra)

    def set_readiness(self, entries, **kw):
        self.proj.readiness(entries, **kw)
        self.proj.commit("readiness")

    # ---- the readiness document
    def test_a_current_readiness_with_real_components_passes(self):
        code, out = self.check()
        self.assertEqual(0, code, out)
        self.assertIn("widget-event", out)

    def test_no_readiness_document_before_the_skeleton_gate_is_a_skip(self):
        (self.proj.root / "data" / "derived" / "readiness.json").unlink()
        code, out = self.check()
        self.assertEqual(0, code, out)
        self.assertIn("SKIP", out)

    def test_require_turns_the_missing_document_into_a_failure(self):
        (self.proj.root / "data" / "derived" / "readiness.json").unlink()
        code, out = self.check("--require")
        self.assertEqual(1, code, out)

    def test_the_second_default_location_is_found(self):
        (self.proj.root / "data" / "derived" / "readiness.json").unlink()
        self.proj.readiness(path="docs/design/readiness.json")
        self.proj.commit("moved")
        self.assertEqual(0, self.check()[0])

    def test_an_invalid_document_is_refused_for_its_stated_rule(self):
        self.set_readiness([readiness_entry("widget-event", state="available", reason="should be null")])
        code, out = self.check()
        self.assertEqual(1, code, out)
        self.assertIn("reason", out)

    def test_a_document_that_is_not_json_is_refused(self):
        self.proj.write("data/derived/readiness.json", "{nope")
        code, out = self.check()
        self.assertEqual(1, code, out)

    def test_a_stale_catalog_hash_is_refused(self):
        self.set_readiness([readiness_entry("widget-event")], sha="0" * 64)
        code, out = self.check()
        self.assertEqual(1, code, out)
        self.assertIn("stale", out)

    def test_a_catalog_row_without_a_readiness_entry_is_refused(self):
        self.proj.catalog([catalog_row("widget-event"), catalog_row("widget-list")])
        self.proj.readiness()
        self.proj.commit("a second row")
        code, out = self.check()
        self.assertEqual(1, code, out)
        self.assertIn("widget-list", out)

    def test_a_readiness_entry_that_is_not_a_catalog_row_is_refused(self):
        self.set_readiness([readiness_entry("widget-event"), readiness_entry("ghost")])
        code, out = self.check()
        self.assertEqual(1, code, out)
        self.assertIn("ghost", out)

    def test_a_version_that_differs_from_the_catalog_is_refused(self):
        self.set_readiness([readiness_entry("widget-event", version="2.0.0")])
        code, out = self.check()
        self.assertEqual(1, code, out)
        self.assertIn("version", out)

    def test_a_readiness_behind_the_head_by_code_commits_is_refused_unless_the_lag_allows_it(self):
        self.proj.write("src/code.py", "x = 1\n")
        self.proj.commit("code after the readiness")
        code, out = self.check()
        self.assertEqual(1, code, out)
        self.assertIn("behind", out)
        self.assertEqual(0, self.check("--lag", "1")[0])

    def test_records_under_specs_do_not_age_the_readiness(self):
        self.proj.write("specs/001-widget/notes.md", "n\n")
        self.proj.commit("notes")
        self.assertEqual(0, self.check()[0])

    def test_an_uncommitted_readiness_is_a_warning(self):
        path = self.proj.root / "data" / "derived" / "readiness.json"
        self.proj.write("data/derived/readiness.json", path.read_text(encoding="utf-8") + "\n")
        code, out = self.check()
        self.assertEqual(2, code, out)
        self.assertIn("uncommitted", out)

    def test_outside_a_git_repository_the_age_cannot_be_checked(self):
        self.proj.fake.enabled = False
        code, out = run("skeleton", "check", "--root", str(self.proj.root))
        self.assertEqual(2, code, out)
        self.assertIn("WARN", out)

    # ---- providers
    def test_components_on_a_provider_are_listed_with_their_provenance_and_pass_before_release(self):
        entries = [readiness_entry("widget-event", state="provider", status="fixture", provenance="fixture",
                                   reason={"en": "the fixture answers"})]
        self.set_readiness(entries)
        code, out = self.check()
        self.assertEqual(0, code, out)
        self.assertIn("provider", out)
        self.assertIn("fixture", out)

    def test_release_lists_every_provider_component_as_a_gap(self):
        entries = [readiness_entry("widget-event", state="provider", status="stub", provenance="stub", reason="stub answers")]
        self.set_readiness(entries)
        code, out = self.check("--release")
        self.assertEqual(1, code, out)
        self.assertIn("gap", out)
        self.assertIn("widget-event", out)
        self.assertIn("stub", out)

    def test_release_lists_a_missing_component_with_its_reason(self):
        self.set_readiness([readiness_entry("widget-event", state="missing", provenance=None, reason="the feed is dormant")])
        code, out = self.check("--release")
        self.assertEqual(1, code, out)
        self.assertIn("the feed is dormant", out)

    def test_release_gaps_cover_partial_stale_and_a_training_model_on_its_baseline(self):
        for state, status, prov, reason, missing in (
                ("partial", "real", "real", "two of three files", ["data/b.csv"]),
                ("stale", "real", "real", "bake is old", []),
                ("training", "real", "baseline", "baseline answers while it trains", [])):
            self.set_readiness([readiness_entry("widget-event", state=state, status=status, provenance=prov,
                                                reason=reason, missing=missing)])
            code, out = self.check("--release")
            self.assertEqual(1, code, (state, out))

    def test_a_training_model_answered_by_the_released_version_is_not_a_gap(self):
        self.set_readiness([readiness_entry("widget-event", state="training", provenance="real", reason="1.2.0 answers while 1.3.0 trains")])
        self.assertEqual(0, self.check("--release")[0])

    def test_release_with_every_component_real_passes(self):
        self.assertEqual(0, self.check("--release")[0])

    # ---- contract tests
    def test_without_a_recorded_test_status_the_check_is_an_honest_partial(self):
        code, out = self.check(recorded=False)
        self.assertEqual(2, code, out)
        self.assertIn("no contract test status", out)

    def test_a_recorded_failure_is_refused(self):
        rec = record(self.proj, {TESTS[0]: "pass", TESTS[1]: "fail"})
        code, out = run("skeleton", "check", "--root", str(self.proj.root), "--tests-record", str(rec))
        self.assertEqual(1, code, out)
        self.assertIn(TESTS[1], out)

    def test_a_test_file_the_catalog_names_must_exist(self):
        (self.proj.root / TESTS[0]).unlink()
        self.proj.commit("remove a test")
        code, out = self.check()
        self.assertEqual(1, code, out)
        self.assertIn(TESTS[0], out)

    def test_a_test_missing_from_the_record_is_a_warning(self):
        rec = record(self.proj, {TESTS[0]: "pass"})
        code, out = run("skeleton", "check", "--root", str(self.proj.root), "--tests-record", str(rec))
        self.assertEqual(2, code, out)

    # ---- previews
    def previews(self, entries, name="previews.json"):
        p = self.proj.root / "docs" / "design" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"contract_version": "1.0", "entries": entries}), encoding="utf-8")
        return p

    def entry(self, **kw):
        base = {"env": "preview", "url": "https://preview.example.org/", "commit": self.proj.head(),
                "providers": {"widget-event": "fixture"}, "date": "2026-10-12"}
        base.update(kw)
        return base

    def test_a_preview_record_is_validated_and_the_network_stays_off_by_default(self):
        p = self.previews([self.entry()])
        with mock.patch("batuta_lib.readiness.fetch_status") as fetch:
            code, out = self.check("--previews", str(p))
        self.assertEqual(0, code, out)
        fetch.assert_not_called()
        self.assertIn("preview.example.org", out)

    def test_an_invalid_preview_record_is_refused(self):
        p = self.previews([{"env": "preview"}])
        code, out = self.check("--previews", str(p))
        self.assertEqual(1, code, out)

    def test_an_empty_preview_record_is_a_warning(self):
        code, out = self.check("--previews", str(self.previews([])))
        self.assertEqual(2, code, out)

    def test_a_preview_for_another_commit_is_a_warning(self):
        code, out = self.check("--previews", str(self.previews([self.entry(commit="1234567")])))
        self.assertEqual(2, code, out)
        self.assertIn("commit", out)

    def test_the_network_check_reaches_the_url_when_asked(self):
        p = self.previews([self.entry()])
        with mock.patch("batuta_lib.readiness.fetch_status", return_value=200) as fetch:
            code, out = self.check("--previews", str(p), "--check-network")
        self.assertEqual(0, code, out)
        fetch.assert_called_once()
        self.assertEqual("https://preview.example.org/", fetch.call_args[0][0])

    def test_an_unreachable_preview_is_refused(self):
        p = self.previews([self.entry()])
        for status in (500, 404, None):
            with mock.patch("batuta_lib.readiness.fetch_status", return_value=status):
                code, out = self.check("--previews", str(p), "--check-network")
            self.assertEqual(1, code, (status, out))
            self.assertIn("unreachable", out)

    def test_an_url_given_directly_is_checked_only_with_the_flag(self):
        with mock.patch("batuta_lib.readiness.fetch_status", return_value=200) as fetch:
            self.assertEqual(0, self.check("--url", "https://x.example.org/")[0])
            fetch.assert_not_called()
            self.assertEqual(0, self.check("--url", "https://x.example.org/", "--check-network")[0])
            fetch.assert_called_once()

    def test_only_http_urls_are_fetched(self):
        with mock.patch("batuta_lib.readiness.fetch_status") as fetch:
            code, out = self.check("--url", "file:///etc/passwd", "--check-network")
        self.assertEqual(1, code, out)
        fetch.assert_not_called()

    def test_json_output(self):
        code, out = self.check("--json")
        doc = json.loads(out)
        self.assertEqual(["skeleton", "check"], [doc["area"], doc["verb"]])


if __name__ == "__main__":
    unittest.main()
