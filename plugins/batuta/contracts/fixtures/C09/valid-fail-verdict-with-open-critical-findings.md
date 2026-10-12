---
gate: L3-contracts
feature: 001-validator
verdict: FAIL
role: adversary
model: sonnet
commit: abc1234
date: 2026-10-11
---

## Definition of done restated

All tests pass.

## Commands and output

`python -m unittest` : OK (12 tests)

## Findings

| Id | Severity | Claim | Reproduction | Status |
|---|---|---|---|---|
| F-1 | critical | data loss | run x | open |
| F-2 | major | wrong unit | run y | open |

## Waivers requested

None.
