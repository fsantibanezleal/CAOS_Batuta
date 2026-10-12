---
id: ADR-0002
title: Align the data contracts with the dimensioned contract-first method and ship them inside the plugin
status: Accepted
date: 2026-10-11
review_trigger: before release 0.01.000, and whenever the method's availability states or evaluation rings change
supersedes: none
superseded_by: none
---

# ADR-0002: Contracts aligned with ADR-0080 and shipped inside the plugin

Status: Accepted, 2026-10-11. Revises the contracts C21, C23, C25, C26, C27 and C28 of the first contract set (U0)
before they are frozen, so the harness speaks the same method and vocabulary as the dimensioned, contract-first
design (CAOS ADR-0080) and the tooling already in use for it. No amendment to ADR-0001 is needed.

## Context

The first contract set described a system map, a technology evaluation, a provider registry, a readiness matrix and
a model card in its own words. The method it serves was fixed in the same period: an inventory with sizes, an exact
stack and rings; contracts as JSON Schema 2020-12 and OpenAPI 3.1; six availability states with a declared behaviour
for each; a walking skeleton with a readiness document; parallel units in waves; a model registry addressed by
alias. Two vocabularies for one method would drift. In addition the contracts lived at the repository root, so a
harness installed as a plugin could not resolve them, and the front matter subset lacked the one-level maps that
two contracts need.

## Decision

1. **Vocabulary.** Availability states are exactly `available`, `partial`, `stale`, `synthetic`, `training`,
   `missing` (case-sensitive). Rings are `adopt`, `trial`, `assess`, `caution`. Model status is `planned`,
   `training`, `candidate`, `released`, `retired`. Models are addressed by alias and serving reports which version
   or baseline answered.
2. **C23 inventory** replaces the system map: repositories, components (kind, responsibility, provides, consumes,
   modules, size class, exact stack with ring, unit, gates, availability), evaluations, contracts and units. JSON
   always; YAML only when PyYAML is importable, refused with a message naming the JSON alternative otherwise.
3. **C25 evaluations** gain the criteria maintenance and size and the decision's ring; `spike` and `risky` stay.
4. **C26 availability** holds two schemas in one file: the per-component declaration (state, adapter returns,
   response block, UI, test; a component that can be absent declares `available` and one other state, each with a
   test) and the runtime block `{state, reason, source, age}` (reason required unless available; age an ISO 8601
   duration, null only for available and missing).
5. **C27 readiness** lists every component or contract as real or stub with its availability state and as-of commit,
   and accepts the product template's readiness document unchanged.
6. **C28 model registry** entries carry alias, registry status, baseline and a serving block; an unreleased model
   must name the released version or the baseline that answers.
7. **C21 tasks** gain a `Unit` column; `contract graph --inventory` computes waves as ADR-0080 section 5: wave 0 the
   contracts, wave 1 the walking skeleton, then units whose consumed contracts are frozen (an unfrozen contract is
   ready when its provider units are done), and refuses a unit that consumes a contract nobody provides.
8. **Front matter subset** gains one-level maps (`key:` then `  sub: value`, and `key: {a: 1}`) and inline maps in
   list items; nothing nests deeper, and a deeper structure is refused with an error. Schema root metadata
   (`$schema`, `$id`, `title`, `contract_id`, `contract_version`) is allowed and validated as metadata.
9. **Location.** The harness's own contracts live in `plugins/harness/contracts/` and every loader resolves them
   relative to the plugin. A project's own contracts stay in its `contracts/` folder: `contract lint --root DIR`
   lints that folder and the project's `docs/design/inventory.json`; with no `--root` the harness lints its own.
10. **Fixtures.** The C16 hook payload fixtures stay synthetic and carry `"_recorded": false` until real payloads
    are recorded. C25 keeps the optional `risky` flag.

## Alternatives considered

| Option | Verdict |
|---|---|
| Keep the first vocabulary and map it to the method's in documents | rejected: two vocabularies for one method drift |
| Keep `contracts/` at the repository root and copy it into the plugin at release | rejected: two copies, and a plugin run from a checkout could read the wrong one |
| Support full YAML front matter | rejected: a parser dependency for two contracts; one-level maps cover them |
| Express the availability rules as one schema per state | rejected: the subset has no conditionals; semantic checks state them once |

## Consequences

- Contracts, fixtures and the CLI use one vocabulary with the method, so an inventory, a readiness document and a
  model registry entry from a product validate with the same words.
- The plugin is self-contained: `contract lint` works from a copy of the plugin folder alone.
- Waves can be computed from the inventory before any task exists, and an unprovided contract is found at design time.
- The contract versions stay 1.0: none of the revised contracts was frozen.
- Costs: C21 tables gain a column; the front matter parser refuses structures it used to read loosely (a list of
  lists); C27 carries the `provider` alias until the product template and the method text use `synthetic`.

## Readings kept from U0, and readings taken here

Kept from U0 (conservative): `contract_version` absent from C16, C14 and the Markdown contracts; C03 does not require
`Sources`; C02 and C18 `model` is a free string; inner fields of bold groups read as required; C16 required subset per
event; C11 history waiver across files is not checked; a contract is frozen for `contract graph` when declared in C22
and present; the Wave column is not rewritten; C19 lessons cannot contain a pipe; empty cells in C21 and C22 mean an
empty list.

Taken here where the brief was silent: repository `visibility` is a free string; `can_be_absent` is an explicit
flag; C23 `evaluations` are summaries of C25 files (a schema cannot reference another file); a declared unit `wave`
that differs from the computed one is a warning; a C21 `Unit` of `-` or empty means none; a C27 document needs at
least one entry; `age` is required (non-null) for partial, stale, synthetic and training.

Open: the method text and the product template call the provider-served state `provider`, while the vocabulary given
for this unit calls it `synthetic`. C27 accepts both so the template's readiness document validates; the question
is whether the template and ADR-0080 move to `synthetic`, after which the alias is dropped.
