<!-- why: blocked is a boolean -->
<!-- expect: front matter /blocked -->
---
feature: 001-validator
phase: P3-red
gates:
  P0-research: passed
  P1-spec: passed
  P1b-contracts: waived
  P2-freeze: passed
  P3-red: pending
waivers:
  - {gate: P1b-contracts, reason: "no external interfaces", by: alex, date: 2026-10-11}
blocked: maybe
---

## Notes

On track.
