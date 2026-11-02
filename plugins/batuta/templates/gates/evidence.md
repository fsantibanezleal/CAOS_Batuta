<!-- Copy to specs/<feature>/evidence/<gate>.md. Written by the adversary (routine gates) or the reviewer (critical gates), never by the builder. -->
<!-- Set gate, feature, verdict, role, model (as routed by gates.critical and the two adversary models of batuta.json), the full commit SHA reviewed and the date. -->
<!-- This template says FAIL on purpose: a gate passes only on an evidence file whose verdict is PASS or PASS-WITH-FIXES. -->
<!-- Every finding that is open or fixed carries a real reproduction. A PASS has no open critical or major finding. PASS-WITH-FIXES adds one `Re-check: <finding id>` line per fixed finding. -->
---
gate: L7-build
feature: example
verdict: FAIL
role: adversary
model: sonnet
commit: "0000000"
date: 2026-01-01
---

## Definition of done restated

The criteria of the gate, restated from the gate file and the approved plan.

## Commands and output

Each command run at the reviewed commit, with its output and exit code.

## Findings

| Id | Severity | Claim | Reproduction | Status |
|---|---|---|---|---|

## Waivers requested

None.
