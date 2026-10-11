<!-- why: PASS-WITH-FIXES needs a Re-check line -->
<!-- expect: Re-check -->
---
gate: P4-green
feature: 001-validator
verdict: PASS-WITH-FIXES
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
| F-2 | major | off by one | run x | fixed |

## Waivers requested

None.
