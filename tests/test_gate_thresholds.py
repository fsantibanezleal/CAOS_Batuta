"""gate thresholds: the ratchet. A value only goes up; a decrease needs a history entry and a same-date C10 waiver."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import FEATURE, TODAY, Case, run  # noqa: E402

PATH = "specs/000-foundation/thresholds.json"


def doc(values, history=()):
    return json.dumps({"contract_version": "1.0", "values": values, "history": list(history)}, indent=2) + "\n"


def entry(date, name, frm, to, reason="calibrated"):
    return {"date": date, "name": name, "from": frm, "to": to, "reason": reason}


class Thresholds(Case):
    def setUp(self):
        super().setUp()
        self.proj = self.project()
        self.root = self.proj.root

    def thresholds(self, *extra):
        return run("gate", "thresholds", "--root", str(self.root), "--today", TODAY, *extra)

    def put(self, text):
        self.proj.write(PATH, text)

    def waiver(self, date=TODAY, by="alex", gate="L9-promote"):
        self.proj.status({}, waivers=[{"gate": gate, "reason": "calibration was wrong", "by": by, "date": date}])

    def read(self):
        return json.loads((self.root / PATH).read_text(encoding="utf-8"))

    # ---- check
    def test_a_valid_file_passes(self):
        self.put(doc({"coverage": 80}, [entry("2026-10-01", "coverage", 70, 80)]))
        code, out = self.thresholds("--check")
        self.assertEqual(0, code, out)

    def test_missing_file_is_skipped(self):
        code, out = self.thresholds("--check")
        self.assertEqual(0, code, out)
        self.assertIn("SKIP", out)

    def test_an_invalid_file_is_refused(self):
        self.put('{"contract_version": "1.0", "values": {"a": "high"}, "history": []}\n')
        code, out = self.thresholds("--check")
        self.assertEqual(1, code, out)

    def test_a_value_changed_without_a_history_entry_is_refused(self):
        self.put(doc({"coverage": 60}, [entry("2026-10-01", "coverage", 70, 80)]))
        code, out = self.thresholds("--check")
        self.assertEqual(1, code, out)
        self.assertIn("coverage", out)
        self.assertIn("history", out)

    def test_a_lowered_threshold_without_a_waiver_is_refused(self):
        self.put(doc({"coverage": 70}, [entry("2026-10-01", "coverage", 80, 70)]))
        code, out = self.thresholds("--check")
        self.assertEqual(1, code, out)
        self.assertIn("waiver", out)

    def test_a_lowered_threshold_with_a_same_date_human_waiver_is_accepted(self):
        self.put(doc({"coverage": 70}, [entry("2026-10-01", "coverage", 80, 70)]))
        self.waiver(date="2026-10-01")
        code, out = self.thresholds("--check")
        self.assertEqual(0, code, out)

    def test_a_waiver_of_another_date_does_not_cover_the_decrease(self):
        self.put(doc({"coverage": 70}, [entry("2026-10-01", "coverage", 80, 70)]))
        self.waiver(date="2026-10-02")
        code, out = self.thresholds("--check")
        self.assertEqual(1, code, out)

    def test_a_waiver_by_an_agent_role_does_not_cover_the_decrease(self):
        self.put(doc({"coverage": 70}, [entry("2026-10-01", "coverage", 80, 70)]))
        self.waiver(date="2026-10-01", by="implementer")
        code, out = self.thresholds("--check")
        self.assertEqual(1, code, out)

    def test_raised_then_lowered_in_one_day_without_a_waiver_is_refused(self):
        self.put(doc({"coverage": 70}, [entry(TODAY, "coverage", 70, 80), entry(TODAY, "coverage", 80, 70)]))
        code, out = self.thresholds("--check")
        self.assertEqual(1, code, out)

    def test_a_broken_history_chain_is_refused(self):
        self.put(doc({"coverage": 90}, [entry("2026-10-01", "coverage", 70, 80), entry("2026-10-02", "coverage", 85, 90)]))
        code, out = self.thresholds("--check")
        self.assertEqual(1, code, out)
        self.assertIn("chain", out)

    def test_history_dates_never_go_backwards(self):
        self.put(doc({"coverage": 90}, [entry("2026-10-05", "coverage", 70, 80), entry("2026-10-02", "coverage", 80, 90)]))
        code, out = self.thresholds("--check")
        self.assertEqual(1, code, out)

    def test_against_a_committed_baseline_catches_a_silent_lowering(self):
        self.put(doc({"coverage": 80}))
        self.proj.commit("baseline")
        self.put(doc({"coverage": 70}))
        code, out = self.thresholds("--check")
        self.assertEqual(0, code, out)           # nothing in the file itself shows the lowering
        code, out = self.thresholds("--check", "--against", "HEAD")
        self.assertEqual(1, code, out)
        self.assertIn("lowered", out)

    def test_against_a_baseline_a_removed_threshold_is_refused(self):
        self.put(doc({"coverage": 80, "mutation": 50}))
        self.proj.commit("baseline")
        self.put(doc({"coverage": 80}))
        code, out = self.thresholds("--check", "--against", "HEAD")
        self.assertEqual(1, code, out)
        self.assertIn("mutation", out)

    def test_against_a_baseline_the_history_must_only_grow(self):
        self.put(doc({"coverage": 80}, [entry("2026-10-01", "coverage", 70, 80)]))
        self.proj.commit("baseline")
        self.put(doc({"coverage": 80}, []))
        code, out = self.thresholds("--check", "--against", "HEAD")
        self.assertEqual(1, code, out)
        self.assertIn("history", out)

    # ---- propose
    def test_a_raise_is_recorded_in_the_history(self):
        self.put(doc({"coverage": 70}))
        code, out = self.thresholds("--propose", "coverage=80", "--reason", "measured 83 percent")
        self.assertEqual(0, code, out)
        self.assertEqual(70, self.read()["values"]["coverage"])          # dry run
        code, out = self.thresholds("--propose", "coverage=80", "--reason", "measured 83 percent", "--apply")
        self.assertEqual(0, code, out)
        written = self.read()
        self.assertEqual(80, written["values"]["coverage"])
        self.assertEqual([entry(TODAY, "coverage", 70, 80, "measured 83 percent")], written["history"])
        code, out = self.thresholds("--propose", "coverage=80", "--apply")
        self.assertEqual(0, code, out)
        self.assertIn("SAME", out)
        self.assertEqual(1, len(self.read()["history"]))

    def test_a_new_threshold_is_added(self):
        self.put(doc({"coverage": 70}))
        code, out = self.thresholds("--propose", "mutation=40", "--apply")
        self.assertEqual(0, code, out)
        self.assertEqual({"coverage": 70, "mutation": 40}, self.read()["values"])

    def test_a_lowering_is_refused_without_a_waiver(self):
        self.put(doc({"coverage": 80}))
        before = (self.root / PATH).read_text(encoding="utf-8")
        code, out = self.thresholds("--propose", "coverage=70", "--reason", "too strict", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("REFUSED", out)
        self.assertEqual(before, (self.root / PATH).read_text(encoding="utf-8"))

    def test_raise_then_attempted_lower_in_one_day_is_refused(self):
        self.put(doc({"coverage": 70}))
        self.assertEqual(0, self.thresholds("--propose", "coverage=80", "--reason", "up", "--apply")[0])
        code, out = self.thresholds("--propose", "coverage=70", "--reason", "down again", "--apply")
        self.assertEqual(1, code, out)
        self.assertEqual(80, self.read()["values"]["coverage"])

    def test_a_lowering_with_a_same_date_waiver_and_a_reason_is_written(self):
        self.put(doc({"coverage": 80}))
        self.waiver()
        code, out = self.thresholds("--propose", "coverage=70", "--reason", "the suite changed", "--apply")
        self.assertEqual(0, code, out)
        written = self.read()
        self.assertEqual(70, written["values"]["coverage"])
        self.assertEqual(entry(TODAY, "coverage", 80, 70, "the suite changed"), written["history"][-1])
        code, out = self.thresholds("--check")
        self.assertEqual(0, code, out)

    def test_a_lowering_needs_a_reason(self):
        self.put(doc({"coverage": 80}))
        self.waiver()
        code, out = self.thresholds("--propose", "coverage=70", "--apply")
        self.assertEqual(1, code, out)
        self.assertIn("reason", out)

    def test_a_non_numeric_value_is_refused(self):
        self.put(doc({"coverage": 80}))
        for bad in ("coverage=high", "coverage", "coverage=NaN", "=5"):
            self.assertEqual(1, self.thresholds("--propose", bad, "--apply")[0], bad)

    def test_a_first_threshold_creates_the_file(self):
        code, out = self.thresholds("--propose", "coverage=70", "--apply")
        self.assertEqual(0, code, out)
        self.assertEqual({"contract_version": "1.0", "values": {"coverage": 70}, "history": []}, self.read())

    def test_check_and_propose_are_exclusive(self):
        with self.assertRaises(SystemExit):
            self.thresholds("--check", "--propose", "coverage=1")

    def test_no_mode_means_check(self):
        self.put(doc({"coverage": 80}))
        code, out = self.thresholds()
        self.assertEqual(0, code, out)
        self.assertIn("OK", out)


if __name__ == "__main__":
    unittest.main()
