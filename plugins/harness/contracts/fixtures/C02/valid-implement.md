---
id: u0-data-contracts-2026-10-11
agent: implementer
kind: implement
model: sonnet
effort: medium
cwd: work/harness-u0
write_scope: [contracts/**, tests/**]
budget_turns: 80
report: reports/u0.md
serves: design unit U0
depends: [C01, C22]
boundary: [plugins/**]
---

## Goal

Turn the field-level definitions into schemas and a validator.

## Context and background

The contracts are defined first so units can be built in parallel.

## Definitions

Schema dialect: JSON Schema 2020-12 restricted to a documented subset.

## Spec

1. Parse the front matter.
2. Validate the sections.

## Out of scope

Any other area.

## Deliverables

- D1: the parser.
- D2: the validator.

## Checks

- C1: `python -m unittest` passes.

## Report layout

Summary, one section per deliverable, completeness table.

## Hard constraints

Stay inside the write scope. Never push.

## Return message

Under 250 words, then the BRIEF and REPORT lines.
