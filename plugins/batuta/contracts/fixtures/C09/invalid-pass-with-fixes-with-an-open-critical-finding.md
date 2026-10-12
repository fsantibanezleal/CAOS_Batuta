<!-- why: PASS-WITH-FIXES cannot carry an open critical finding -->
<!-- expect: PASS-WITH-FIXES require no open critical or major finding -->
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
| F-1 | critical | data loss | run x | open |
| F-2 | minor | typo | run y | fixed |
Re-check: F-2.

## Waivers requested

None.
