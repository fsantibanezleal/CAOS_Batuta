---
name: red
description: Use when a task's tests must exist before its code (L7-build, red): a test-author writes failing tests, they are locked by hash and a [red] commit records them.
allowed-tools: Bash(python *) Read Grep Glob
argument-hint: <task id T-NNN>
---

# Red: failing tests first, locked

Gate: L7-build (red half). The tests are written by `batuta:test-author`, never by the agent that will write the code.

1. Brief and launch the test-author with the `brief` and `delegate` skills (`subagent_type="batuta:test-author"`, model from
   `route show`). Each test file carries one marker line `# REQ: <requirement id>` (`// REQ: ...` in JavaScript or TypeScript).
2. Run the project's test command. Every new test must fail for the right reason (the missing behavior), not for an import
   error or a typo. A test that passes before the code exists tests nothing: fix the test.
3. Lock the files by hash (a dry run first):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tdd lock --task T-001 tests/test_x.py`
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tdd lock --task T-001 tests/test_x.py --apply`
4. Commit the red step with the C32 message, naming the files explicitly:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tdd commit --red T-001 -m "TITLE" tests/test_x.py --apply`
5. Check the history so far: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tdd check`
6. Hand over to the `green` skill. A locked test changes only through an approved change request (see `green`); the locked-tests
   guard denies any other edit.

On a non-zero exit: exit 1 from `tdd lock` is a refusal (a changed hash without an approved request, a path outside the
repository); exit 1 from `tdd check` is a broken rule (a red commit whose tests are not locked or do not fail): fix and
re-run, never edit the lock file by hand. Exit 2 is a warning (for example no red commit yet): report it.
