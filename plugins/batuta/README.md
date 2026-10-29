# batuta (plugin)

The Claude Code plugin of CAOS_Batuta: governed agentic development, with scoped agents on explicit models, spec-driven and
test-driven work with locked tests, data contracts, adversarial gates in every phase, guards with script and CI twins, and a
context budget. Version 0.01.000 (semver 0.1.0 in the manifest).

## What ships

- `.claude-plugin/plugin.json`, the plugin manifest (name `batuta`, the plugin option `python`).
- `scripts/batuta.py`, the single command line entry (standard-library Python 3.10 or newer), and `scripts/hook.py`, the
  launcher every hook entry runs through (contract C31).
- `scripts/batuta_lib/areas/`, one module per command area: `adr`, `brief`, `context`, `contract`, `device`, `dispatch`,
  `fragments`, `gate`, `guard`, `init`, `leaks`, `lessons`, `memory`, `preflight`, `provider`, `report`, `reserve`, `route`,
  `size`, `skeleton`, `spec`, `tdd`, `tech`, `version`.
- `agents/` (adversary, doc-writer, implementer, reviewer, runner, searcher, test-author, each on a pinned model), `skills/`
  (thirteen skills, from `route` and `brief` to `promote` and `lessons`) and `hooks/hooks.json` (every guard and check
  handler, wired per event).
- `contracts/`, the data contracts C01 to C34 with valid and invalid fixtures (see `contracts/README.md`).
- `templates/`, everything `init` and `device` render: the project template with its `batuta-gates` workflow, the user
  core, the settings presets, the knowledge manifest, the brief, spec and gate templates, and a managed-settings example.

## Install

One step, for Claude Code 2.1.275 or later (from a shell, 2.1.292 or later):

```
/plugin install batuta --marketplace fsantibanezleal/CAOS_Batuta
```

The two-step form is `/plugin marketplace add fsantibanezleal/CAOS_Batuta` then `/plugin install batuta@caos-batuta`. Claude Code asks for the
plugin option `python` (the command that starts Python 3.10 or newer, used by every hook); hooks with `onFailure: "block"` need Claude Code 2.1.295
or later. The full guide is `docs/guides/install.md` in the repository.

## Skills, hooks and the plugin manifest

The plugin ships thirteen skills (`skills/<name>/SKILL.md`): `route`, `brief`, `delegate`, `spec`, `freeze`, `red`, `green`,
`gate`, `verify`, `promote`, `context-audit`, `doctor` and `lessons`. Each is a numbered procedure over the commands of
this CLI, the lifecycle gate it serves and what to do on a non-zero exit. `freeze` and `promote` are started by a person only.

`hooks/hooks.json` runs every handler through the launcher with the interpreter of the plugin option `python`:

```
"$CLAUDE_PLUGIN_OPTION_PYTHON" -I "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" <handler id>
```

| Event | Handler ids |
|---|---|
| SessionStart (`startup\|resume`) | `session-check` |
| PreToolUse | `guard-automation`, `guard-destructive`, `guard-locked-tests`, `guard-approvals`, `guard-secrets` (each `onFailure: "block"`), `guard-require-brief` |
| SubagentStop | `subagent-stop` |
| UserPromptSubmit | `spec-approval`, `tdd-change-request` |
| Stop | `gate-stop` |

Set the option `python` when Claude Code asks at install: `python3` on macOS and Linux, `py` or the absolute path of
python.exe on Windows (Python 3.10 or newer; Git Bash must be installed on Windows).

`"onFailure": "block"` in hooks needs Claude Code v2.1.295 or later (the hooks reference,
https://code.claude.com/docs/en/hooks, read 2026-10-16). The page does not say what an older client does with the key;
that behavior is UNVERIFIED, so run the plugin on v2.1.295 or later or the five guards may not fail closed.

## Areas `route`, `brief` and `report`: delegation with a checkable report

A delegation is a brief in, a report out, and a row in the ledger that says how it ended. Roles and models come from the
configuration (C01), briefs from `templates/brief.md`, and nothing is accepted on the agent's word: the report is checked
against the brief.

```
python scripts/batuta.py route show [--root DIR]
python scripts/batuta.py route check [--root DIR] [--agents-dir DIR]
python scripts/batuta.py brief new --slug S --topic T --agent A --title "..." [--model M] [--kind K] [--sizing PATH] [--report PATH] [--root DIR] [--date YYYY-MM-DD]
python scripts/batuta.py brief lint BRIEF [--root DIR]
python scripts/batuta.py report check --brief BRIEF [REPORT] [--root DIR]
python scripts/batuta.py report ledger-status [--ledger FILE] [--root DIR] [--write]
python scripts/batuta.py report hook-subagent-stop < payload.json
```

- Where things live: briefs in `<coordination_root>/delegation/<id>.brief.md`, the ledger in
  `<coordination_root>/delegation/ledger.md` (`coordination_root` is `.batuta` by default). The ledger is one Markdown
  table (C04): ID, Agent, Model, Brief, Report, Status, Accepted, then the optional Provider, Tokens in, Tokens out, Cost
  USD, Superseded by and Notes. Status is one of drafted, pending, launched, complete, incomplete, defective, accepted,
  superseded, lost, timeout, error, over-budget; Accepted is `yes` or `no` (`y` and `n` are read, never written). The
  evidence of an acceptance goes in Notes.
- `route check` fails when an agent file does not satisfy C18, when its `model` differs from the model of the role of the
  same name, or when its role runs on Haiku and the file lacks `omitClaudeMd: true`. An agent file without a role is a
  warning.
- `brief new` takes the model and the kind from the agent (searcher: haiku, lookup; runner: haiku, run; implementer: sonnet,
  implement; doc-writer: sonnet, docs; reviewer: opus, review; general-purpose needs `--model` and is research). The kinds
  implement, job and skeleton carry the contract-first sections. `brief lint` refuses a brief with an unfilled
  `<fill: ...>` slot, a missing section or header field, or a check without a backticked command, and warns about an
  escalation, the fable model, more than eight deliverables and a write scope that overlaps another open brief.
- `report check` exits 0 when every deliverable is DONE with evidence, 1 when the report is defective (a missing row, a
  placeholder, a bad status, a missing Red run or Production path section), 2 when it is well formed but some rows are
  PARTIAL or BLOCKED. `report ledger-status` is a dry run unless `--write` is given.
- The SubagentStop decision holds a briefed agent once until its report passes: it blocks (`decision: block`, exit 0)
  when the final message lacks the `BRIEF:` and `REPORT:` lines or the report is missing, defective or incomplete. It
  allows an agent that was not briefed, and on the second attempt it allows and appends a dated UNVERIFIED line to
  `<coordination_root>/delegation/unverified.log`, so it never loops. An internal error allows the stop. The plugin's hooks
  file registers it under the id `subagent-stop`.
- Ledger writes are atomic: the new file is written next to the ledger and replaced in one step under a lock file, the
  ledger is re-read just before the replace so a row a concurrent writer added is kept, and a result that does not satisfy
  C04 is refused with the file untouched.

## Areas `size`, `tech`, `adr` and `spec`: the design gates before any code

```
python scripts/batuta.py size lint [--root DIR] [--sizing FILE] [--catalog FILE]
python scripts/batuta.py tech lint [--root DIR] [--sizing FILE] [--max-age-days 90]
python scripts/batuta.py adr new --title TITLE [--apply]      # then: adr lint
python scripts/batuta.py spec new --title TITLE [--tier S|M|L] [--apply]
python scripts/batuta.py spec lint [--spec ID] [--catalog FILE]
python scripts/batuta.py spec trace ID [--tests PATH] [--apply]
python scripts/batuta.py spec show ID
python scripts/batuta.py spec approve ID                      # manual path: a human types the phrase at the console
python scripts/batuta.py spec hook-approval < payload.json     # dry run of the hook handler, never writes
python scripts/batuta.py spec freeze --check ID
```

- `size lint` reads `sizing.md` (C23) from the coordination root and the catalog from `docs/contracts/catalog.md` (C22). A
  component has a unit when its line says `(unit: <id>)` for a Parallel units row, or its name appears in a Modules or
  Parallel units row; a component without a unit is a warning, never a failure. Totals are the counts in the Size estimate cells, per owner unit and per repository.
- `tech lint` fails a range, a missing source or a date that does not exist; a date older than `--max-age-days` is a warning.
- `adr new` and `spec new` are dry runs until `--apply`. A change to a decision is a new ADR that supersedes the old one;
  `adr lint` flags overdue `review-by` dates and broken supersession links.
- A spec lives in `specs/<NNN-slug>/` (`spec.md`, `plan.md`, `tasks.md`, `approvals/`, `evidence/`,
  `test-change-requests.md`); `specs/000-foundation/constitution.md` holds the constitution and the tiers. Template examples
  are HTML comments and never count as requirements, tasks or approvals.
- Every active requirement names a Gate: a backticked command or a test id (`path` or `path::name`). Tests tag requirements
  with a comment line `# REQ: <id>[, <id>]` (Python) or `// REQ: <id>` (JavaScript, TypeScript); `spec trace` fails on
  orphans, unknown or retired ids and test files without a marker (a Draft spec is exempt from the orphan rule).
- The freeze: `spec show ID` prints the files that are hashed and the phrase to type, `approve <spec id> <first 12 hex of the
  spec sha256>`. The prompt hook records it where hooks run; `spec approve ID` is the path where they do not, and it reads the
  phrase from the console device (`CONIN$`, `/dev/tty`), so it refuses piped input and runs only in an interactive terminal.
  `spec hook-approval` is a dry run and never writes. A prefix that is not the current spec's is refused and nothing is written. `spec freeze --check ID` reports VALID, or VOID with the files
  that changed, were deleted or are no longer covered.
- Gates name what the freeze hashes: every token of a Gate that resolves to an existing file or folder under the root is hashed
  (folders expand, backslashes are read as slashes, `..` is folded and one that leaves the root is refused); a Gate in Review
  or Frozen that names none is a lint failure, as is prose around a span, a bare file name or a command that cannot fail
  (`true`, `exit 0`, `echo ...`). A `# REQ:` marker counts only as a real Python comment token, and a `// REQ:` marker only
  outside strings, template literals and block comments.
- Residual risk (waived for this unit, review F-02): a schema-valid approval record written by another process (an inline
  interpreter) is indistinguishable from a captured one. The controls are the approvals write guard, the guard on the three
  approval commands and the permission preset that deny agents those writes, and human review of the committed record.
- Console reading (review F-01): `spec approve` needs a console on standard input (on Windows a console handle, on POSIX a tty
  with a `/dev/tty` that opens) and waits at most 300 seconds for the typed phrase, then refuses with exit 1 and writes
  nothing. Keystrokes injected into the console by another local process are the same waived class as the inline interpreter
  above: a deliberate local-process attack that the guards deny on its direct paths.
- A Gate passes only when it yields at least one hashable test file (a path that looks like a test); configuration and
  documentation files named next to it are still hashed but never count. A backticked command starts with a known runner, an
  executable on the PATH or a script of the repository, and a chain that can never fail (`|| true`, `; exit 0`,
  `python -c pass`, `echo ...`) is refused.
- Gate vocabulary: a Gate command starts with a runner of the documented list (python, py, pytest, uv, poetry, tox, nox, hatch,
  node, npm, npx, pnpm, yarn, bun, deno, vitest, jest, go, cargo, dotnet, mvn, gradle, java, make, bash, sh, pwsh, powershell,
  ctest, cmake, bazel, rspec, bundle, ruby, php, phpunit, swift, mix, R, Rscript, julia, among others) or a script of the
  repository that exists; the PATH is never consulted, so lint gives the same answer on every device. A leading `cd <dir> &&`
  and a trailing `&& echo ...` are fine; a command after a double pipe, an unconditional success after the test, `ls`, `cat`
  and other read-only commands alone, and `--collect-only` or `--dry-run` listings are refused. Test files are recognized by
  the common conventions (`test_*.py`, `*_test.py`, `*.test.*`, `*.spec.*`, `__tests__/`, `*_test.go`, `tests/`, `src/test/`,
  `*.Tests` folders); `conftest.py`, `__init__.py` and non-code files never count as the test, though they are hashed when named.
- A Gate's exit status must be the test's: a double pipe, a pipe after the test (unless the Gate starts with `set -o pipefail` in
  bash or sh; PowerShell pipes are refused), a `;` or `&` chain that does not end with a test invocation naming a test path, an
  inline `python -c` that runs no test runner, and info or listing invocations (`--version`, `-h`, `--help`, `--collect-only`,
  `make -n`, `npm ls`, `pip list`) are refused; `bash -c`, `sh -c`, `cmd /c`, `pwsh -Command` bodies are analysed with the same
  rules. Quoting follows POSIX (no escape inside single quotes). Under a test folder only test-named files count as the test
  (`test_*.py`, `*_test.py`, `*.test.*`, `*.spec.*`, `*_test.go`, Rust `tests/*.rs`, Jest `__tests__/*`); helpers and fixtures
  are hashed when named.
- The approval phrase is the whole first line: after trimming, the first line of the typed prompt must equal
  `approve <spec id> <first 12 hex>` (keyword and hex in any case). Other text on that line, even after a correct phrase
  (`approve 001-x abc123def456 -- no wait, do not`), is refused with a message and nothing is written; later lines are ignored.
- Pipefail and shell wrappers, tightened: `set -o pipefail` counts only as a `set` segment before the pipe whose option is exactly
  `pipefail` after `-o` (or in a combined flag such as `-eo`), never after a `set +o pipefail`, never under `cmd` or PowerShell;
  in a `;` or `&` chain nothing may follow the test (not even `cd` or `export`), only `&&`. For sh, bash, zsh and dash any
  short-flag cluster holding `c` (`-lc`, `-ec`) is the run flag; for PowerShell any prefix of `-command` of at least `-c` is,
  and `-EncodedCommand` (any prefix of at least `-e`, or `-ec`) is refused. A Rust file counts as a test only directly under `tests/`.

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
  `wmic` or `Get-CimInstance` on a parent), and `exec`, `eval` or `compile` of anything but a string literal. It reads every
  Python source the interpreter can import or run: `.py`, `.pyw` and any file the configured test command names explicitly
  (`python run_checks -v` names `run_checks`). A finding introduced inside the checked range fails unless an approved change request
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

## Areas `gate`, `skeleton`, `provider` and `lessons`: only verified results are approved and promoted

Every lifecycle gate (`L0-understand` to `L10-lessons`) ends with an evidence file from an agent that did not build the
result. The checkers read artifacts, never prompts.

```
python scripts/batuta.py gate evidence-lint specs/001-x/evidence/L7-build.md
python scripts/batuta.py gate status 001-x [--set L7-build=passed] [--apply]
python scripts/batuta.py gate check 001-x [--release] [--strict-commits] [--no-commit-check] [--readiness FILE] [--catalog FILE]
python scripts/batuta.py gate thresholds [--check [--against REF] | --propose name=value --reason TEXT] [--apply]
python scripts/batuta.py gate promote --repo owner/repo --pr N [--require CHECK] [--sha SHA] [--local-evidence FILE] [--apply]
python scripts/batuta.py gate promote --branch task/x --into develop --local-evidence FILE [--apply]
python scripts/batuta.py gate hook-stop < payload.json
python scripts/batuta.py skeleton check [--release] [--tests-record FILE] [--previews FILE] [--check-network]
python scripts/batuta.py provider lint [--catalog FILE] [--models DIR]
python scripts/batuta.py provider check --response FILE [--id ROW]
python scripts/batuta.py lessons check [--lessons FILE]
```

| Files | Where |
|---|---|
| Evidence | `specs/<feature>/evidence/<gate>.md` (C09) |
| Status | `specs/<feature>/status.md` (C10) |
| Approval | `specs/<feature>/approvals/<stamp>.json` (C06) |
| Thresholds | `specs/000-foundation/thresholds.json` (C11) |
| Readiness | `data/derived/readiness.json` or `docs/design/readiness.json` (C27) |
| Catalog | `docs/contracts/catalog.md` (C22) |

- Routing: a gate in `gates.critical` (and `L7-build` of a unit in `gates.critical_units`) needs `role: reviewer` on
  `gates.adversary_model_critical`; every other gate needs `role: adversary` on `gates.adversary_model_routine`. A script
  or the builder is never the independent check. HTML comments are stripped before any file is read.
- `gate check` fails on: a gate passed out of order or without valid evidence; evidence whose commit is not in the history
  or goes backwards along the gates; release evidence for a commit older than the head (changes under
  `specs/<feature>/` are allowed); a void approval (a hashed file changed, the typed phrase `approve <spec id> <first 12 hex>`
  missing, an agent as approver); a waiver without a dated human line or written by an agent role; a phase that does not
  follow the gates; and, at L9 or with `--release`, any component in the readiness document that is not real.
- `gate status --set <gate>=passed` runs the same evidence checks first and never sets `waived`: a waiver is a line a human
  writes in the status file (`gate`, `reason`, `by`, `date`).
- `gate thresholds` only lets a value go up. A decrease needs a history entry and a human waiver of `L9-promote` dated the
  same day; `--against REF` finds a value lowered by editing the file.
- `gate promote` never overrides a failed or pending check and never switches branches; a repository without CI promotes with
  local test output that names the full head SHA. The merge command is printed unless `--apply` is given.
- Settings that can weaken a gate come from the base revision of the checked range, never from the change under review: `gate check`
  reads the thresholds (and runs the ratchet on them: a lowering inside the range fails unless a human waiver of L9-promote of that
  date and a history entry cover it) and the `gates` block of `.batuta/batuta.json` (critical gates, critical units, adversary models)
  from the merge-base with the target branch (`origin/develop`, `develop`, `origin/main` or `main`), or from `--against REV`. A change to
  the gates block inside the range is a WARN naming the commit; the check keeps routing by the base revision's settings. A
  configuration named by `--config` or the environment is used as given. The target branch is the remote's default branch
  (`origin/HEAD`), else `origin/develop`, `develop`, `origin/main`, `main`, `origin/master` or `master`. When none shares history
  with HEAD, `gate check` says `no base revision: thresholds and routing were not compared` (WARN, exit 2); when HEAD is the
  target itself it warns that the range is empty (a change committed directly on the target branch is not compared). `--against`
  must be an ancestor of HEAD, and CI passes the pull-request base explicitly with --against. A lowering made in several steps
  passes when a chain of history entries leads from the base value to the final one and every decrease has a human waiver.
- Evidence must not predate the change it certifies: each phase is checked at its own gate, so for each passed gate a path the gate
  judges must not change between its evidence commit and the next passed gate's evidence commit (the last passed gate is bound by
  the head only while it is being passed with `gate status --set`; L9 evidence must describe the head until L10 passes). The paths
  a gate judges: L0 the spec, tasks and trace of the feature; L1 also the sizing; L2 the ADRs and technology decisions; L3 the
  contracts and catalog; L4 also the models; L5 the spec, contracts and decisions; L6 and L8 the code and the readiness documents;
  L7 the code and tests. Otherwise `gate check` fails with `evidence ... predates the change`. The coordination folder `.batuta/`
  never counts as a change, and never ages the readiness document. A change to a path the newest passed gate judges, made after
  its evidence, is a WARN (`the change after the last passed gate has not been reviewed`, exit 2), so a unit stopped at L7 with
  later code is never green. Only the newest 500 commits of the history have their files read: when a range is longer, a WARN says
  older judged changes were not compared and names the limit.
- `gate tests-record` writes the contract-tests record (C34, `docs/design/contract-tests.json`), validated before it is written:
  `--run` (runs the python test files the catalog names, one unittest discovery each; no test run is a skip) and `--result
  <test path>=fail|skip` (repeatable; a pass is recorded only by `--run`, never typed in). It records HEAD and refuses a working
  tree with uncommitted changes outside `specs/`.
  `skeleton check` reads the record (the default path, or `--tests-record`): a failed or skipped test fails, a record for a commit
  with later code or contract changes fails, and no record is a WARN. `gate check` reads it at the release gate.
- Tool scope of the `adversary` agent: the agent definition cannot scope `Write` or `Bash` to a path, so the limit to
  `specs/*/evidence/*.md` is enforced by the guards, not by the definition; the guard is listed for the guards unit.
- Stop hook: `gate-stop` (a handler in the `gate` area, wired by `hooks.json`) blocks once while a unit with uncommitted
  changes has a failing gate check, then writes `- <date> UNVERIFIED: ...` to the unit's status file and lets the session
  end. A unit's `scope: [paths]` front matter, and the write scopes of the units named in its `tasks.md` (the sizing's Parallel
  units table), tie changes outside `specs/<feature>/` to it. The handler keeps its own once-per-failure state in
  `<coordination root>/gate-stop.state` (keyed by session and failure, at most 1000 entries, replaced atomically), so it blocks
  once even when the host sends no `stop_hook_active`; an internal error allows the stop and says why in the handler result's
  `message`. Residual, listed for the hooks units: the handler does not know which session changed the files, so a session that
  changed nothing can be held by a unit another session left dirty in a shared checkout; recording each session's touched paths
  needs a PostToolUse hook.
- Promotion evidence for a head without CI shows tests that ran: `Ran N tests` with N above zero and `OK`, or `N passed`; zero
  tests, an all-skipped run or any failure line is refused.
- `lessons check` ignores lesson lines inside HTML comments and code fences and refuses a blank field.
- `skeleton check` reads the catalog hash and the age of the readiness document (more than `--lag` commits outside `specs/`
  behind the head is stale); before L6-skeleton the document is absent and the check says `SKIP`. The network is touched only
  with `--check-network`.
- `provider lint` needs, per catalog row, one state per `missing-data behavior` item with a test that exists and is its own;
  a provider in the provider column needs its `provider(kind)` state.

## Area `context` and `memory`: what loads at every session start

Claude Code loads user and project CLAUDE.md files and unscoped `.claude/rules/` files in full, `.claude/rules/` files
with `paths` front matter only with a matching file, `@imports` eagerly, and only the first 200 lines or 25 KB of each
project's MEMORY.md; topic files are read on demand. These areas keep the always-loaded part small and measured.

| Layer | What | Loads |
|---|---|---|
| L0 | rendered user core, project CLAUDE.md chain, unscoped rules, MEMORY.md index | every session |
| L1 | `.claude/rules/<id>.md` stubs with `paths` | with a matching file |
| L2 | reference files listed in `INDEX.md` with triggers, memory topic pages | when the task matches |

```
python scripts/batuta.py context build --manifest knowledge/manifest.json --out OUT [--apply]
python scripts/batuta.py context render --template templates/user/CLAUDE.template.md --values values.json --out ~/.claude/CLAUDE.md [--apply]
python scripts/batuta.py context check [--project DIR] [--home DIR] [--user-core FILE] [--memory-dir DIR] [--chain-root DIR]
python scripts/batuta.py context measure [--project DIR]
python scripts/batuta.py memory index --memory-dir DIR --project NAME [--topics FILE] [--budget FILE] [--apply]
```

- `context build` validates the manifest (C12: acyclic `requires`, unit files exist inside the manifest folder,
  summaries of at most 160 characters), writes `INDEX.md` (llms.txt style, one line per unit with load, triggers and
  requires), `CORE.md` (the `load: always` units) and `rules/<id>.md` (one stub per `load: path` unit), and refuses with
  `REFUSED` when the core or index exceeds the manifest budget. Dry run by default; output is sorted, LF only and
  carries no timestamp, so a second `--apply` reports `SAME` for every file.
- `context check` measures bytes, not characters. Budgets come from `batuta.json` (C01 `budgets`): `user_core_bytes`,
  `project_core_bytes`, `unscoped_rules_bytes`, `memory_index_bytes`, `memory_index_lines`. Exactly at a limit passes;
  one byte over fails (exit 1). A MEMORY.md over 200 lines or 25 KB fails for any project; another project's index
  over the C01 budget but under the cap is a warning (exit 2). A missing user core is `MISSING`; a project without a
  memory folder is reported `SKIP`.
- `@path` imports in the user core, the project CLAUDE.md chain and unscoped rules are counted the way Claude Code loads
  them: eagerly, relative to the importing file (`~/` is the home folder), up to 4 hops; a space in a path is written
  as `\ ` (`@Design\ Docs/notes.md`); code blocks, code spans and missing files are not imports. An import cycle or an
  import beyond 4 hops is a `WARN`. `measure` lists each import as its own L0 row.
- A memory index that belongs to an ancestor folder of the project is a warning, not a failure, because whether
  Claude Code keys memory by the repository root is UNVERIFIED. Lines are counted by `\n`, not by Unicode separators.
- `context build` writes the links of `INDEX.md` and of the stubs relative to where each page is written, and warns
  when the core exceeds the C01 `user_core_bytes`.
- `memory index` writes, replaces and removes only pages that carry its generation mark. A file in `topics/` without
  the mark is the owner's: it is never read as a source of entries, never removed, and when its name is the page of a
  topic that has members the run fails (`FAIL`, exit 1, nothing written) and names the file. Pages written by an
  older version of the tool, before the mark existed, are migrated with `--adopt-legacy`, which treats unmarked
  pages named like a topic id as generated.
- `context measure` always exits 0 and prints each file's layer, bytes and estimated tokens (bytes divided by 4) and
  the L0 total.
- `memory index` needs a topics file (C13) listing the project; a project that is not listed exits 2 with nothing
  written. Memory folders are found under `<home>/.claude/projects/<sanitized project path>/memory`, where every
  character of the project path that is not a letter or digit becomes a hyphen.
- Templates: `templates/user/` (the generic user core and its `reference/` files) and `templates/knowledge/` (a sample
  manifest). Placeholders: `language`, `tone`, `user_name`, `python`, `deploy_root`, `temp_root`, `data_root`,
  `models_root`, `worktrees_root`; a placeholder without a value is refused.

## Area `device` and `preflight`: install, verify, restore and back up a device

A device gets a copy of the plugin (`scripts/`, `contracts/`, `templates/`, `reference/`, `.claude-plugin/`) and a
profile, `device.json` (C15), holding that device's interpreter and roots. No shipped file holds a machine path: roots
come from `batuta.json` (C01 `roots`, `$VAR` expanded) or the environment (`BATUTA_HOME`, `BATUTA_TEMP`, ...), and a
root that resolves inside a repository, to a drive root, to the home folder or onto a missing drive is a configuration
error.

```
python scripts/batuta.py device deploy [--deploy-root DIR] [--python PATH] [--apply]
python scripts/batuta.py device restore [--deploy-root DIR] [--stubs RULES_DIR] [--force] [--apply]
python scripts/batuta.py device check [--hook]
python scripts/batuta.py device backup --out DIR [--allow SHA256] [--apply]
python scripts/batuta.py preflight limits
python scripts/batuta.py preflight prereqs --register FILE [--timeout SECONDS]
```

- `device deploy` is a dry run unless `--apply`, refuses a deploy root inside a repository, on a missing drive or in a
  folder that holds a `scripts/` of someone else, and mirrors only its own folders (a `batuta.json` next to the copy
  stays). The contracts' `fixtures/` (test data) are not copied. A second `--apply` changes nothing.
- `device restore` merges `templates/presets/*.json` (C17) into `~/.claude/settings.json` without removing or reordering
  anything, after a `.bak-<stamp>` copy. A running Claude session can rewrite that file at any time (reported with
  about 15 parallel sessions), so the file is re-read after the write and what is missing is merged again into the file
  as it is now, at most 3 attempts 0.5 s apart; what is still missing is an error naming the items. A value of the
  wrong type (for example `permissions.deny` not a list) refuses and touches nothing. The `session-check` preset is
  rendered per device (the absolute interpreter and launcher from the profile, exec form) and skipped with a WARN while
  the device copy has no `scripts/hook.py`.
- The user core is rendered when `batuta.json` has `user_core.template` (a path, relative to the deploy root) and
  `user_core.values` (the template's `{{name}}` values); without it the step is skipped with a WARN naming the key.
  `--stubs` installs the path-scoped stubs of a `context build` into `~/.claude/rules/`, rewriting each link so it
  resolves from there (the build layout's `../../units/...` is valid only next to the build output); a file that is not
  a generated stub is never replaced without `--force`.
- `device check` reads only, finishes in well under two seconds and never runs git, a subprocess or the network.
  `--hook` prints the SessionStart object (at most 10,000 characters) and exits 0; the same check is the `session-check`
  hook handler.
- `device backup` collects agents, the agentic keys of `settings.json`, memory pages, hand-written rules, the user
  `batuta.json` and, when it is not rendered from a template, `CLAUDE.md`. Rendered files and generated stubs are
  rebuilt, never backed up. Any secret pattern refuses the whole backup and writes nothing; a reviewed line is exempted
  by its sha256 with `--allow`.
- The secret scan reads every file in every plausible decoding (UTF-8, UTF-16 little and big endian, and the raw bytes
  with the NUL bytes removed) and also scans each file name; a hit in any refuses the whole backup. `--out` must be
  empty, new, or hold a `MANIFEST.json` from an earlier backup (a bundle), and every path and area must resolve inside
  it once links and junctions are resolved, or nothing is written or removed. Deploy applies the same resolve-inside check.
  A link or junction (a symlink, or any Windows reparse point) found where a managed file or folder belongs, or anywhere
  below a managed area, is reported and refused (exit 1): the mirror never descends into it and never deletes through it.
  A reviewed token is one hit however many decodings show it, so one `--allow` hash exempts it.
- A re-read or replace that fails with a file-system error (a sharing violation, which running sessions cause on
  Windows) or that finds a half-written file counts as a lost race: it is retried, and after the last attempt the error
  names the missing items and the cause. Residual race, not closable without a file lock that Claude Code does not
  take: another session's write that lands in the microseconds between restore's compare read and its `os.replace` is
  lost, and restore still reports success; the verified write detects its own items being dropped afterwards, not that.
- The session-start line is INCOMPLETE only for a failed item with its exact fix. A user value kept on purpose (an
  existing `env` key with another value) and a preset skipped for a missing launcher are shown as notes and leave it OK.
  A broken device copy is repaired from the source it was deployed from (`deployed_from` in its profile), never by
  deploying the copy into itself; when no source exists the fix says to reinstall the plugin.
- `preflight limits` reports a missing GPU or Node as absent (Node is needed only by the `npx` entry), not as an error.
  `preflight prereqs` reads a register of `name`, `why`, `owner_action` and `probe` (a command list or a shell string),
  never prints a probe's output, and exits 1 when any prerequisite is missing.

Managed settings (`templates/managed-settings.example.json`) are the layer users cannot remove, for organizations.
Claude Code reads a `managed-settings.json` from a system folder: on Windows `C:\Program Files\ClaudeCode\`, on macOS
`/Library/Application Support/ClaudeCode/`, on Linux and WSL `/etc/claude-code/` (UNVERIFIED here: confirm against
code.claude.com/docs/en/settings before rolling it out). Copy the example there, keep the deny rules, and set
`allowManagedHooksOnly` to restrict hooks to the managed ones.

## Areas `guard` and `leaks`, and the hook launcher

Guardrails run as PreToolUse hooks through one launcher, `scripts/hook.py <handler id>`, and each has a script and a CI
equivalent (see `docs/reference/enforcement-matrix.md`).

```
python scripts/batuta.py guard automation|locked-tests|approvals|secrets|destructive|require-brief --payload FILE [--explain]
python scripts/batuta.py guard scan --diff origin/develop..HEAD [--root DIR]
python scripts/batuta.py leaks scan [--root DIR] [--deny-list FILE] [--allow-email PATTERN]
```

- The launcher fails open: any problem of its own (unknown id, crash, invalid result) exits 1 with the reason on
  stderr, which Claude Code treats as a non-blocking error. A guard that must block when it cannot decide is wired with
  `onFailure: "block"` in `hooks/hooks.json`; the matrix lists which ones.
- `guard <name>` exits 0 for allow, 1 for deny, 2 for ask. `--explain` says what the guard checks and what it found
  (for example, no lock file means nothing is locked yet).
- Optional `batuta.json` keys: `tdd.lock_file`, `guards.secret_globs`, `guards.protected_branches`,
  `guards.destructive_disable`, `guards.require_brief` (`deny`, `ask`, `off`), `guards.scan_ignore`, `leaks.allow_emails`.
- `leaks scan` never reads a deny-list from inside the repository; keep that file outside it and pass `--deny-list` or
  set `BATUTA_LEAKS_DENY_LIST`.

## Area `init`, `fragments` and `reserve`: adopt, check, update and remove; shared files and numbers

One command adopts Batuta on a device or in a project. Every write is a dry run unless `--apply`, atomic, and reversible:
what is replaced is backed up next to it as `<name>.bak-<stamp>`, and what `init` wrote is recorded in an install manifest.

```
python scripts/batuta.py init user [--home DIR] [--deploy-root DIR] [--python PATH] [--var user_name=...] [--apply]
python scripts/batuta.py init project [--target DIR] [--var project_name=...] [--apply]
python scripts/batuta.py init doctor [--project DIR] [--channel auto|device|plugin]
python scripts/batuta.py init update [--scope project|user] [--target DIR] [--apply]
python scripts/batuta.py init uninstall [--scope project|user] [--target DIR] [--apply]
python scripts/batuta.py fragments changelog REPO_DIR [--apply]
python scripts/batuta.py fragments i18n DICTIONARY.csv FRAGMENT_DIR [--apply]
python scripts/batuta.py reserve next REPO KIND [--from N] [--root DIR] [--apply]
python scripts/batuta.py reserve list [--root DIR]
npx github:fsantibanezleal/CAOS_Batuta <area> <verb> ...
copier copy gh:fsantibanezleal/CAOS_Batuta <destination>
```

- `init user` writes `<BATUTA_HOME>/batuta.json` only when it is missing (roots from `BATUTA_*` variables, the user core
  template and its values), then runs the device area's deploy and restore and installs the agent files into
  `~/.claude/agents/`. The manifest is `<deploy root>/installed.json`.
- `init project` renders `templates/project/` of the plugin with five variables (`project_name`, `python_version`,
  `test_command`, `default_branch`, `batuta_ref`, the release tag of the installed version that the CI checks are fetched
  from, moved by `init update`; the defaults are the target folder's name, `3.12`, `python -m unittest discover -s tests -t . -v`
  and `main`). An existing `CLAUDE.md` or `AGENTS.md` is backed up with a stamp before it is replaced;
  `.claude/settings.json` is merged append-only (the permission rules of the template are added, nothing is removed or
  reordered) after a backup; a file the template does not own is never touched. No git repository at the target is a
  WARN (the workflow is still written); a target inside another repository is a WARN that GitHub reads the workflow at
  the repository root only. The manifest is `<project>/.batuta/installed.json` and carries no machine path.
- Ownership: a seed file (`.batuta/batuta.json`, the constitution, thresholds, the example feature, the foundation test) is
  written once and is yours afterwards; `init` and `init update` never overwrite it. A managed file (AGENTS.md, the
  workflow, the agent files) is rewritten only while it is an unchanged installed copy; a hand-edited one is kept and
  reported DIFFERENT (exit 2) unless `--force` replaces it after a backup. An existing CLAUDE.md, in a project or the user
  core, keeps its content and gains one block between `<!-- batuta:begin ... -->` and `<!-- batuta:end -->`, rewritten in
  place by `init update`. `init uninstall` refuses a manifest whose bases, paths or links leave the project or the Batuta
  home, deleting nothing.
- The workflow `.github/workflows/batuta-gates.yml` has one job, `batuta-gates`: full history, Python from
  `python_version`, the base revision from `github.event.pull_request.base.sha` (pull request) or `github.event.before` (a
  push, or the merge base with the default branch on a new branch or a force push), the test step `id: tests` running
  exactly `tdd.test_command`, then the Batuta checks. A WARN (exit 2) of a check is reported and does not fail the job; a
  FAIL fails it, and every check runs even after a failure.
- `init doctor` reports each probe OK, WARN or FAIL with its fix, without writing and in a few seconds, and compares the
  workflow's test step with `tdd.test_command` (a difference is a FAIL naming both strings). Git Bash on Windows is a FAIL
  for the plugin channel and not needed by the device channel; Node (npx channel only) and the `claude` CLI are WARN.
- `init uninstall` restores the backup of each file init replaced and removes each installed file whose hash (line
  endings ignored) is unchanged; an edited file is kept and reported DIFFERENT with exit 2, and the manifest keeps it for
  a later run. Folders init created are removed when empty. `init update` renders again from the current templates and
  backs up every file it changes.
- `fragments changelog` merges `changes/*.md` bullets under `## [Unreleased]` (file-name order, no duplicates, line
  endings kept) and `fragments i18n` merges `*.csv` rows into a dictionary (sorted dictionaries stay sorted, duplicate keys
  are refused with the file names); both delete the fragments only with `--apply` and change nothing on a refusal.
  `reserve next` gives the next number of a `repo:kind` sequence, recorded under an exclusive lock with `--apply`.
- The npx entry finds Python in this order: `BATUTA_PYTHON`, `py -3` (Windows), `python3`, `python`; one older than 3.10
  is skipped. Without a suitable Python it exits 1 and names every candidate it tried.

## Area `dispatch`

A brief (C02) is provider-neutral; the dispatcher decides where it runs. Every run returns a report that passes the same
gates and records provider, model, tokens and cost in the ledger. Runs are started by hand, bounded by time and cost, and
end with the command: nothing is scheduled, detached or kept alive.

```
python scripts/batuta.py dispatch plan --brief FILE [--lane subagent|sdk|provider:NAME] [--model ID] [--max-cost USD] [--report-only] [--allow-unpriced] [--root DIR]
python scripts/batuta.py dispatch run --request FILE [--apply] [--hours H] [--report-only] [--allow-unpriced] [--transport-fixture FILE] [--root DIR]
python scripts/batuta.py dispatch resume --result FILE [--apply] [--hours H] [--root DIR]
```

| Lane | Runs on | Credential |
|---|---|---|
| `subagent` (default) | a Claude Code subagent: the command prints the launch specification, the main session launches it | the Claude Code login |
| `sdk` | the Claude Agent SDK on an API key (`pip install claude-agent-sdk`), resumable | `ANTHROPIC_API_KEY`, or the file named by `dispatch.sdk.key_file` |
| `provider:NAME` | one tool-less call: `openai-compatible`, `gemini`, `bedrock` or `vertex`; returns a report and an optional patch | the environment variable named by the provider in `batuta.json` |

- `dispatch run` is a dry run by default: it prints what would be sent with every secret redacted. `--apply` runs the lane,
  writes the report, the C30 result (`<id>.dispatch-result.json` next to the request) and the ledger row.
- A billed lane needs a cost cap (`caps.max_cost_usd_per_task`, or `--max-cost` below it) and a verified price in
  `batuta_lib/dispatch/prices.json`; a model without one is refused unless `--allow-unpriced` (the cap then cannot be
  enforced and the cost is recorded as 0). The run stops BLOCKED (`over-budget`) when the projected or actual cost passes
  the cap.
- A provider lane has no tools: a brief of kind implement, job, skeleton or run is refused unless `--report-only`. A patch
  the provider returns is written next to the report and must stay inside the brief's write scope; apply it only after the
  gates pass.
- The sdk lane runs the batuta guards (the PreToolUse handlers of `hooks/hooks.json`, or the default set) through
  `scripts/hook.py` for every tool call, runs the checks of the brief before marking the result complete, and keeps its
  session id so `dispatch resume` can continue it within the cap that is left.
- `--transport-fixture FILE` answers provider calls from a JSON list of `{status, body, headers}` for offline runs.
- Cost is cumulative per task: `<id>.dispatch-state.json` next to the result holds the cost, tokens and (sdk lane) the time spent by
  every earlier run, resume and crash of the request; each call gets at most the cap that is left, and a call that ends without usage
  figures (crash, timeout, cut stream, an answer that cannot be parsed and carries none) is charged its full allowed budget, an upper
  bound. A rerun of a request therefore starts with the cap already reduced.
- The sdk guards: the PreToolUse handlers of `hooks/hooks.json` (matcher and timeout of each entry honoured), else every `guard-*` handler
  of the guard area. Every guard runs; the strictest answer wins. The lane refuses to run with no guard. Beyond the guards the session
  policy denies reading the process environment (which holds the key), pushing to protected branches, force pushes, merges, deletions
  and Docker prunes, and limits write tools to the brief's write scope, its report and the temp root.
- A provider lane result is `complete` only when the report gates and the brief's checks pass; with a patch it is `incomplete` until the
  checks can run on the patched tree. The patch scope and the report path are re-read from the brief at run time; a request that differs
  is refused.
- Known limits: the session's working directory is `--root` (the brief's `working directory` line is not used), the allowed tools come
  from the brief kind, there is no credential-helper command (C01 has no field for one), and whether the real SDK ends its CLI child and
  agent `run_in_background` jobs when a run is cancelled is UNVERIFIED (no SDK was installed to test it).
- Bedrock: name the inference profile id in `--model`, for example `global.anthropic.claude-sonnet-5-5`; Bedrock and Vertex rows of the
  price table are unknown, so those lanes need `--allow-unpriced` (the cost cap then cannot be enforced and the cost is recorded as 0
  and for a call that may have billed without usage figures only the token estimates are recorded, because an unpriced model has no rate to charge).
- Retries and cost: a retry is charged when the first attempt may have billed (an error after the send, a 5xx answer) and is sized to
  what is left of the cap; a 429 answer and a connection error before the send are free. A run of read timeouts therefore ends
  `over-budget` once the cap cannot cover another attempt. The shell-write check of the sdk policy cannot see writes made by code
  inside an interpreter (`python -c "open(...)"`): that stays with the brief's scope and the guards.
- Network: provider calls use the standard library's `http.client` (not `urllib.request`), TLS verification stays on, redirects are not
  followed, plain HTTP is allowed only for the local host. They honour `HTTPS_PROXY` (an http:// proxy URL, tunnelled with CONNECT)
  and `NO_PROXY` (host names and domain suffixes, `*`, an optional port; no CIDR ranges). `HTTP_PROXY` is not used because only local
  hosts may use plain HTTP.

## Adding an area

Create `scripts/batuta_lib/areas/<name>.py`:

```python
from batuta_lib.output import emit, item

AREA = "example"
HELP = "one line shown in `batuta.py --help`"

def _run(args):
    items = [item("OK", "hello")]
    return emit(AREA, "run", items, "run: 1 ok", getattr(args, "json", False))  # 0 ok, 1 failure, 2 warnings

def register(subparsers):
    parser = subparsers.add_parser("run", help="say hello")
    parser.set_defaults(func=_run)
```

The dispatcher imports every module in that folder in sorted order. A module that raises on import is reported as
`WARN area <name> failed to load: <error>` and skipped; the others keep working. Global options `--config PATH`,
`--json` and `--version` are available to every handler as `args.config` and `args.json`.
