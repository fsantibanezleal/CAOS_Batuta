"""Every refusal of the lifecycle, shown refusing, through the public command line or a C16 hook payload.

One test each: a brief with an unfilled slot, an approval typed with a wrong prefix, an edit of a locked test, a green
commit that touches a locked path, a weakened test, a gate without evidence, a promotion before the head is proven green,
an automation command, and a secret-shaped string. Each test also shows the near miss that must NOT be refused, so a
guard that denies everything cannot pass. The project is built once (to the green commit) and cloned per test.
"""
from __future__ import annotations

import unittest

import e2e_world as ew
from e2e_world import FEATURE, TASK, TEST_PATH, RefusalCase


class RefusalTests(RefusalCase):
    def test_a_brief_with_an_unfilled_slot_is_refused_by_lint(self):
        world = self.fresh()
        made = self.ok(world.batuta("brief", "new", "--slug", "scratch", "--topic", "probe", "--agent", "implementer",
                                    "--title", "Probe"), "NEW brief")
        briefs = sorted(world.path(".batuta/delegation").glob("probe-*.brief.md"))
        self.assertEqual(len(briefs), 1, made.describe())
        refused = self.refused(world.batuta("brief", "lint", briefs[0].relative_to(world.project).as_posix()),
                               "FAIL", "not filled", "LINT FAILED")
        self.assertIn("<fill", refused.text, refused.describe())

    def test_an_approval_typed_with_a_wrong_prefix_is_refused(self):
        world = self.fresh()

        def records():
            return sorted(p.name for p in world.path("specs/%s/approvals" % FEATURE).iterdir())

        before = records()
        phrase = ew.approval_phrase(self, world)
        word, slug, prefix = phrase.split(" ")
        # a stale prefix is refused out loud and names the current one
        stale = world.hook("spec-approval", world.prompt_payload("%s %s %s" % (word, slug, "0" * 12)))
        self.assertEqual(stale.rc, 0, stale.describe())
        self.assertIn("REFUSED", stale.out, stale.describe())
        self.assertIn(prefix, stale.out, stale.describe())
        # a phrase that does not start with the typed word is not an approval: nothing recorded
        for typed in ("%sd %s %s" % (word, slug, prefix), "please %s" % phrase):
            ignored = world.hook("spec-approval", world.prompt_payload(typed))
            self.assertEqual(ignored.rc, 0, ignored.describe())
            self.assertNotIn("approval recorded", ignored.out, ignored.describe())
        self.assertEqual(records(), before, "a refused approval must write no record")

    def test_an_edit_of_a_locked_test_is_denied_by_the_guard_payload(self):
        world = self.fresh()
        target = str(world.path(TEST_PATH))
        for tool, tool_input in (("Edit", {"file_path": target, "old_string": "Ada", "new_string": "Bob"}),
                                 ("Write", {"file_path": target, "content": "pass\n"})):
            denial = self.assertDenied(world.hook("guard-locked-tests", world.pretool_payload(tool, tool_input)))
            self.assertIn("locked test", denial)
        free = world.hook("guard-locked-tests", world.pretool_payload(
            "Edit", {"file_path": str(world.path("greeter.py")), "old_string": "Hello", "new_string": "Hi"}))
        self.assertAllowed(free)
        self.assertEqual(world.read(TEST_PATH), ew.GREETER_TEST, "the guard is a decision: it never edits")

    def test_a_green_commit_touching_a_locked_path_fails_the_tdd_check(self):
        world = self.fresh()
        world.write(TEST_PATH, world.read(TEST_PATH) + "\n# a tweak\n")
        self.refused(world.batuta("tdd", "commit", "--green", TASK, "-m", "tweak", TEST_PATH, "--apply"),
                     "REFUSED", "locked test", "nothing staged or committed")
        # the same change committed by hand, past the tool, is caught by the check that CI runs
        self.ok(world.commit_all("[green] T-001 tweak the test"))
        failed = self.refused(world.batuta("tdd", "check"), "FAIL", "touches locked test", "tdd check: failed")
        self.assertIn(TEST_PATH, failed.out, failed.describe())

    def test_a_weakened_test_fails_the_tdd_check(self):
        world = self.fresh()
        weak = world.read(TEST_PATH).replace("    def test_trims_the_name", "    @unittest.skip('later')\n    def test_trims_the_name")
        self.assertNotEqual(weak, world.read(TEST_PATH))
        world.write(TEST_PATH, weak)
        self.ok(world.commit_all("[green] T-001 weaken the test"))
        failed = self.refused(world.batuta("tdd", "check"), "FAIL", "weakening marker", "tdd check: failed")
        self.assertIn("unittest.skip", failed.out, failed.describe())

    def test_a_gate_without_evidence_is_refused(self):
        world = self.fresh()
        ew.write_status(world)
        before = world.read("specs/%s/status.md" % FEATURE)
        refused = self.refused(world.batuta("gate", "status", FEATURE, "--set", "L0-understand=passed", "--apply"),
                               "REFUSED", "evidence", "nothing changed")
        self.assertIn("independent evidence", refused.out, refused.describe())
        self.assertEqual(world.read("specs/%s/status.md" % FEATURE), before, "a refused gate change must write nothing")
        # evidence that is not a valid evidence file is refused by its own lint
        world.write("specs/%s/evidence/L0-understand.md" % FEATURE, "PASS, trust me\n")
        self.refused(world.batuta("gate", "evidence-lint", "specs/%s/evidence/L0-understand.md" % FEATURE), "FAIL")

    def test_promote_is_refused_until_the_head_is_proven_green(self):
        world = self.fresh()
        head = world.head()
        args = ("gate", "promote", "--branch", ew.TASK_BRANCH, "--into", "main")
        main_before = world.git("rev-parse", "main").out.strip()
        self.refused(world.batuta(*args), "REFUSED", "nothing proves a green head")
        failing = world.write("failing.txt", "head %s\nRan 3 tests\n\nFAILED (failures=1)\n" % head, root=world.files)
        self.refused(world.batuta(*args, "--local-evidence", failing, "--apply"), "REFUSED", "promotion refused")
        stale = world.write("stale.txt", "head %s\nRan 3 tests\n\nOK\n" % ("0" * 40), root=world.files)
        self.refused(world.batuta(*args, "--local-evidence", stale, "--apply"), "REFUSED", "promotion refused")
        self.assertEqual(world.git("rev-parse", "main").out.strip(), main_before, "a refused promotion must not merge")
        green = ew.run_project_tests(world)
        self.assertEqual(green.rc, 0, green.describe())
        proof = world.write("green.txt", "head %s\n%s" % (head, green.text), root=world.files)
        self.ok(world.batuta(*args, "--local-evidence", proof), "promotion green", "dry run")

    def test_an_automation_command_is_denied_by_the_automation_guard(self):
        world = self.fresh()
        for command in ("schtasks /create /tn nightly /tr calc.exe /sc daily", "echo '0 3 * * * run.sh' | crontab -"):
            denial = self.assertDenied(world.hook("guard-automation", world.pretool_payload("Bash", {"command": command})))
            self.assertIn("automation", denial, command)
        self.assertAllowed(world.hook("guard-automation", world.pretool_payload("Bash", {"command": "git status --short"})))

    def test_a_secret_shaped_string_is_caught_by_leaks_scan(self):
        world = self.fresh()
        self.ok(world.batuta("leaks", "scan"), "clean")
        # assembled here so this test file itself holds no secret-shaped literal
        world.write("notes/leak.txt", "token = " + "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8" + "\n")
        caught = self.refused(world.batuta("leaks", "scan"), "FAIL", "notes/leak.txt", "hit(s)")
        self.assertNotIn("a1B2c3D4e5F6g7H8", caught.text, "the scan must not echo the secret\n" + caught.describe())


if __name__ == "__main__":
    unittest.main()
