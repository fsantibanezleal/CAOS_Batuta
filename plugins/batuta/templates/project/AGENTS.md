# {{ project_name }}: instructions for coding agents

This file is read by any coding agent that follows the AGENTS.md convention. Claude Code also loads `CLAUDE.md`, the
short core of the same rules.

## The workflow
1. Understand and size the work, then write a spec: `specs/<NNN-slug>/spec.md` with one EARS requirement per row, each
   with a gate (a command or a test id) that can run and fail. Create it with `spec new`.
2. A human approves the frozen spec by typing its approval phrase (`spec show` prints it). Agents never write approvals.
3. Write the failing tests first and lock them (`tdd lock`). The red commit is `[red] T-NNN <title>`, the passing one
   `[green] T-NNN <title>`, a cleanup `[refactor] T-NNN <title>`.
4. Implement until the tests pass; run `gate check <spec id>` and attach the independent check's evidence.
5. Open a pull request; the `batuta-gates` job must pass before merge.

## Commands
- Tests: `{{ test_command }}`
- Python version in CI: {{ python_version }}
- Default branch: `{{ default_branch }}`

## Boundaries
- `specs/000-foundation/constitution.md` outranks every plan. `specs/000-foundation/thresholds.json` only ratchets upward.
- Locked tests, approvals and `.batuta/test-locks.json` are not edited by agents.
- Project configuration is `.batuta/batuta.json`; roots (temp, data, worktrees) come from environment variables
  (`BATUTA_TEMP`, `BATUTA_DATA`, `BATUTA_WORKTREES`), never from a path written in this repository.
- English only in code, comments, docs and commit messages.
