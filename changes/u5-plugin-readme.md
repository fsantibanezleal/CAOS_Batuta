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
  configuration named by `--config` or the environment is used as given.
- Evidence must not predate the change it certifies: for each gate the newest commit that changed a path the gate judges (L0 and L5 the
  spec, tasks and trace of the feature; L1 also the sizing; L2 the ADRs and technology decisions; L3 the contracts and catalog; L4 also
  the models; L5 also the decisions; L6 and L8 the code and the readiness documents; L7 the code and tests) must be the evidence's
  commit or an ancestor of it; otherwise `gate check` fails with `evidence ... predates the change`. L9 evidence must describe the head
  until L10 passes.
- `gate tests-record` writes the contract-tests record (C34, `docs/design/contract-tests.json`), validated before it is written:
  `--result <test path>=pass|fail|skip` (repeatable) and `--run` (runs the python test files the catalog names, one unittest
  discovery each; no test run is a skip). It records HEAD and refuses a working tree with uncommitted changes outside `specs/`.
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
