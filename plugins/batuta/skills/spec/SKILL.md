---
name: spec
description: "Use when starting a feature or product, before any code: understand, size, decide technology, write contracts and the spec (L0 to L5, up to the freeze)."
allowed-tools: Bash(python *scripts/batuta.py* *) Bash(py *scripts/batuta.py* *) Read Grep Glob Edit Write
argument-hint: <feature id or title>
---

# Specify before building (L0 to L5)

Gates: L0-understand, L1-size, L2-decide, L3-contracts, L5-freeze. Each gate ends with the `verify` skill.

1. L0-understand: write the problem statement, users, constraints and success measures into the spec, with persisted
   research that cites its sources and marks what is UNVERIFIED.
2. L1-size: sizing.md lists every component with owner role, estimate and risk:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" size lint`
3. L2-decide: one ADR per decision, then the technology matrix (pinned version, license, evidence for each choice):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" adr new --title "TITLE" --apply`
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" adr lint`
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tech lint`
4. L3-contracts: a data contract for every interface, listed in the catalog, then the parallel waves:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" contract lint`
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" contract graph`
5. L5-freeze, the spec (EARS requirements, each with a runnable Gate; interfaces; tasks with waves):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" spec new --title "TITLE" --tier M --apply`
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" spec lint`
6. After tests exist, build the trace matrix:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" spec trace SPEC_ID --apply`
7. When lint is clean, ask the human to run `/batuta:freeze` (only a person can start it). You never approve a spec yourself.

On a non-zero exit: exit 1 is a refusal (a requirement without a Gate, an id reused, a missing ADR for tier L, an open
`[NEEDS CLARIFICATION]`): fix the artifact and run the same command again. Exit 2 is a warning (for example a component
without a unit): resolve it or state it in the gate's evidence.
