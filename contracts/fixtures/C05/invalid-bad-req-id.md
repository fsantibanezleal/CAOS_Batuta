<!-- why: requirement ids are REQ-X-NNN -->
<!-- expect: /Id -->
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
| REQ-1 | ubiquitous | The validator shall reject unknown keywords. | pytest tests/test_validator.py | unit test | active |

## Interfaces

| Interface | Contract file | Producer | Consumers | Version |
|---|---|---|---|---|
| config | contracts/C01-harness-config.schema.json | init | every area | 1.0 |

## Edge cases

Empty schema.

## Open questions

None.
