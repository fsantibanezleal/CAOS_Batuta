<!-- why: gate names are the lifecycle names; the retired P-names are refused -->
<!-- expect: /gate -->
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
| F-1 | minor | x | y | fixed |
Re-check: F-1.

## Waivers requested

None.
