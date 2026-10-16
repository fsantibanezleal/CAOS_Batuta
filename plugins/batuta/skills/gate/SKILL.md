---
name: gate
description: Use when asking whether a lifecycle gate is passed or what blocks the next one: status, evidence files and the deterministic checks for L0 to L10.
allowed-tools: Bash(python *) Read Grep Glob
argument-hint: <feature id>
---

# Gate status and checks

Gates: L0-understand, L1-size, L2-decide, L3-contracts, L4-boundaries, L5-freeze, L6-skeleton, L7-build, L8-integrate,
L9-promote, L10-lessons. A gate is passed only with a valid evidence file from an agent that did not build the result.

1. Show where the feature stands: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate status FEATURE`
2. Enforce the rules (order, evidence, approvals, waivers, readiness at the release gate):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate check FEATURE`
3. Lint one evidence file (`specs/<feature>/evidence/<gate>.md`):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate evidence-lint specs/FEATURE/evidence/GATE.md`
4. The deterministic gate commands per phase: `size lint` (L1), `adr lint` and `tech lint` (L2), `contract lint` (L3),
   `provider lint` (L4), `spec lint` (L5), `skeleton check` (L6), `tdd check` (L7), `provider check` (L8):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" provider lint`
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" skeleton check`
5. Thresholds only ratchet upward:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate thresholds --check`
6. Set a gate to passed only after the `verify` skill produced PASS evidence (it is a dry run until you add `--apply`, which writes the status):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate status FEATURE --set L7-build=passed`
7. A waiver is a dated line a human writes in the status file; you never write one and never set `waived`.

On a non-zero exit: exit 1 is a failed rule (a gate passed out of order, evidence missing, invalid or older than the change
it certifies, a void approval): fix the cause and run the check again, never edit the status file to pass. Exit 2 is a warning
or an honest partial (for example evidence for a commit older than the head): say it in your report; it is not a pass.
