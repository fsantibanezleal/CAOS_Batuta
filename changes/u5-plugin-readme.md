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
- Stop hook: `gate-stop` (a handler in the `gate` area, wired by `hooks.json`) blocks once while a unit with uncommitted
  changes has a failing gate check, then writes `- <date> UNVERIFIED: ...` to the unit's status file and lets the session
  end. A unit's `scope: [paths]` front matter ties changes outside `specs/<feature>/` to it.
- `skeleton check` reads the catalog hash and the age of the readiness document (more than `--lag` commits outside `specs/`
  behind the head is stale); before L6-skeleton the document is absent and the check says `SKIP`. The network is touched only
  with `--check-network`.
- `provider lint` needs, per catalog row, one state per `missing-data behavior` item with a test that exists and is its own;
  a provider in the provider column needs its `provider(kind)` state.
