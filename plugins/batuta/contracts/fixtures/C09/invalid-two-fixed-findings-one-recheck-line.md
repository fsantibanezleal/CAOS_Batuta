<!-- why: every fixed finding needs its own Re-check line -->
<!-- expect: one 'Re-check:' line per fixed finding -->
---
gate: L7-build
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
| F-1 | major | off by one | run x | fixed |
| F-2 | major | wrong unit | run y | fixed |
Re-check: F-1 verified.

## Waivers requested

None.
