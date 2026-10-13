## Area `tdd`: test-first enforced on artifacts and history

Tests written first are locked by hash, commits follow a red and green grammar, and a checker proves the order from git
history instead of trusting a prompt. CI is the authority; the PreToolUse guard that blocks editing a locked file is a
separate hook.

```
python scripts/batuta.py tdd lock --task T-001 tests/test_x.py [--supersedes --change-request CR-001] [--apply]
python scripts/batuta.py tdd change-request new --test tests/test_x.py --requirement REQ-X-001 --reason TEXT --proposed TEXT --feature NAME [--apply]
python scripts/batuta.py tdd commit --red|--green|--refactor T-001 -m TITLE PATH... [--approved CR-001] [--apply]
python scripts/batuta.py tdd check [--range GIT-RANGE] [--replay]
```

- The lock is `.batuta/test-locks.json` (C07, append-only). A path locked with the same hash is `SAME`; a changed hash is
  refused unless `--supersedes --change-request <id>` names a row of `specs/**/test-change-requests.md` (C33) with Status
  `approved`, a Decided by and the same Test path. Requirement ids come from `# REQ: REQ-X-001` (or `// REQ:`) lines of
  the test file; a file without one is locked with a `WARN`. The hash reads CRLF as LF.
- A change request always belongs to a feature (`--feature` is required): it is written to
  `specs/<feature>/test-change-requests.md`; `check` reads every `specs/**/test-change-requests.md`.
- An agent adds an `open` change request (`change-request new`) and stops; only a person turns it `approved`. The
  request ids are `CR-NNN`, unique across features because the id is the commit trailer.
- Commit messages are C32: `[red] T-001 title`, `[green] T-001 title`, `[refactor] T-001 title`, a blank line, a body and
  a last paragraph of trailers. The only override is `Test-Change-Approved: <request id>`.
- `check` fails on a green without an earlier red of its task, a commit that touches a path locked at its parent (the
  default is every commit kind, not only green), a lock edited or shortened, a locked file whose hash at the end of the
  range differs from its newest entry, an added weakening marker and a test file whose assertions dropped. Markers: Python
  `unittest.skip`, `skipIf`, `skipUnless`, `expectedFailure`, `pytest.mark.skip`, `skipif`, `xfail`, `pytest.skip`;
  JavaScript and TypeScript `it.only`, `describe.only`, `test.only`, `it.skip`, `describe.skip`, `test.skip`, `xit`,
  `xdescribe`, `test.todo`. Python files are read with `ast` (a marker in a string or comment never counts), a test file
  that stops parsing fails. A merge commit is skipped with a `WARN`; a history without a red commit exits 2 with a `WARN`;
  without a lock file it warns that nothing is locked and still checks markers and assertions.
- A locked test may be renamed or deleted only under an approved request; for a rename the new path must itself be locked
  (C07 supersedes entries are per path), and the request's spec folder must have a changed file in the same range.
- `--replay` runs, for each `[red]` commit, the test command on the test files that commit adds or changes, in a
  temporary worktree under the configured temp root, and requires each to fail. The worktree is removed on success,
  failure and timeout. The default test command runs each file through `python -m unittest discover -s <dir> -p <file>`;
  a configured command containing `{tests}` receives all the files in its place, any other command gets them appended.
- Optional `tdd` block of `batuta.json`: `test_command`, `replay_timeout_seconds` (default 300), `lock_file`, `markers`
  (`{"python": [...], "javascript": [...]}` replaces a language's default list). Git 2.30 or newer is required.
- Exit codes: 0 ok, 1 a failure or refusal, 2 warnings only.
