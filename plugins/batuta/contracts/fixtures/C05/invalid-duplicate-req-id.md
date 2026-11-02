<!-- why: requirement ids are never reused -->
<!-- expect: duplicate -->
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
| REQ-VAL-001 | ubiquitous | The validator shall reject unknown keywords. | pytest tests/test_validator.py | unit test | active |

## Interfaces

| Interface | Contract file | Producer | Consumers | Version |
|---|---|---|---|---|
| config | contracts/C01-batuta-config.schema.json | init | every area | 1.0 |

## Edge cases

Empty schema.

## Open questions

None.
