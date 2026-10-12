<!-- why: gate state outside the enum -->
<!-- expect: /gates/L7-build -->
---
feature: 001-validator
phase: L7-build
gates:
  L7-build: skipped
waivers:
  - {gate: L3-contracts, reason: "no external interfaces", by: alex, date: 2026-10-11}
blocked: false
---

## Notes

On track.
