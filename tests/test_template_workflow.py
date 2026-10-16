"""The shell logic of the template's `batuta-gates` workflow, run for real against scratch repositories and a stand-in
`batuta.py`: the base revision of a pull request and of a push (plan decisions 31 to 33), and the exit-code rule (a WARN,
exit 2, is reported and does not fail the job; a FAIL, exit 1, does)."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import (FIXTURE_VARS, bash_path, commit_all, git, make_repo, run_block,  # noqa: E402
                               step_block)

from batuta_lib.areas import init  # noqa: E402

ZEROS = "0" * 40


def rendered_workflow():
    return init.render_project(dict(FIXTURE_VARS))[".github/workflows/batuta-gates.yml"]


def base_script():
    """The python program of the `base` step: the text between its here-document markers."""
    body = run_block(step_block(rendered_workflow(), "base"))
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", body, re.S)
    assert match, "the base step has no python here-document"
    return match.group(1) + "\n"


class BaseRevision(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.repo = make_repo(self.tmp / "repo")
        (self.repo / "a.txt").write_text("1\n", encoding="utf-8")
        self.c1 = commit_all(self.repo, "one")
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.c1)
        git(self.repo, "checkout", "-q", "-b", "feature")
        (self.repo / "a.txt").write_text("2\n", encoding="utf-8")
        self.c2 = commit_all(self.repo, "two")
        (self.repo / "a.txt").write_text("3\n", encoding="utf-8")
        self.c3 = commit_all(self.repo, "three")

    def resolve(self, event_name, event):
        event_file = self.tmp / "event.json"
        event_file.write_text(json.dumps(event), encoding="utf-8")
        env_file = self.tmp / "github_env"
        env_file.write_text("", encoding="utf-8")
        env = {**os.environ, "GITHUB_EVENT_NAME": event_name, "GITHUB_EVENT_PATH": str(event_file),
               "GITHUB_ENV": str(env_file), "DEFAULT_BRANCH": FIXTURE_VARS["default_branch"]}
        done = subprocess.run([sys.executable, "-B", "-c", base_script()], cwd=self.repo, env=env, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        lines = [ln for ln in env_file.read_text(encoding="utf-8").splitlines() if ln.startswith("BATUTA_BASE=")]
        self.assertEqual(len(lines), 1, done.stdout + done.stderr)
        return lines[0].split("=", 1)[1], done.stdout + done.stderr

    def test_pull_request_uses_the_base_commit_of_the_event(self):
        base, _ = self.resolve("pull_request", {"pull_request": {"base": {"sha": self.c1}}})
        self.assertEqual(base, self.c1)

    def test_push_uses_the_commit_before(self):
        base, _ = self.resolve("push", {"before": self.c2, "after": self.c3})
        self.assertEqual(base, self.c2)

    def test_push_of_a_new_branch_uses_the_merge_base_with_the_default_branch(self):
        base, _ = self.resolve("push", {"before": ZEROS, "after": self.c3})
        self.assertEqual(base, self.c1)

    def test_push_after_a_force_push_with_an_unknown_before_uses_the_merge_base(self):
        base, _ = self.resolve("push", {"before": "1" * 40, "after": self.c3})
        self.assertEqual(base, self.c1)

    def test_other_events_use_the_merge_base(self):
        base, _ = self.resolve("workflow_dispatch", {})
        self.assertEqual(base, self.c1)

    def test_first_push_to_the_default_branch_never_uses_head_as_the_base_when_a_parent_exists(self):
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--ff-only", "feature")
        git(self.repo, "update-ref", "refs/remotes/origin/main", git(self.repo, "rev-parse", "HEAD"))
        base, _ = self.resolve("push", {"before": ZEROS, "after": self.c3})
        self.assertEqual(base, self.c2)

    def test_a_repository_with_one_commit_falls_back_to_head_and_says_so(self):
        solo = make_repo(self.tmp / "solo")
        (solo / "a.txt").write_text("1\n", encoding="utf-8")
        head = commit_all(solo, "only")
        git(solo, "update-ref", "refs/remotes/origin/main", head)
        event_file = self.tmp / "event2.json"
        event_file.write_text(json.dumps({"before": ZEROS}), encoding="utf-8")
        env_file = self.tmp / "github_env2"
        env_file.write_text("", encoding="utf-8")
        env = {**os.environ, "GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": str(event_file),
               "GITHUB_ENV": str(env_file), "DEFAULT_BRANCH": "main"}
        done = subprocess.run([sys.executable, "-B", "-c", base_script()], cwd=solo, env=env, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"BATUTA_BASE={head}", env_file.read_text(encoding="utf-8"))
        self.assertIn("::warning::", done.stdout)


@unittest.skipIf(bash_path() is None, "bash is not available; the workflow's shell logic is checked where it is")
class GatesStep(unittest.TestCase):
    """The `gates` step under bash with a stand-in batuta.py that answers per `<area> <verb>` from the environment."""

    STANDIN = (
        "import os, sys\n"
        "log = os.environ['STANDIN_LOG']\n"
        "with open(log, 'a', encoding='utf-8') as h:\n"
        "    h.write(' '.join(sys.argv[1:]) + '\\n')\n"
        "key = '_'.join(sys.argv[1:3]).upper().replace('-', '_')\n"
        "sys.exit(int(os.environ.get('RC_' + key, '0')))\n"
    )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.proj = self.tmp / "proj"
        for spec_dir in ("000-foundation", "001-example-feature", "002-second"):
            (self.proj / "specs" / spec_dir).mkdir(parents=True)
        (self.proj / "specs" / "README.md").write_text("x\n", encoding="utf-8")
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        (self.fake / "batuta.py").write_text(self.STANDIN, encoding="utf-8")
        self.log = self.tmp / "calls.log"
        script = run_block(step_block(rendered_workflow(), "gates"))
        self.script = self.tmp / "gates.sh"
        self.script.write_text(script, encoding="utf-8", newline="\n")

    def gates(self, **rc):
        env = {**os.environ, "BATUTA_DIR": self.fake.as_posix(), "BATUTA_BASE": "abc123", "STANDIN_LOG": str(self.log),
               "PYTHON": sys.executable.replace("\\", "/"), **{f"RC_{k.upper()}": str(v) for k, v in rc.items()}}
        done = subprocess.run([bash_path(), str(self.script)], cwd=self.proj, env=env, capture_output=True, text=True,
                              timeout=120)
        calls = self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []
        return done, calls

    def test_every_check_runs_with_the_base_revision_and_the_foundation_folder_is_skipped(self):
        done, calls = self.gates()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("tdd check --replay --range abc123..HEAD", calls)
        self.assertIn("guard scan --diff abc123..HEAD", calls)
        for feature in ("001-example-feature", "002-second"):
            self.assertTrue(any(c.startswith(f"spec trace {feature}") for c in calls), calls)
            self.assertTrue(any(c.startswith(f"gate check {feature}") and "--against abc123" in c for c in calls), calls)
        self.assertFalse(any("000-foundation" in c for c in calls), calls)
        for needed in ("gate thresholds", "context check", "leaks scan"):
            self.assertTrue(any(c.startswith(needed) for c in calls), (needed, calls))

    def test_a_warning_exit_code_is_reported_and_does_not_fail_the_job(self):
        done, _ = self.gates(tdd_check=2, leaks_scan=2)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("::warning::", done.stdout)

    def test_a_failure_fails_the_job_but_every_other_check_still_runs(self):
        done, calls = self.gates(spec_trace=1)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("::error::", done.stdout)
        self.assertTrue(any(c.startswith("leaks scan") for c in calls), "later checks run after a failure")


if __name__ == "__main__":
    unittest.main()
