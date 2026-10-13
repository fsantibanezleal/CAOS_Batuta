---
id: ADR-0003
title: The contracts after the adversarial review: the method's own artifacts, one vocabulary, the missing boundaries
status: Superseded in part by ADR-0004
date: 2026-10-12
review_trigger: before the contracts are frozen, and whenever the contract-first method changes its artifacts or states
supersedes: ADR-0002 (in part)
superseded_by: ADR-0004 (in part)
---

# ADR-0003: Contracts after the adversarial review

Status: Superseded in part by ADR-0004 (2026-10-12): the ledger format (decision 5 and open point 2), the hook registry
(decision 6, C31) and the configuration validation (decision 7) are decided there, and the C26 declaration root (open point
3) is retired there. Accepted 2026-10-12. Supersedes the parts of ADR-0002 listed under "What changes in ADR-0002". It does
not change ADR-0001.

## Context

The contract set of ADR-0002 (C01 to C29) was reviewed adversarially before its freeze. The verdict was FAIL: 2 critical,
17 major and 12 minor findings (F01 to F31), each with a reproduction. The main problems:

1. C23 was a machine-readable inventory and C22 a spec-local interface table, two artifacts the method no longer uses
   (it keeps `sizing.md` and the contract catalog; a second representation is the drift the method exists to remove).
2. The availability state of a provider answer was named twice (`synthetic` in the contracts, `provider` in the method,
   the product template's readiness schema and its checker), with an alias that was accepted without a warning.
3. C02 and C03 refused the briefs and reports the delegation tools write today.
4. Gate names, waves and "frozen" had several meanings; the locked-test path and the approval had integrity gaps.
5. Several boundaries had no contract: the dispatch request and result, the hook launcher and its registration, the
   commit grammar of the test-first protocol, and the shared configuration and output helpers.

## Decision

1. **Gate names are the lifecycle names** `L0-understand`, `L1-size`, `L2-decide`, `L3-contracts`, `L4-boundaries`,
   `L5-freeze`, `L6-skeleton`, `L7-build`, `L8-integrate`, `L9-promote`, `L10-lessons`, used by C01 (`gates.critical`),
   C09 and C10, and checked equal by `contract lint`. The earlier P-names map to them (P0 to L0, P1 and P2 to L5, P1b to
   L3, P3 and P4 to L7, P5 and P6 to L9, P7 to L10) and are refused. The default critical gates are `L2-decide`,
   `L5-freeze` and `L9-promote`, plus `L7-build` for the units listed in `gates.critical_units`. C09 `feature` is a spec
   id (`NNN-slug`) or a product slug, so product-level evidence validates. PASS-WITH-FIXES, like PASS, admits no open
   critical or major finding and needs one `Re-check:` line per fixed finding.
2. **Availability states are the method's, exactly:** `available`, `partial`, `stale`, `provider`, `training`,
   `missing`. A `provider` answer carries `provenance`, its kind (stub, simulator, fixture, baseline). There is no
   alias and `synthetic` is not a state.
3. **The sizing artifact is `sizing.md` and the interface artifact is the contract catalog.** C23 is the Markdown
   contract of `sizing.md` (11 sections, four tables, pairwise disjoint write scopes), C22 the contract of
   `docs/contracts/catalog.md` (the 12 columns of the template, semver versions, `kind:path` providers, a baseline
   provider for every model slot). C21 tasks name catalog contract ids and the sizing's units, and `contract graph`
   computes one wave numbering from the catalog, the sizing and the tasks: wave 0 the contracts, wave 1 the walking
   skeleton, units and tasks from wave 2. C25 is the Technology matrix row (tool, exact version, primary source URL,
   verified date) with an optional evaluation in which a risky chosen candidate needs a spike that passed. The sizing is
   coordination and lives under the coordination root of C01.
4. **Frozen means the catalog row says frozen** (the optional column `frozen: yes`). C06 proves the freeze by hashing the
   spec, every contract and accepted ADR it references (`adrs_sha256`) and every named test; the `frozen` boolean of the
   old inventory is gone.
5. **C02 and C03 describe the formats the tools write and accept.** A brief is a title, metadata bullets and sections
   (the contract-first sections for implement, job and skeleton briefs); `depends` accepts catalog contract ids. A
   report is a Completeness table, one `## D<n>` section per deliverable, no placeholder text in the prose; the BRIEF
   and REPORT lines belong to the agent's final message. The ledger C04 gains the status `pending` and the dispatch
   fields; the delegation tool's Markdown ledger table maps onto it.
6. **New contracts.** C30 is the dispatch request and result (lanes, provider names mapped to environment variable
   NAMES, never values; C04 gains `provider`, `tokens_in`, `tokens_out`, `cost_usd`; C01 gains
   `caps.max_cost_usd_per_task` and a `dispatch` block). C31 is the hook registry and the rendered `hooks.json`
   (launcher argv, stdin payload per C16, stdout decision, exit codes, fail-open or fail-closed declared per handler).
   C32 is the commit grammar `[red] T-NNN <title>`, `[green] T-NNN <title>`, `[refactor] T-NNN <title>` and the
   trailer `Test-Change-Approved: <change request id>`.
7. **Shared helpers.** `batuta_lib/config.py` resolves `batuta.json` (`--config`, `BATUTA_CONFIG`, project
   `.batuta/batuta.json`, user `<BATUTA_HOME>/batuta.json`, defaults), expands `$VAR` and validates as C01;
   `batuta_lib/output.py` prints tag lines and the C20 object and fixes the exit codes. Every area uses them.
8. **Validator hardening and the minor findings.** Patterns match the whole text with ASCII digits; NaN, Infinity and
   duplicate keys are refused; a UTF-8 byte order mark is accepted; an unknown key in a sections file, an unknown rule
   type and a `$ref` cycle are refused at load; relative paths cannot contain `..`; each invalid fixture breaks exactly
   one rule and states which; `contract lint` enforces two valid and three invalid fixtures per contract; C04, C07, C08
   and C05 gain their conditional rules.

## What changes in ADR-0002

| ADR-0002 item | After this ADR |
|---|---|
| 1 Vocabulary: `synthetic` | `provider` with provenance (decision 2); rings and model status unchanged |
| 2 C23 inventory | replaced by the sizing contract (decision 3); the inventory, `contract graph --inventory` and the C23 and C26 equality lint are removed |
| 3 C25 evaluations | the Technology matrix row with an optional evaluation (decision 3) |
| 5 C27 readiness (components, as-of commit, the `provider` alias) | the product template's readiness document, closed, with its conditional rules |
| 7 C21 and `contract graph --inventory` | tasks name catalog ids; `contract graph --catalog --sizing --tasks` (decisions 3 and 4) |
| 9 Location: `plugins/harness/contracts/`, `docs/design/inventory.json` | `plugins/batuta/contracts/` after the rename to Batuta; `contract lint --root` lints the project's `sizing.md`, catalog and readiness document |
| Kept: 4 (C26 root and runtime block, with `provider`), 6 (C28), 8 (front matter subset, extended with `bullets` headers), 10 (fixtures) | unchanged |

## Alternatives considered

| Option | Verdict |
|---|---|
| Keep C23 as the inventory and generate `sizing.md` from it | rejected: the method withdrew the inventory; two representations drift |
| Keep the `synthetic` word and amend the method and the template | rejected by decision: the method's word is `provider` |
| Keep `P` gate names and add the `L` names as aliases | rejected: two vocabularies for one lifecycle |
| Read a brief's header as YAML front matter and change the tools | rejected: the tools are the reference and write bullets |
| Mark a frozen contract in a separate file | rejected: one place says it, the catalog row |

## Consequences

- The contracts describe what the running tools produce and what the method uses; the units that build the spec, size,
  gate, hook and dispatch areas can start from them without reading each other's code.
- The catalog gains an optional column `frozen`. The CAOS checkers read the catalog by column name and ignore it, so a
  catalog stays valid for them; the method's template should list the column.
- A configuration, a catalog or a readiness document that validated under ADR-0002 may not validate now (retired gate
  names, `synthetic`, `1.0` versions, ranges as versions). All contract versions stay 1.0: none was frozen.
- Costs: more contracts (32), a larger validator (new rule types), and a stricter reading than the delegation tools for
  some cells (an exact version, a semver version, a path without `..`).

## Open points for the owner

1. The `frozen` column is this ADR's way to let "the catalog row says frozen" be true; the alternative is a third value
   of `status`, which the existing skeleton checker would refuse.
2. The ledger C04 stays one JSON object per line, as designed; the delegation tool writes a Markdown table. The mapping is
   documented; one of the two formats should win when the route unit is built.
3. C26 keeps its declaration root next to the runtime block although the catalog's missing-data column covers the same
   ground; retiring the root is a separate decision.
4. The field-level design note kept with the plan still describes the first contract set; the catalog in
   `plugins/batuta/contracts/README.md` is now the description of record.
