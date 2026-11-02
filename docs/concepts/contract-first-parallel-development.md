# Contract-first parallel development

Parallel, autonomous development works only when units do not block each other. Batuta gets there by fixing the
interfaces first: every artifact that crosses a unit boundary has a versioned data contract before any unit is built, a
unit depends on contracts only and never on another unit's code, and the order of work is computed from the contracts.
The method is the contract-first parallel delivery (CPD) used in the author's other repositories; this page describes the
artifacts Batuta checks for it.

![Contract-first delivery: size and decompose, the contract catalog, boundaries with fixture providers, the walking skeleton, then parallel waves from wave 2, then real providers replace the fixtures.](../assets/contract-first-waves.svg)

## Sizing (contract C23)

`sizing.md`, in the coordination root, dimensions the system before a spec exists. It has twelve sections: Problem,
Executive brief, ADR constraints, Repositories, Components, Modules and functions, Boundaries, Technology matrix, Machine
limits, Parallel units, Integrator and merge order, Reservations; and four tables:

| Table | Columns |
|---|---|
| Modules and functions | Module, Responsibility, Owner unit, Size estimate |
| Boundaries | ID, Producer, Consumer, Contract ID |
| Technology matrix | Tool, Version, Primary source URL, Verified date |
| Parallel units | Unit, Write scope, Depends on contract ids |

Write scopes of the parallel units are disjoint (compared case-folded, a bare name read as a prefix). `size lint` checks
the document against C23 and cross-checks it with the catalog; a component without a unit is a WARN (exit 2) listing it,
never a FAIL, because a lint must not reject a document its contract accepts (plan decision 29). `tech lint` fails a
version range, a missing source or a date that does not exist, and warns about a date older than `--max-age-days` (90).

## The contract catalog (contract C22)

`docs/contracts/catalog.md` has one row per interface with these columns: id, version, owner, schema file, example,
producer test, consumer test, missing-data behavior, provider and swap test; the optional columns are model io, status
and `frozen`. A contract is frozen when its row says so, and the freeze approval of a spec hashes it (see
[spec-driven development](spec-driven-development.md)): editing a frozen contract voids the approval, and a breaking change
bumps the contract's major version. Producers validate what they write and consumers what they read, against the schema;
the two tests of a row prove it from both sides, and the swap test proves a real provider can replace a fixture without
changing a consumer.

Batuta applies the same rule to itself: its own contracts C01 to C34 are in `plugins/batuta/contracts/` with at least two
valid and three invalid fixtures each (see the [contracts catalog](../reference/contracts.md)). After the freeze they evolve
only additively, by a minor version with its own adversarial check (plan decision 23), as ADR-0006 did for C01, C16 and C34.

## Availability states and fallbacks

Every dependency that can be absent declares what happens when it is, in the catalog's missing-data behavior column. The
vocabulary is exactly the one of the CAOS dimensioned contract-first method (ADR-0080): `available`, `partial`, `stale`,
`provider`, `training` and `missing`, with a provider labelled by its provenance kind. Contract C26 is the runtime block an
artifact or response carries when a source is not fully available: `state`, `reason`, `source`, `age` (an ISO 8601
duration) and `provenance`.

A fallback is not a mockup. It is a fixture-backed implementation of the real contract, labelled `degraded` at runtime and
in the interface, with the expected behaviour when the real provider is missing, late or failing, and it is replaced, not
kept. A model that is still training answers from a baseline model that satisfies the same input and output contract (a
model card, C28). `provider lint` fails a catalog row that has no state declared for one of its missing-data behavior items,
a test that does not exist or is not its own, or a provider column without its `provider(kind)` state; `provider check`
validates a response's availability block and, with `--id`, that its state is one the row declares.

## The walking skeleton

Before the units are built, a thin end-to-end slice is deployed to a preview on the fixture providers: the frontend and
the APIs run, contract tests run in CI, and a readiness document (C27, `docs/design/readiness.json`) labels every
component real or served by a provider with its provenance. The preview deployment record is C29 (`docs/design/previews.json`)
and the contract-tests record is C34 (`docs/design/contract-tests.json`), written by `gate tests-record` after it runs the
catalog's tests (a pass is recorded only by running them, never typed in).

`skeleton check` reads those records. Before L6 there is no readiness document and the check says SKIP. A readiness document
that is more than `--lag` commits (outside `specs/`) behind the head is stale; a failed or skipped contract test fails; a
record for a commit with later code or contract changes fails; and no record is a WARN. The network is touched only with
`--check-network`. With `--release`, every component that is not real (a provider serves it, or it is missing, partial or
stale, or a model answers from its baseline) is listed as a gap and fails, which is the rule the `L9-promote` gate applies.

## Waves

`contract graph` computes the order of work in one numbering from the catalog, the sizing and the tasks table (contract C21):

- wave 0 is the contracts (the frozen ones are listed);
- wave 1 is the walking skeleton;
- from wave 2 the sizing's parallel units and the tasks: a unit that depends only on frozen contracts starts at wave 2, and a
  unit that depends on a contract another unit still owns starts after that unit.

It fails when a task depends on a task in a later wave, and warns when a task depends on a task of another unit in the same
wave (coupling). A task depends on contracts and on other tasks, never on another unit's code (requirement CONTRACT-4). The
Wave column of the tasks table is left empty by the author; the command computes it and warns when a written value
disagrees. Units in one wave share no contract change and have disjoint write scopes, so they can run as separate agents in
separate worktrees at once, each one red then green ([test-driven development](test-driven-development.md)).

## Real providers replace fixtures

At L8 real providers replace fixtures one at a time behind flags; the readiness matrix moves to real per interface; degraded
paths stay tested. A real provider passes the same contract tests as the fixture it replaces (`provider check`), which is
why the swap test exists. Data and model providers are the ones whose gate the plan names the strongest model for (see the
note on L8 in the [lifecycle](lifecycle.md)).

## Sources

- Design: software design document sections 3.3 and 4 (CONTRACT-1 to CONTRACT-5) and decisions 1 to 5, 7, 10, 20, 23 and 29;
  `plugins/batuta/contracts/README.md` and the contracts C21 to C29 and C34; ADR-0002 to ADR-0006.
- The `contract`, `size`, `tech`, `provider` and `skeleton` areas (see the [command reference](../reference/cli.md));
  `batuta_lib/areas/contract.py` (`compute_waves`, `compute_unit_waves`).
- CAOS ADR-0080, the dimensioned contract-first method (a design record of the author's other repositories, not part of this
  one); the vocabulary and the C22 and C23 layouts are restated in this repository's contracts.
