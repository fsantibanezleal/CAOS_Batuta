## Area `tdd`: test-first enforced on artifacts and history

Tests written first are locked by hash, commits follow a red and green grammar, and a checker proves the order from git
history instead of trusting a prompt. CI is the authority; the PreToolUse guard that blocks editing a locked file is a
separate hook.

```
python scripts/batuta.py tdd lock --task T-001 tests/test_x.py [--supersedes --change-request CR-001] [--apply]
python scripts/batuta.py tdd change-request new --test tests/test_x.py --requirement REQ-X-001 --reason TEXT --proposed TEXT --feature NAME [--apply]
python scripts/batuta.py tdd change-request show CR-001
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
  request with `change-request new` (an `open` row, C33-validated, the file created when absent) and stops. A request is
  decided in one of two ways, both by a person. `change-request decide <id> approve|reject --apply` asks on the console
  device itself (`CONIN$` on Windows, `/dev/tty` elsewhere, never standard input): on Windows `GetConsoleMode` must succeed on
  the stdin handle (NUL, a pipe or a file fail it), on POSIX standard input must be a terminal and `/dev/tty` must open; it
  wants the exact phrase `approve CR-001` or `reject CR-001`, waits 300 seconds at most (exit 1, nothing written) and records
  the operating-system account, never an environment variable, as Decided by. Or `change-request show <id>` prints the
  phrase `approve CR-001 <12 hex>` (the first 12 hex digits of the SHA-256 of that row's normalized text): the person types it
  as a prompt, and the UserPromptSubmit handler `tdd-change-request` (`HOOKS` of this area) records the decision, Decided by
  `typed prompt`, only when the first line of the prompt, trimmed, is exactly the phrase (words after it on that line decide
  nothing) and the row is still `open` with that hash; it never blocks and never raises. Request ids are `CR-NNN`, unique across features because the id is the commit trailer. Waived: keystrokes
  injected into a console by another process attached to it (the same class as F-02 of the spec unit); the guards unit
  closes it by denying agents the command and every direct run of the hook launcher.
- A request is opened, then decided in a commit of its own, then used: `check` fails a row that is born `approved` or
  `rejected`, a decided row that is edited, and a commit that decides a row together with any other path.
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
  destructuring and variable aliases (`const t = it; t.only(...)`). Python aliases are resolved through `import`,
  `importlib.import_module('m')`, `__import__('m')`, `sys.modules['m']`, the defining modules (`unittest.case.skip` is
  `unittest.skip`, `_pytest.*` is `pytest.*`) and name assignments (`u = unittest`, `s = unittest.skip`). `conftest.py`,
  an `__init__.py` under a test folder and the runner settings (`pytest.ini`, `tox.ini`, `setup.cfg`, the pytest section of
  `pyproject.toml`) are read for the same markers and for what deselects tests (`--deselect`, `--ignore`, `-k`, `-m "not"`,
  `python_files`, `testpaths`, `norecursedirs`...), and a `load_tests` function, `pytest_collection_modifyitems` or
  `collect_ignore` anywhere is a marker. A `[green]` or `[refactor]` commit that changes test configuration (a `conftest.py`
  or the pytest part of a settings file) needs an approved change request. Python files are read with `ast`: a marker or
  assertion in a string or comment never counts, a test file that stops parsing fails. Assertions: `assert` statements (not
  `assert True`), `assert*` methods the file does not define as no-ops, `assert*` functions imported from unittest, pytest and
  the like or defined in the file with an assertion on their parameters; not counted: asserts under a constant false
  branch (`False`, `0`, `1 == 2`), after a `return`, `raise`, `continue` or `break`, inside a `try` that catches
  `AssertionError`, `Exception` or everything, inside `contextlib.suppress(AssertionError)` and inside a nested function nothing
  uses. JavaScript counts `expect(` and `assert(` calls with comments, strings and regular-expression literals removed.
- Settings come from the range's base commit, never from the checked-out tree: the start of `A..B`, or the root commit for
  a single revision. `--config` (or `BATUTA_CONFIG`) overrides, so CI should pass one from outside the repository, or
  `--range <base>..HEAD`. A commit in the range (not the base commit itself) that changes the `tdd` block or `roots.temp` of
  `.batuta/batuta.json` from the base commit's is reported as a `WARN` naming the commit. A history without a red commit exits 2 with a `WARN`; without a lock file it warns that nothing is locked and
  still checks markers and assertions.
- A locked test may be renamed or deleted only under an approved request; for a rename the new path must itself be locked
  (C07 supersedes entries are per path).
- `--replay` checks each `[red]` commit out in a temporary worktree under the configured temp root and runs the project's
  own test command once: the configured `tdd.test_command` (the token `{tests}` stands for the red's test files), else
  `python -m unittest discover -s tests -p "test_*.py"` from the checkout root, with `-t .` when `tests` is a package. A red
  counts only when a test of its own failed or errored; exit 0, exit 5, `Ran 0 tests` and the failure of somebody else's
  test do not. The worktree is removed on success, failure and timeout. `--replay` also RUNS the tests of the project (unittest
  discovery with a result class that records each test id's outcome, or pytest with a JUnit XML report in the temp root) at every
  commit of the range that changes a test, a test support file or the test configuration (whatever its tag or task), at every
  `[green]` and `[refactor]` commit, and at the head of the range, and compares the outcomes of every live locked test, of every
  task (from its first `[green]` commit on), with the tests the locked file defines: each must have run, not be skipped,
  deselected or reported as an expected failure at any of those commits (the first commit with the problem is named),
  whatever configuration, hook, patch or import did it (`setattr` on `setUp`, a `SkipTest` raised from a fixture, a module-level
  patch). An approved rename maps the ids to the new file, an approved deletion removes them; a parametrized pytest id is
  compared by the part before `[` (one case that ran is enough). A test command that is neither pytest nor unittest discovery
  gets a `WARN` that the comparison was not run. Cost: one checkout and one run of the test command per such commit, each bounded by
  `replay_timeout_seconds`, so the time grows with the number of those commits times the length of the suite (at most that many
  timeouts); a range with many test-changing commits is expensive, and CI should replay `<base>..HEAD` of a branch, not the whole
  history.
- The head check point of `--replay` is the project's own run, one and the same process: it runs the configured `tdd.test_command`
  VERBATIM (exactly the string the project and CI run: no wrapper, no `-c`, no added module, argument or environment) in the
  repository's own checkout (the working tree `check` was started in), and reads each test's outcome from that command's own
  output: unittest's verbose lines (`test_x (module.Class.test_x) ... ok|FAIL|ERROR|skipped|expected failure|unexpected
  success`), a JUnit XML file the command writes (`--junitxml=<path>`) or the summary of `pytest -rA`. A command that does not
  report each test (unittest without `-v`, pytest without `-rA` or `--junitxml`, a template with `{tests}`, any other runner) fails
  the head check: `configure tdd.test_command to report each test (for example python -m unittest discover -v or pytest -rA
  --junitxml=<path>)`. The default command, when none is configured, is `python -m unittest discover -s tests -p "test_*.py" -v`
  (with `-t .` added when `tests` is a package: unittest cannot start from a folder that is not importable with it). The CI
  workflow must call the same `tdd.test_command` string as its test step, then `tdd check --replay`. Product code cannot tell
  the head run from CI. When that working tree has uncommitted changes to tracked files the head check point fails
  (`the working tree differs from HEAD; commit or run from a clean checkout`; CI checkouts are clean); untracked files are
  fine. A range that ends before the checked-out HEAD runs its end in a temporary worktree and gets a `WARN` naming both commits.
  Intermediate check points keep a recording runner (a result class that records each test id's outcome) and the red replays
  run in temporary worktrees whose names are random and contain no `tdd`, `replay` or `batuta`, with the caller's environment
  unchanged (no variable is added). Known limit: an intermediate worktree is detectable (by its `.git` file, the temp root's own
  path, which is the configured `roots.temp`, or the recording runner); code that does so can hide intermediate states only,
  and nothing it hides ships, because the head runs in place and the CI run is the project's real run.
- Forgery from inside the run. A locked test passes at the head only with exactly one result line that is `ok`: any skip, expected
  failure or unexpected success line fails it, and so does a second result line for the same test (a parametrized pytest case may
  appear once per case). The result lines must match the runner's own summary: the number of lines equals `Ran N tests`, the
  failures, errors, skips, expected failures and unexpected successes equal the tally after it (unittest); the JUnit `tests`
  attribute equals its `testcase` elements; the `pytest -rA` lines equal its final tally. A line added, removed or rewritten by the
  code under test breaks one of these. A static scan of EVERY Python file of the repository (not only tests) finds assignments to
  or patches of the runner's own classes and functions (`unittest.TestCase` methods, `unittest.main`, `TextTestRunner`,
  `TextTestResult`), pytest hooks that change collection or reporting (`pytest_collection_modifyitems`, `pytest_runtest_*`), a
  replacement of `sys.stdout` or `sys.stderr`, and reads of the parent process (`os.getppid`, a psutil parent, `/proc/<pid>/cmdline`,
  `wmic` or `Get-CimInstance` on a parent). A finding introduced inside the checked range fails unless an approved change request
  names the file; one that already exists at the base commit is a `WARN`. Residual (accepted, plan decision 37): in-process forgery
  that none of these sees (for example a result stream rewritten by means the scan does not know) is controlled by the static
  scan and by the human review of the diff; CI must run exactly `tdd.test_command`, and the guards and distribution unit adds a
  doctor check that the workflow's test step equals it.
- Known limits of the static rules: a skip built from a name made at run time in a test that is not locked is not seen, except
  `import_module` or `__import__` with a computed name, which is itself flagged; the runtime run above is the control for
  locked tests. A skip raised inside a test body at run time is seen by the run only as `skipped`.
- Optional `tdd` block of `batuta.json`, the closed block of C01 1.1 (also checked here in a 1.0 document): `test_command`,
  `replay_timeout_seconds` (an integer, at least 1, default 300), `lock_file` (a `.json` that is not `batuta.json`, default
  `.batuta/test-locks.json`), `markers` (an array of names that adds to the default list of every language, so a project cannot remove a default marker;
  a 1.0 document may still carry the legacy object per language, `{"python": [...], "javascript": [...]}`, which adds too). Git
  2.30 or newer is required.
- Exit codes: 0 ok, 1 a failure or refusal, 2 warnings only.
