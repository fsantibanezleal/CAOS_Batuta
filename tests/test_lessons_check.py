"""lessons check: every unit with a passed L7-build has a C19 line in LESSONS.md."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_fixtures import FEATURE, GATES, TODAY, Case, run  # noqa: E402

LINE = f"- 2026-10-12 | {FEATURE} | the checker needs a fixture per refusal | added one fixture per rule"


class LessonsCheck(Case):
    def setUp(self):
        super().setUp()
        self.proj = self.project(git=False)
        self.proj.status({g: "passed" for g in GATES[:8]})

    def lessons(self, text):
        self.proj.write("LESSONS.md", text)

    def check(self, *extra):
        return run("lessons", "check", "--root", str(self.proj.root), "--today", TODAY, *extra)

    def test_a_unit_with_a_lesson_line_passes(self):
        self.lessons("# Lessons\n\n" + LINE + "\n")
        code, out = self.check()
        self.assertEqual(0, code, out)
        self.assertIn(FEATURE, out)

    def test_a_unit_without_a_lesson_line_is_refused(self):
        self.lessons("# Lessons\n\n- 2026-10-12 | 002-other | a lesson | an action\n")
        code, out = self.check()
        self.assertEqual(1, code, out)
        self.assertIn(FEATURE, out)
        self.assertIn("MISSING", out)

    def test_no_lessons_file_is_refused_when_a_unit_finished_its_build(self):
        code, out = self.check()
        self.assertEqual(1, code, out)

    def test_a_unit_whose_build_is_not_passed_needs_no_lesson(self):
        self.proj.status({g: "passed" for g in GATES[:7]})
        self.assertEqual(0, self.check()[0])

    def test_no_units_and_no_file_is_fine(self):
        (self.proj.root / "specs" / FEATURE / "status.md").unlink()
        self.assertEqual(0, self.check()[0])

    def test_the_slug_of_the_feature_also_names_the_unit(self):
        self.lessons("- 2026-10-12 | widget | lesson | action\n")
        self.assertEqual(0, self.check()[0])

    def test_a_line_that_starts_with_a_date_must_satisfy_c19(self):
        for bad in ("- 2026-10-12 | 001-widget | lesson only",
                    "- 2026-10-12 | 001-widget | lesson | action | extra",
                    "- 2026-13-40 | 001-widget | lesson | action",
                    "- 2026-10-12 |  | lesson | action"):
            self.lessons(bad + "\n")
            code, out = self.check()
            self.assertEqual(1, code, (bad, out))

    def test_a_plain_bullet_is_ignored_with_a_warning(self):
        self.lessons("## 2026-10-11, U1\n\n- A scaffold must not claim checks it lacks.\n" + LINE + "\n")
        code, out = self.check()
        self.assertEqual(2, code, out)
        self.assertIn("WARN", out)

    def test_a_lesson_dated_in_the_future_is_refused(self):
        self.lessons("- 2026-12-31 | 001-widget | lesson | action\n")
        self.assertEqual(1, self.check()[0])

    def test_several_units_each_need_their_own_line(self):
        other =self.proj.root / "specs" / "002-other"
        other.mkdir(parents=True)
        (other / "status.md").write_bytes((self.proj.root / "specs" / FEATURE / "status.md").read_bytes().replace(b"001-widget", b"002-other"))
        self.lessons(LINE + "\n")
        code, out = self.check()
        self.assertEqual(1, code, out)
        self.assertIn("002-other", out)
        self.lessons(LINE + "\n- 2026-10-12 | 002-other | lesson | action\n")
        self.assertEqual(0, self.check()[0])

    def test_an_unreadable_status_file_is_a_warning_not_a_crash(self):
        bad = self.proj.root / "specs" / "003-broken"
        bad.mkdir(parents=True)
        (bad / "status.md").write_text("garbage\n", encoding="utf-8")
        self.lessons(LINE + "\n")
        code, out = self.check()
        self.assertEqual(2, code, out)

    def test_an_explicit_lessons_path_is_used(self):
        self.proj.write("docs/MY-LESSONS.md", LINE + "\n")
        self.assertEqual(0, self.check("--lessons", "docs/MY-LESSONS.md")[0])
        self.assertEqual(1, self.check()[0])

    def test_json_output(self):
        self.lessons(LINE + "\n")
        code, out = self.check("--json")
        self.assertEqual(["lessons", "check"], [json.loads(out)["area"], json.loads(out)["verb"]])


if __name__ == "__main__":
    unittest.main()
