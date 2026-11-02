<!-- why: a Re-check line quoted inside a code block does not count -->
<!-- expect: Re-check -->
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
| F-2 | major | off by one | run x | fixed |
```
Re-check: F-2 verified at abc1234.
```

## Waivers requested

None.
