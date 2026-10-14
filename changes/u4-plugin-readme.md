## Area `tdd`: test-first enforced on artifacts and history

Tests written first are locked by hash, commits follow a red and green grammar, and a checker proves the order from git
history instead of trusting a prompt. CI is the authority; the PreToolUse guard that blocks editing a locked file is a
separate hook.

```
python scripts/batuta.py tdd lock --task T-001 tests/test_x.py [--supersedes --change-request CR-001] [--apply]
python scripts/batuta.py tdd change-request new --test tests/test_x.py --requirement REQ-X-001 --reason TEXT --proposed TEXT --feature NAME [--apply]
python scripts/batuta.py tdd change-request decide CR-001 approve|reject [--apply]
python scripts/batuta.py tdd commit --red|--green|--refactor T-001 -m TITLE PATH... [--approved CR-001] [--apply]
python scripts/batuta.py tdd check [--range GIT-RANGE] [--replay] [--config PATH]
```

- The lock is `.batuta/test-locks.json` (C07, append-only). A path locked with the same hash is `SAME`; a changed hash is
  refused unless `--supersedes --change-request <id>` names a row of `specs/**/test-change-requests.md` (C33) with Status
  `approved`, a Decided by and the same Test path. Requirement ids come from `# REQ: REQ-X-001` (or `// REQ:`) lines of
  the test file; a file without one is locked with a `WARN`. The hash reads CRLF as LF.
- A change request always belongs to a feature (`--feature` is required): it is written to
  `specs/<feature>/test-change-requests.md`; `check` reads every `specs/**/test-change-requests.md`. An agent opens a
  request with `change-request new` (an `open` row, C33-validated, the file created when absent) and stops. Only
  `change-request decide` approves or rejects: it asks the person on the console device itself (`CONIN$` on Windows,
  `/dev/tty` elsewhere, never standard input), wants the exact phrase `approve CR-001` or `reject CR-001` and refuses
  without a console. Request ids are `CR-NNN`, unique across features because the id is the commit trailer.
- Commit messages are C32: `[red] T-001 title`, `[green] T-001 title`, `[refactor] T-001 title`, a blank line, a body and
  a last paragraph of trailers. The only override is `Test-Change-Approved: <request id>`, honoured only when the row was
  `approved` with a Decided by in the commit's parent (decided in an earlier commit), for the changed path, with a
  changed spec file in the same range. A commit that sets a row to approved or rejected together with any other path fails.
- `check` fails on: a green without an earlier red of its task; a `[red]` commit that adds no test file, holds anything
  but tests, test support files and the lock, or has a test not locked with its content at that commit; a commit that
  touches a path locked at its parent (every commit kind; a change of line endings only is not a change); a lock edited,
  shortened or extended by a `[green]` or `[refactor]` commit (except superseding entries under an approved request);
  a locked file whose hash at the end of the range differs from its newest entry; an added weakening marker; a test file
  whose assertions dropped (a rename to a name no runner discovers drops them to zero). A merge commit is checked against
  every parent: a path that differs from all of them is the merge's own edit and goes through the same rules, and the
  merge's lock keeps every parent's entries unchanged and in order. An empty range fails, a range part that starts with
  a dash is refused.
- Markers (Python resolved through its imports, so `import unittest as u; @u.skip` counts): `unittest.skip`, `skipIf`,
  `skipUnless`, `expectedFailure`, `SkipTest`, `skipTest`, `pytest.mark.skip`, `skipif`, `xfail`, `pytest.skip`,
  `pytest.importorskip`, `getattr` on `unittest` or `pytest`, assignments to `unittest.TestCase` members; JavaScript and
  TypeScript `it.only`, `describe.only`, `test.only`, `it.skip`, `describe.skip`, `test.skip`, `xit`, `xdescribe`,
  `test.todo`, `describe.todo`, `it.todo`, `fit`, `fdescribe`, `xtest`, also through a member prefix, brackets and
  destructuring. `conftest.py`, an `__init__.py` under a test folder and `pytest.ini`, `tox.ini`, `setup.cfg` are read
  for the same markers (and for `--deselect`, `--ignore`). Python files are read with `ast`: a marker or assertion in
  a string or comment never counts, a test file that stops parsing fails. Assertions: `assert` statements, `assert*`
  methods, `assert*` functions imported from unittest, pytest and the like or defined in the file with an assertion in
  their body; not counted: asserts under a constant false branch or inside a `try` that catches `AssertionError`,
  `Exception` or everything. JavaScript counts `expect(` and `assert(` calls with comments, strings and regular-expression
  literals removed.
- Settings come from the range's base commit, never from the checked-out tree: the start of `A..B`, or the root commit for
  a single revision. `--config` (or `BATUTA_CONFIG`) overrides, so CI should pass one from outside the repository. A commit
  in the range that changes the `tdd` block or `roots.temp` of `.batuta/batuta.json` is reported as a `WARN` naming the
  commit. A history without a red commit exits 2 with a `WARN`; without a lock file it warns that nothing is locked and
  still checks markers and assertions.
- A locked test may be renamed or deleted only under an approved request; for a rename the new path must itself be locked
  (C07 supersedes entries are per path).
- `--replay` checks each `[red]` commit out in a temporary worktree under the configured temp root and runs the project's
  own test command once: the configured `tdd.test_command` (the token `{tests}` stands for the red's test files), else
  `python -m unittest discover -s tests -p "test_*.py"` from the checkout root, with `-t .` when `tests` is a package. A red
  counts only when a test of its own failed or errored; exit 0, exit 5, `Ran 0 tests` and the failure of somebody else's
  test do not. The worktree is removed on success, failure and timeout.
- Optional `tdd` block of `batuta.json`: `test_command`, `replay_timeout_seconds` (default 300), `lock_file`, `markers`
  (`{"python": [...], "javascript": [...]}` replaces a language's default list). Git 2.30 or newer is required.
- Exit codes: 0 ok, 1 a failure or refusal, 2 warnings only.
