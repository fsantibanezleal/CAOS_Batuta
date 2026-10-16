---
id: 001-example-feature
title: Example feature
status: Draft
tier: M
owner: Project owner
created: 2026-01-01
---

## Problem

State the problem in the context it lives in: who is affected, what it costs, what done looks like. Name the ADRs that
constrain the work (by id, ADR-NNNN) so the freeze hashes them.

## Scope and out of scope

In: what this spec delivers. Out: what it deliberately leaves to other specs.

## Requirements

One row per requirement, written in EARS form (ubiquitous: "The system shall ..."; event: "When ..., the system shall ...";
state: "While ..., ..."; unwanted: "If ..., then the system shall ..."; optional: "Where ..., ..."). The Id is never reused,
in this spec or in any other. The Gate is a backticked command or a test id (`path::name`) that can run and fail.

| Id | Kind | EARS text | Gate | Verification | Status |
|---|---|---|---|---|---|
| REQ-FOUND-001 | ubiquitous | The project shall keep its constitution at `specs/000-foundation/constitution.md`. | `python -m unittest tests/test_foundation.py` | unit test | active |

<!--
Example row (a comment: it is never counted as a requirement):
| REQ-EXAMPLE-001 | event | When a file arrives, the service shall list it within one second. | `pytest tests/test_listing.py` | unit test | active |
-->

## Interfaces

List every interface this spec touches as `- <catalog contract id>: who produces it, who consumes it`, using the ids of
`docs/contracts/catalog.md`, or write `none`. A spec in Review or Frozen states them.

<!--
Example item (a comment): - alert-event: produced by the pipeline, consumed by the API.
-->

## Edge cases

Empty, late, missing, oversized and malformed inputs; concurrent use; the behavior of each.

## Open questions

None yet. Mark an open question with the clarification tag (the words NEEDS CLARIFICATION in square brackets); a spec in Review or Frozen has none.
