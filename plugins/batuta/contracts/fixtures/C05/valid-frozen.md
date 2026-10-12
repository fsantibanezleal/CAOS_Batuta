---
id: 001-validator
title: Validator
status: Frozen
tier: M
owner: alex
created: 2026-10-11
---

## Problem

Users cannot validate contracts.

## Scope and out of scope

In: validator. Out: deployment.

## Requirements

| Id | Kind | EARS text | Gate | Verification | Status |
|---|---|---|---|---|---|
| REQ-VAL-001 | ubiquitous | The validator shall reject unknown keywords. | pytest tests/test_validator.py | unit test | active |
| REQ-VAL-002 | unwanted | If a schema is invalid, then the validator shall exit 1. | tests/test_validator.py::test_exit | unit test | retired |

## Interfaces

- alert-event: produced by the pipeline, consumed by the API (catalog row alert-event).
- alert-list

## Edge cases

Empty schema.

## Open questions

None.
