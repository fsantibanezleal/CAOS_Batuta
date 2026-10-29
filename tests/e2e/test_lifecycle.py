"""The happy path of the whole governed lifecycle, in one scratch project, through the public command line only.

The script is the first-project walkthrough (docs/guides/first-project.md): init user, init project, size and catalog,
spec new and lint, spec show, the typed approval through the `spec-approval` hook payload, the freeze check, the test
lock and the red commit, the red test failing, the implementation, the green commit, the replay of the history, the
evidence and the gate check, the Stop hook allowing, and the promotion. Every artifact the scenario writes is validated
against its contract, and every step that must refuse is shown refusing first, so a step cannot pass without its gate.
"""
from __future__ import annotations

import sys
import unittest

import e2e_world as ew
from e2e_world import FEATURE, TASK, TEST_PATH, WorldCase


class LifecycleTests(WorldCase):
    def test_full_lifecycle_through_the_public_command_line(self):
        world = self.new_world()

        # L0 device: init user (a dry run writes nothing), then device check
        dry = self.ok(world.batuta("init", "user", "--home", world.home, "--deploy-root", world.deploy), "dry run", rc=0)
        self.assertEqual(list(world.deploy.iterdir()), [], "init user without --apply must write nothing\n" + dry.describe())
        self.assertFalse((world.home / ".claude").exists(), dry.describe())
        applied = world.batuta("init", "user", "--home", world.home, "--deploy-root", world.deploy, "--apply")
        self.assertIn(applied.rc, (0, 2), applied.describe())  # 2 is the honest warning that no user core template is set
        self.ok(world.batuta("device", "check", "--home", world.home, "--deploy-root", world.deploy), "device check: complete")
        self.validate(world, "C01", world.deploy / "batuta.json")
        self.validate(world, "C15", world.deploy / "device.json")

        # init project, spec scaffolding, size and catalog
        ew.adopt_project(self, world)
        self.validate(world, "C01", world.path(".batuta/batuta.json"))
        sizing = ew.write_sizing_and_catalog(self, world)
        self.validate(world, "C23", sizing)
        self.validate(world, "C22", world.path("docs/contracts/catalog.md"), root=None)
        self.ok(world.batuta("size", "lint", "--root", ".", "--sizing", sizing), "size lint: 8 ok, 0 warning(s), 0 failure(s)")

        # spec new and lint: the lint warns while the named test does not exist (a warning is exit 2, never a pass)
        ew.write_spec(self, world)
        self.validate(world, "C21", world.path("specs/%s/tasks.md" % FEATURE))
        early = world.batuta("spec", "lint", "--spec", FEATURE)
        self.assertEqual(early.rc, 2, early.describe())
        self.assertIn("does not exist", early.text, early.describe())
        world.write(TEST_PATH, ew.GREETER_TEST)
        self.ok(world.batuta("spec", "lint", "--spec", FEATURE), "satisfies C05")
        self.validate(world, "C05", world.path("specs/%s/spec.md" % FEATURE))
        self.ok(world.batuta("spec", "trace", FEATURE, "--apply"), "ok=true")
        self.validate(world, "C08", world.path("specs/%s/trace.json" % FEATURE))

        # spec show, the freeze is VOID until a person approves, then the typed approval through the hook
        phrase = ew.approval_phrase(self, world)
        self.refused(world.batuta("spec", "freeze", "--check", FEATURE), "VOID")
        done = world.hook("spec-approval", world.prompt_payload(phrase))
        self.assertEqual(done.rc, 0, done.describe())
        self.assertIn("approval recorded", done.out, done.describe())
        records = sorted(world.path("specs/%s/approvals" % FEATURE).glob("2*.json"))
        self.assertEqual(len(records), 1, done.describe())
        self.validate(world, "C06", records[0])
        self.ok(world.batuta("spec", "freeze", "--check", FEATURE), "VALID")

        # hook payload files conform to C16, the hook registration to C31
        for doc in (world.prompt_payload(phrase), world.stop_payload()):
            self.validate(world, "C16", world.payload(doc))
        self.validate(world, "C31", ew.PLUGIN / "hooks" / "hooks.json")

        # commit the spec, lock the test, the red commit (C32 message), the red test fails
        self.ok(world.commit_paths("docs(spec): 002-greeting spec, tasks and typed approval", "specs", "docs"))
        self.ok(world.batuta("tdd", "lock", "--task", TASK, TEST_PATH, "--apply"), "locked")
        self.validate(world, "C07", world.path(".batuta/test-locks.json"))
        red = self.ok(world.batuta("tdd", "commit", "--red", TASK, "-m", "Greet by name", TEST_PATH, "--apply"), "[red] T-001 Greet by name")
        self.assertEqual(world.git("log", "-1", "--format=%s").out.strip(), "[red] T-001 Greet by name", red.describe())
        message = world.write("red-message.txt", "[red] T-001 Greet by name\n", root=world.files)
        self.validate(world, "C32", message)
        failing = ew.run_project_tests(world)
        self.assertNotEqual(failing.rc, 0, "the red test must fail before the implementation\n" + failing.describe())
        self.assertIn("greeter", failing.text, "the red test must fail for the missing behavior\n" + failing.describe())
        self.ok(world.batuta("tdd", "check"), "tdd check: ok")

        # the implementation and the green commit; the project tests pass; the replay proves red then green
        world.write("greeter.py", ew.GREETER)
        self.ok(world.batuta("tdd", "commit", "--green", TASK, "-m", "Greet by name", "greeter.py", "--apply"), "[green] T-001 Greet by name")
        passing = ew.run_project_tests(world)
        self.assertEqual(passing.rc, 0, passing.describe())
        replay = self.ok(world.batuta("tdd", "check", "--replay"), "fails at the red commit", "tdd check: ok")
        self.assertIn("OK red commit", replay.out, replay.describe())

        # a gate cannot pass out of order or without evidence from another agent
        ew.write_status(world)
        self.refused(world.batuta("gate", "status", FEATURE, "--set", "L7-build=passed"), "REFUSED L7-build", "pending")
        self.refused(world.batuta("gate", "status", FEATURE, "--set", "L0-understand=passed", "--apply"), "evidence")
        self.assertIn("L0-understand: pending", world.read("specs/%s/status.md" % FEATURE))
        self.ok(world.commit_all("chore: trace and status"))
        ew.pass_l0(self, world)
        self.validate(world, "C09", world.path("specs/%s/evidence/L0-understand.md" % FEATURE))
        self.validate(world, "C10", world.path("specs/%s/status.md" % FEATURE))
        self.ok(world.batuta("gate", "check", FEATURE), "every gate rule holds", "gate L0-understand passed with adversary evidence")
        self.ok(world.batuta("gate", "thresholds", "--check"), "thresholds hold")
        self.validate(world, "C11", world.path("specs/000-foundation/thresholds.json"))
        self.ok(world.batuta("guard", "scan", "--diff", "main..HEAD"), "guard scan: clean")
        self.ok(world.batuta("leaks", "scan"), "leaks scan: clean")

        # the machine-readable form of a command conforms to C20
        as_json = world.batuta("--json", "spec", "lint", "--spec", FEATURE)
        self.assertEqual(as_json.rc, 0, as_json.describe())
        self.assertEqual(as_json.json()["exit_code"], 0)
        self.validate(world, "C20", world.write("lint.json", as_json.out, root=world.files))

        # the Stop hook allows: the unit changed in this session has a passing gate check
        stop = world.hook("gate-stop", world.stop_payload())
        self.assertAllowed(stop)
        self.assertEqual(world.git("status", "--short", "--", ".batuta/gate-stop.state").out.strip(), "")

        # commit, push the branch to the local remote, and promote with local test evidence for the exact head
        self.ok(world.commit_all("docs(gates): L0 evidence and status"))
        self.ok(world.git("push", "-q", "origin", ew.TASK_BRANCH))
        head = world.head()
        report = ew.run_project_tests(world)
        self.assertEqual(report.rc, 0, report.describe())
        evidence = world.write("local-evidence.txt", "head %s\n%s" % (head, report.text), root=world.files)
        dry = self.ok(world.batuta("gate", "promote", "--branch", ew.TASK_BRANCH, "--into", "main", "--local-evidence", evidence),
                      "promotion green", "dry run")
        self.assertNotEqual(world.git("rev-parse", "main").out.strip(), head, "a dry run must not merge\n" + dry.describe())
        self.ok(world.git("checkout", "-q", "main"))
        self.ok(world.batuta("gate", "promote", "--branch", ew.TASK_BRANCH, "--into", "main", "--local-evidence", evidence, "--apply"),
                "merged")
        self.assertEqual(world.git("merge-base", "--is-ancestor", head, "main").rc, 0, "the head must be in main after the promotion")
        self.ok(world.git("push", "-q", "origin", "main"))
        self.assertEqual(world.git("rev-parse", "main").out.strip(), world.git("ls-remote", "origin", "main").out.split()[0])

    def test_an_installed_scratch_world_never_reaches_the_real_home(self):
        """The world's home is its own: the project run above and every command here resolve the home inside the scratch."""
        world = self.new_world()
        probe = world.run([sys.executable, "-c", "import os, pathlib; print(pathlib.Path.home()); print(os.environ['BATUTA_HOME'])"])
        self.ok(probe)
        home, deploy = probe.out.splitlines()[:2]
        self.assertEqual(home, str(world.home))
        self.assertEqual(deploy, str(world.deploy))


if __name__ == "__main__":
    unittest.main()
