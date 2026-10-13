<!-- Copy to specs/<NNN-slug>/status.md and set `feature`. `gate status <feature> --set <gate>=passed --apply` moves a gate once its evidence file is valid. -->
<!-- A waiver is written by a human, never by an agent, as an entry of a `waivers:` list in this front matter. Example (ignored here, it is inside a comment): -->
<!-- waivers: - {gate: L3-contracts, reason: "no external interfaces", by: a-human, date: 2026-01-01} -->
---
feature: 000-example
phase: L0-understand
gates:
  L0-understand: pending
  L1-size: pending
  L2-decide: pending
  L3-contracts: pending
  L4-boundaries: pending
  L5-freeze: pending
  L6-skeleton: pending
  L7-build: pending
  L8-integrate: pending
  L9-promote: pending
  L10-lessons: pending
blocked: false
---

## Notes

Progress, decisions and the resume point of this feature. `gate hook-stop` appends a dated UNVERIFIED line here when a
session ends with a failing gate check.
