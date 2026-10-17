# The governed delivery lifecycle

Spec-driven development starts before any spec. A system is understood, sized and decomposed, and its technology is
validated; then every interface gets a data contract; then every external dependency gets an adapter with a
contract-faithful fallback; then a walking skeleton is deployed; only then do parallel waves build the parts. That order
is what makes autonomous, parallel, agentic development possible without cross-blocking, and Batuta enforces it as eleven
gates, `L0-understand` to `L10-lessons`.

![The eleven phases L0 to L10 in two rows. Each shows what it produces, its deterministic gate and the model of its independent check. L2 decide, L5 freeze and L9 promote are highlighted as critical and checked on the strongest model.](../assets/lifecycle.svg)

## The phases

| Phase | What is produced | Contract | Deterministic gate | Independent check |
|---|---|---|---|---|
| L0 understand | problem statement, users, constraints, success measures, persisted research | C05 Problem section, C03 | `report check` | a sample of the claims is re-fetched (adversary, sonnet) |
| L1 size | system map: repositories, components, modules and functions, data stores, models, UIs, with size estimates and risks | C23 | `size lint` | missing components, under-estimates (sonnet) |
| L2 decide | ADRs (status, review trigger, supersession) and technology evaluations: candidates, pinned versions, licenses, maturity, a spike with evidence per risky choice | C24, C25 | `adr lint`, `tech lint` | version, license, maturity, alternatives (reviewer, opus, for the stack decision) |
| L3 contracts | a data contract per interface: APIs, files, datasets, model I/O, events, UI view models | C22 and per-project schemas | `contract lint`, `contract graph` (waves) | missing fields, ambiguity, coupling (sonnet) |
| L4 boundaries | an adapter per external dependency with a fixture provider that honours the contract and declares `degraded`; model cards with a baseline model | C26, C28 | `provider lint` | silent fallbacks, behaviour gaps (sonnet) |
| L5 freeze | requirements (EARS) with gates, interfaces, tasks with waves, a human approval hashed with the ADRs and contracts | C05, C06, C21 | `spec lint`, `gate check` | reviewer (opus, critical) |
| L6 skeleton | a thin end-to-end slice deployed to a preview on fixture providers; contract tests in CI | C27, C29 | `skeleton check` | integration and UX review (sonnet) |
| L7 build | per wave and per unit: red (test-author), green (implementer) | C07, C02, C03 | `tdd check`, unit gates | per unit (sonnet; opus for units listed in `gates.critical_units`) |
| L8 integrate | real providers replace fixtures one at a time behind flags | C26, C27 | `provider check` | the plan names the reviewer on opus for data and model providers (see the note below) |
| L9 promote | thresholds, replay, trace, evidence; the required CI job `batuta-gates`; release | C08, C09, C11 | `gate check`, CI `batuta-gates` | reviewer (opus) for the release |
| L10 lessons | a dated lesson per unit; ADRs revisited when their review trigger fires | C19, C24 | `lessons check`, `adr lint` | none |

Source: the software design document, section 3.3, and [ADR-0001](../decisions/ADR-0001-architecture.md). The gate names
are the lifecycle names only; they are used by the configuration (C01), the evidence files (C09) and the status file
(C10).

Note on L8. The design table names the reviewer on opus for data and model providers, but the default critical set of
the configuration is `L2-decide`, `L5-freeze`, `L9-promote` (the built-in defaults in `batuta_lib/config.py`). A project
that wants the strongest model at L8 lists `L8-integrate` in `gates.critical`; the default does not.

## Critical gates

A gate listed in `gates.critical` (and the `L7-build` gate of a unit listed in `gates.critical_units`) needs evidence from
`role: reviewer` on the model of `gates.adversary_model_critical` (opus by default). Every other gate needs
`role: adversary` on `gates.adversary_model_routine` (sonnet by default). A script, or the builder, is never the
independent check. The reasoning is economic as well as safety: the evaluator "was only worth its cost for tasks beyond
what the model could reliably do alone" (https://www.anthropic.com/engineering/harness-design-long-running-apps), so the
strong model is spent where a wrong decision is most expensive to undo: the stack, the freeze and the release.

## Evidence, status and the gate check

Each gate ends with one evidence file, `specs/<feature>/evidence/<gate>.md` (contract C09): front matter with `gate`,
`feature`, `verdict` (PASS, FAIL or PASS-WITH-FIXES), `role`, `model`, the full `commit` reviewed and the `date`; then the
sections Definition of done restated, Commands and output, Findings and Waivers requested. A PASS has no open critical or
major finding; PASS-WITH-FIXES carries one `Re-check: <finding id>` line per fixed finding; every finding names a real
reproduction.

`specs/<feature>/status.md` (C10) records each gate as `pending` or `passed` (or `waived`). `gate check <feature>` fails on:

- a gate passed out of order, or passed without valid evidence;
- evidence whose commit is not in the history, or that goes backwards along the gates;
- evidence that predates a change to a path its gate judges (for example L7 judges the code and tests);
- release evidence for a commit older than the head;
- a void approval (a hashed file changed, the typed phrase missing, an agent as approver);
- a waiver without a dated human line, or written by an agent role;
- at L9 or with `--release`, any component of the readiness document that is not real.

`gate status --set <gate>=passed` runs the same evidence checks first, never sets `waived` (a waiver is a line a human
writes: `gate`, `reason`, `by`, `date`), and is a dry run without `--apply`. Settings that could weaken a gate (the
thresholds and the `gates` block of `batuta.json`) are read from the base revision of the checked range, never from the
change under review. Every verb and option is in the [command reference](../reference/cli.md).

Thresholds (`specs/000-foundation/thresholds.json`, C11) only ratchet upward: a lowering needs a history entry and a
human waiver of `L9-promote` dated the same day.

## Architecture decisions stay open

ADRs constrain development and stay open to improvement. Each has a status (Proposed, Accepted, Superseded,
Deprecated), a review trigger (a date or a condition) and a supersession link. `adr lint` flags overdue reviews and broken
links; a change goes through a new ADR that supersedes the old one, never an edit in place. This repository follows the
same rule: [ADR-0002](../decisions/ADR-0002-contracts-align-adr0080.md) to
[ADR-0006](../decisions/ADR-0006-additive-contracts-r5.md) supersede one another in part.

## Fixtures are not mockups

A fallback provider is a fixture-backed implementation of the real contract, labelled degraded at runtime and in the
interface, and it is replaced, not kept. The availability vocabulary is `available`, `partial`, `stale`, `provider`,
`training` and `missing` (the CAOS dimensioned-design method, ADR-0080), declared per boundary in the contract catalog. See
[contract-first parallel development](contract-first-parallel-development.md).

## What a person decides

Two steps need a human, and the agents are denied both: the typed approval that freezes a spec (L5) and the decision on
a request to change a locked test (L7). Both are described in [spec-driven development](spec-driven-development.md) and
[test-driven development](test-driven-development.md). The merge itself follows the repository's own rules: `gate promote`
prints the merge command and runs it only with `--apply`, and only on green checks for the exact head commit.

## Sources

- Design: software design document sections 3.3 and 3.4; ADR-0001; `plugins/batuta/templates/gates/evidence.md`.
- Command behaviour: the `gate`, `size`, `adr`, `tech`, `provider` and `skeleton` areas (see the
  [command reference](../reference/cli.md)); `plugins/batuta/hooks/hooks.json`.
- https://www.anthropic.com/engineering/harness-design-long-running-apps (March 24, 2026)
- CAOS ADR-0080, the dimensioned contract-first method that supplies the availability vocabulary (a design record of the
  author's other repositories, not part of this one; the vocabulary is restated in `plugins/batuta/contracts/README.md`).
