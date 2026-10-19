"""A commit in a test repository leaves no process behind: `git commit` runs `git maintenance run --auto --detach`, a detached
process that can still write into `.git/objects` while the test's temporary folder is removed (the CI error `Directory not empty:
'objects'`). The test repositories switch automatic maintenance off."""
import os
import tempfile
import unittest
from pathlib import Path

from test_init_support import commit_all, make_repo


class NoDetachedMaintenance(unittest.TestCase):
    def test_a_commit_in_a_test_repository_starts_no_maintenance_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            (repo / "a.txt").write_text("a", encoding="utf-8")
            trace = Path(tmp) / "trace.txt"
            old = os.environ.get("GIT_TRACE")
            os.environ["GIT_TRACE"] = str(trace)
            try:
                commit_all(repo, "first")
            finally:
                if old is None:
                    os.environ.pop("GIT_TRACE", None)
                else:
                    os.environ["GIT_TRACE"] = old
            text = trace.read_text(encoding="utf-8", errors="replace")
            self.assertIn("git commit", text)
            self.assertNotIn("maintenance run", text)
            self.assertNotIn("gc --auto", text)
