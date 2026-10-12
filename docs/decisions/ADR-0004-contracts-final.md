---
id: ADR-0004
title: The contracts, final form: one ledger, one availability vocabulary, hooks.json as the registry, configuration validated after expansion
status: Accepted
date: 2026-10-12
review_trigger: before the contracts are frozen, and whenever a delegation tool, the hooks platform or the contract-first method changes the artifact a contract describes
supersedes: ADR-0003 (in part)
superseded_by: none
---

# ADR-0004: The contracts, final form

Status: Accepted, 2026-10-12. Supersedes the parts of ADR-0003 listed under "What changes in ADR-0003". It does not
change ADR-0001 or ADR-0002.

## Context

The second review of the contracts (a re-review of revision 2) ended FAIL with 0 critical, 7 major and 13 minor open
findings (R01 to R20). Four of the majors needed a decision that belongs to the design, not to the builder: the ledger
format, where a boundary declares its availability states, how a hook handler is registered and found, and where the
configuration is validated. They are decisions 6 to 9 of the plan; decision 10 partly freezes the contracts that were
not touched. This ADR records them with the fixes that follow from them.

## Decision

6. **The ledger is one representation: the Markdown table the CAOS delegation tool writes.** C04 is that table: the
   columns ID, Agent, Model, Brief, Report, Status and Accepted, plus the optional Provider, Tokens in, Tokens out, Cost USD
   and Superseded by. The JSONL form is removed. The status enum covers every C30 result status (complete, incomplete,
   defective, error, timeout, over-budget, pending) under the same name, so a dispatch result is written to the ledger as
   it is; `contract lint` checks that every C30 result status is a C04 status. A billed row (a Provider other than `-`:
   `anthropic` for the sdk lane, the provider name for a provider lane) records Tokens in, Tokens out and Cost USD. C01
   gains the optional `dispatch.sdk.key_file` for the sdk lane's key file path.
7. **A boundary declares its availability states in the catalog.** The `missing-data behavior` cell of C22 holds one
   declaration per state, `<state>: <behavior> (test: <path>[::name])`, in the single vocabulary of ADR-0080 section 3
   (available, partial, stale, provider(kind), training, missing), each declared once, with `available` and one other, a
   provider state naming its provenance kind and every state naming its test. C26 keeps only the state vocabulary and the
   runtime block an artifact or response carries; its declaration root and fixtures are removed.
8. **`plugins/batuta/hooks/hooks.json` is the hook registry, and handlers are discovered like command areas.** C31 defines
   that file with the official entry fields (type, command, args, timeout, if, shell, onFailure, async, statusMessage,
   once), one grammar for the exec form and the shell form (the placeholder in double quotes), `onFailure: "block"` for
   the fail-closed guards on the events that can block through it, and matchers where the platform has them. An area
   module may define `HOOKS = {id: handler}`; the launcher resolves a unique id across the areas; a duplicate id, and a
   hooks.json id no area defines, are lint failures. The handler result is contracted, so a unit builds its hook from its
   own area module and one entry in hooks.json.
9. **Configuration paths are validated after `$VAR` expansion.** `config.load` expands first, then validates the expanded
   document as C01, so a variable that expands to a path with `..` or an absolute path is refused; an unset variable in
   a path field is an error that names the variable and the field; an unset root still falls back under `BATUTA_HOME`.
10. **Partial freeze.** C12, C13, C14 and the `budgets` block of C01 are not touched by this revision and are frozen now.

The minor findings are fixed with them: C23 gains the Executive brief the method's sizing checker requires, with a dated
copy of the checker's required sections recorded as a fixture and compared by a test, so an upstream change is a visible
fixture update; C02 refuses unfilled `<fill: ...>` slots; one relative-path pattern (no control character, no `.` or `..`
segment, no empty segment) is shared by C01, C07, C28 and C30 and checked equal by `contract lint`; a number that
overflows to infinity is refused; the sections file values are checked; dates are calendar dates (`format: date`); fixture
keys (`_why`, `_expect`, `_recorded`) are ignored only in fixtures; the Re-check line of a fixed finding names its id and
is not counted inside a code block; a path has one live lock; the reserved trailer key has one spelling.

## What changes in ADR-0003

| ADR-0003 item | After this ADR |
|---|---|
| 5 the ledger C04 gains `pending` and the dispatch fields; the Markdown table maps onto it | C04 is the Markdown table (decision 6); no JSONL |
| 6 C31 is the hook registry and the rendered hooks.json (launcher argv, stdout decision, exit codes, fail-open or closed per handler) | C31 is hooks.json with the official fields, handler discovery through `HOOKS` and the handler result (decision 8); the separate registry document is removed |
| 7 `config.py` validates as C01 and expands `$VAR` | it expands first and validates the expanded document (decision 9) |
| Kept: gate names, the availability states, sizing and catalog, C30, C32, the validator hardening | unchanged except as listed |
| Open points 2 and 3 of the owner (ledger format, C26 declaration root) | decided: decisions 6 and 7 |

## Alternatives considered

| Option | Verdict |
|---|---|
| Keep the JSONL ledger and map the table onto it | rejected: two representations; the delegation tool is the reference |
| Keep the C26 declaration next to the catalog column | rejected: the same declaration twice drifts |
| A separate handler registry file next to hooks.json | rejected: the platform file is the registry; a second file is a second source of truth |
| Make the launcher import every area to find handlers | rejected for the lint: reading the modules is enough and cannot execute code |
| Validate the configuration as written and again after expansion | rejected: validating the expanded document is the check that matters; the structure errors show there too |

## Consequences

- The CAOS delegation tool reads exactly seven ledger columns (its `read_ledger` skips a row that has another number of
  cells), so a ledger that uses the optional columns is valid C04 but its `status` verb needs an extension (a CAOS change
  outside this repository) before it reads such a ledger. The plain seven-column ledger works with both.
- The CAOS contract catalog template's example row uses free text in the missing-data behavior cell; it needs the
  declaration grammar (a CAOS change) for the template row to validate as C22.
- Contract versions stay 1.0: nothing was frozen except what decision 10 lists.
- Costs: new rule types in the sections dialect (`labeled_parts`, `cell_items`, an id column for `lines_per_row`), a
  stricter catalog cell, and a hooks lint that parses the area modules.

## Open points for the owner

1. The grammar of a typed approval phrase and the format of `test-change-requests.md` (finding R19) are not contracted: they
   are design questions for the units that build approval capture and the test-first protocol, with a proposed phrase
   in the report of this revision.
2. The plan's port-map row for the locked-test guard and the plan's unit row for U0 (findings R18 and R20) live in the
   coordination repository, outside this repository.
