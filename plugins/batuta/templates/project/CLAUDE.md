# {{ project_name }}

Project core for Claude Code. Keep it short: it loads at every session start. Detail lives in `AGENTS.md`, the
constitution and the specs, which you read on demand.

## How work is done here
- Spec first: every change starts from a spec under `specs/<NNN-slug>/` with EARS requirements, each naming a gate that
  can run and fail. Do not write code before the spec is approved.
- Tests first: write the failing tests, lock them, then write the code. A locked test changes only through a change
  request, never by editing it.
- Gates decide, not prose: a phase ends when its gate passes and an independent check has reproduced the claims.
- The invariants are in `specs/000-foundation/constitution.md`; a plan names the article each decision touches.

## Commands
- Tests: `{{ test_command }}`
- Batuta checks: `spec lint`, `spec trace <spec id>`, `tdd check --replay`, `gate check <spec id>`, `gate thresholds`,
  `context check`, `leaks scan` (run through the Batuta plugin, or `npx github:fsantibanezleal/CAOS_Batuta <area> <verb>`).
- The CI job `batuta-gates` runs the same checks on every push and pull request; keep it required on `{{ default_branch }}`.

## Rules for agents
- Work on a task branch, never directly on `{{ default_branch }}`; commits are small and each is one logical unit.
- Never edit `specs/*/approvals/`, `.batuta/test-locks.json` or a locked test; the guards deny it and CI fails it.
- No machine paths, secrets or personal data in any file of this repository.
- Delegation records carry machine paths: they are git-ignored here and belong in a private coordination repository.
- Report what was verified and what was not; a claim without evidence is marked unverified.
