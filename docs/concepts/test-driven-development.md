# Test-driven development on artifacts

Tests are written first, locked by hash, and the order is proved from git history by a checker, not trusted from a
prompt. Continuous integration is the authority; the PreToolUse guard that blocks editing a locked file is a second,
separate layer. This page describes the lock, the commit grammar, what `tdd check` proves, how a locked test may change
and where the method stops.

## Why artifacts and not a prompt

The research found that the ecosystem's test-first tools judge with a language model and do not detect tampering
deterministically (tdd-guard and Probity, read from source on 2026-10-11), and that the cheating that does occur is mostly
hardcoding and heuristics on ambiguous problems, with test-file edits rare but real (EvilGenie,
https://arxiv.org/abs/2511.21654). Anthropic's own guidance names the pattern ("have one Claude write tests, then another
write code to pass them") and a Stop hook as "a deterministic gate"
(https://code.claude.com/docs/en/best-practices). Batuta takes the deterministic part: diff the test files, forbid weakening
markers, count assertions, replay the history. Ambiguity is handled earlier, by the spec. See [principles](principles.md),
principle 1.

## The lock (contract C07)

`tdd lock --task T-001 tests/test_x.py --apply` appends an entry to `.batuta/test-locks.json` (append-only): the path, the
SHA-256 of the file with CRLF read as LF, the task, the requirement ids from the file's `# REQ:` marker lines, the commit
and the time. A path locked again with the same hash is `SAME`; a changed hash is refused unless `--supersedes
--change-request <id>` names an approved row. A file with no `# REQ:` marker is locked with a `WARN`. Real output:

```
NEW would lock tests/test_greeter.py for T-001 (fd508c2222be) (tests/test_greeter.py)
tdd lock: dry run, nothing written (use --apply)
NEW locked tests/test_greeter.py for T-001 (fd508c2222be) (tests/test_greeter.py)
OK wrote 1 entry to .batuta/test-locks.json
tdd lock: done
```

## The commit grammar (contract C32)

A step of the task is one commit whose message is `[red] T-001 title`, `[green] T-001 title` or `[refactor] T-001 title`,
then a blank line, an optional body and a last paragraph of trailers. `tdd commit --red|--green|--refactor T-001 -m TITLE
PATH... --apply` stages exactly the files named (never everything at once) and writes that message. The only override is the
trailer `Test-Change-Approved: <change request id>`.

```
OK committing: [red] T-001 Greet by name
OK committed 0aa4235: [red] T-001 Greet by name
...
OK committing: [green] T-001 Greet by name
OK committed 5f79a9d: [green] T-001 Greet by name
```

The test-author writes the red step and the implementer the green step, in two different agents (the `red` and `green`
skills), so the implementer never writes the oracle it is graded against.

## What `tdd check` proves

`tdd check [--range A..B] [--replay]` walks the history and fails on:

- a `[green]` commit without an earlier `[red]` of its task;
- a `[red]` commit that adds no test file, holds anything but tests, test support files and the lock, or has a test not
  locked with its content at that commit;
- a commit that touches a path locked at its parent (a change of line endings only is not a change);
- a lock edited, shortened or extended by a `[green]` or `[refactor]` commit;
- a locked file whose hash at the end of the range differs from its newest entry;
- an added weakening marker: `unittest.skip`, `skipIf`, `expectedFailure`, `pytest.mark.skip`, `xfail`, `importorskip`
  and the JavaScript and TypeScript `it.only`, `describe.skip`, `test.todo`, `xit` and their aliases, resolved through
  imports, assignments and destructuring (Python is read with `ast`, so a marker inside a string or comment never counts);
- a test file whose assertion count dropped (a rename to a name no runner discovers drops it to zero).

A merge commit is checked against every parent. An empty range fails. A history with no red commit exits 2 with a WARN
(decision 22: a WARN is exit 2 everywhere); without a lock file it warns that nothing is locked and still checks markers and
assertions. Settings come from the range's base commit, never from the checked-out tree, so a change that loosens the
`tdd` block cannot approve itself; a change to it inside the range is a WARN naming the commit.

Real output on the guide's project:

```
OK 1 of 1 locked test file(s) match the lock at 5f79a9d
OK red commit 0aa4235 (T-001): tests/test_greeter.py fails at the red commit (exit 1) (tests/test_greeter.py)
OK 4 commit(s) checked against the red and green rules
tdd check: ok
```

## Replay

`--replay` checks each `[red]` commit out in a temporary worktree under the configured temp root and runs the project's own
test command once. A red counts only when a test of its own failed or errored: exit 0, exit 5, `Ran 0 tests` and the
failure of somebody else's test do not. The worktree has a random name with no `tdd`, `replay` or `batuta` in it, the
caller's environment is unchanged, and the worktree is removed on success, failure and timeout.

Replay also runs the tests at every commit that changes a test, a test support file or the test configuration, at every
`[green]` and `[refactor]` commit, and at the head, and compares the outcomes of every live locked test with the tests the
locked file defines: each must have run, and not be skipped, deselected or reported as an expected failure, whatever
configuration, hook, patch or import did it. The cost is one checkout and one run of the test command per such commit,
each bounded by `replay_timeout_seconds` (default 300), so a range with many test-changing commits is expensive; CI should
replay `<base>..HEAD` of a branch, not the whole history.

The head run is the project's real run (plan decisions 34 and 35). It runs the configured `tdd.test_command` verbatim in the
repository's own checkout and reads each test's outcome from that command's own output (unittest's verbose lines, a JUnit
file, or the summary of `pytest -rA`). A command that does not report each test is refused with the fix: configure
`tdd.test_command` to report each test, for example `python -m unittest discover -v` or `pytest -rA --junitxml=<path>`. The
default is `python -m unittest discover -s tests -p "test_*.py" -v` (with `-t .` when `tests` is a package). A working tree
that differs from HEAD is refused at the head check point, so product code cannot tell the head run from the CI run, and
the CI workflow of the project template runs exactly the same string as its test step.

## Changing a locked test

A locked test changes only through a change request (contract C33, `specs/<feature>/test-change-requests.md`, always
belonging to a feature). The flow is deliberately asymmetric:

1. An agent opens a request with `tdd change-request new --test PATH --requirement REQ-ID --reason TEXT --proposed TEXT
   --feature NAME --apply`. This appends an `open` row (the first request creates the file) and nothing else.
2. A person decides it, in one of two ways. `tdd change-request show CR-001` prints the phrase `approve CR-001 <12 hex>` (or
   `reject ...`; the 12 hex digits are the prefix of the SHA-256 of that row), and the person types it as a prompt; the
   UserPromptSubmit handler `tdd-change-request` records the decision, Decided by `typed prompt`, only when the first line
   is exactly that phrase and the row is still `open` with that hash. Or `tdd change-request decide CR-001 approve|reject
   --apply` asks on the console device (`CONIN$` or `/dev/tty`, never standard input), waits 300 seconds at most and records
   the operating-system account as Decided by.
3. The decision is a commit of its own. Then the change is committed with the trailer `Test-Change-Approved: CR-001`; `tdd
   check` honours the trailer only for a row already approved at the commit's parent, for the changed path, with a changed
   spec file in the same range. A commit that decides a row together with any other change fails, and so does a row born
   approved or a decided row that is edited.

A locked test may be renamed or deleted only under an approved request; for a rename the new path must itself be locked.
Request ids are `CR-NNN`, unique across features, because the id is the commit trailer. The guards deny agents the `decide`
command, every direct run of the hook launcher and direct writes to `test-change-requests.md`
([enforcement matrix](../reference/enforcement-matrix.md)); the guard's message points an agent to `tdd change-request new`.

## Forgery from inside the run

The locked tests run in a process that the code under test controls, so that code could forge the output it prints. This
cannot be closed from outside the process, and three checks narrow it (plan decision 37). A locked test passes at the head
only with exactly one result line that is `ok`: a skip, expected failure, unexpected success or duplicate line fails it. The
result lines must equal the runner's own summary (the number of lines equals `Ran N tests`, and the tally of failures,
errors, skips and the rest matches; the JUnit `tests` attribute equals its `testcase` elements). And a static scan of every
Python file of the repository finds patches to the runner's own classes and functions, pytest hooks that change collection
or reporting, a replacement of `sys.stdout` or `sys.stderr`, reads of the parent process and `exec`, `eval` or `compile` of
anything but a string literal; a finding introduced inside the checked range fails unless an approved change request names
the file. The remaining in-process forgery is an accepted residual (see [known limits](../reference/known-limits.md)): Batuta
guards against agents cutting corners, and deliberate forgery code is conspicuous in a diff.

## Settings of the area

The optional `tdd` block of `batuta.json` (contract C01 1.1) has `test_command`, `replay_timeout_seconds`, `lock_file` and
`markers`; the defaults and types are in the [configuration reference](../reference/configuration.md). Git 2.30 or newer is
required.

## Sources

- Design: software design document sections 4 (TDD-1 to TDD-4) and decisions 22 to 26, 31, 33 to 35 and 37; contracts C07,
  C32, C33 in `plugins/batuta/contracts/`; ADR-0006.
- The `tdd` area fragment, summarized in the [command reference](../reference/cli.md); `plugins/batuta/skills/red/SKILL.md`
  and `green/SKILL.md`.
- https://arxiv.org/abs/2511.21654 (EvilGenie), https://github.com/nizos/tdd-guard, https://github.com/nizos/probity,
  https://code.claude.com/docs/en/best-practices
- Real output captured in a scratch project (see the [first project guide](../guides/first-project.md)).
