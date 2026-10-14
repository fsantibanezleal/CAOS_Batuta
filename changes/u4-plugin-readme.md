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
  test do not. The worktree is removed on success, failure and timeout. `--replay` also RUNS, at every later `[green]` and
  `[refactor]` commit of a task, the tests of the project (unittest discovery with a result class that records each test id's
  outcome, or pytest with a JUnit XML report in the temp root) and compares the outcomes of the locked tests with the tests the
  red commit's file defines: each locked test must have run, not be skipped and not be reported as an expected failure,
  whatever configuration, hook, patch or import did it (`setattr` on `setUp`, a `SkipTest` raised from a fixture, a module-level
  patch). An approved rename maps the ids to the new file, an approved deletion removes them; a parametrized pytest id is
  compared by the part before `[` (one case that ran is enough). A test command that is neither pytest nor unittest discovery
  gets a `WARN` that the comparison was not run.
- Known limits of the static rules: a skip built from a name made at run time in a test that is not locked is not seen, except
  `import_module` or `__import__` with a computed name, which is itself flagged; the runtime run above is the control for
  locked tests. A skip raised inside a test body at run time is seen by the run only as `skipped`.
- Optional `tdd` block of `batuta.json`, the closed block of C01 1.1 (also checked here in a 1.0 document): `test_command`,
  `replay_timeout_seconds` (an integer, at least 1, default 300), `lock_file` (a `.json` that is not `batuta.json`, default
  `.batuta/test-locks.json`), `markers` (an array of names that adds to the default list of every language, so a project cannot remove a default marker;
  a 1.0 document may still carry the legacy object per language, `{"python": [...], "javascript": [...]}`, which adds too). Git
  2.30 or newer is required.
- Exit codes: 0 ok, 1 a failure or refusal, 2 warnings only.
