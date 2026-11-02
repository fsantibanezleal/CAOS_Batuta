---
name: verify
description: "Use at the end of every gate: an independent agent with fresh context reproduces each claim at the reviewed commit and writes the evidence file."
allowed-tools: Bash(python *scripts/batuta.py* *) Bash(py *scripts/batuta.py* *) Read Grep Glob Agent
argument-hint: <gate id> <feature id>
---

# Verify a gate with the adversary

Gate: the one being verified (L0-understand to L10-lessons). The builder never grades its own work.

1. Fix the inputs: the gate id, the feature id, the project folder, the repository, the commit SHA under review and the
   artifacts of the gate. Do not hand the checker the builder's summary or reasoning.
2. Choose the checker from `gates` in batuta.json: `batuta:adversary` (sonnet) for routine gates;
   `batuta:reviewer` (opus) for a critical gate (L2-decide, L5-freeze, L9-promote by default) and for a critical unit.
3. Write and lint its brief with the `brief` skill (the evidence path `specs/<feature>/evidence/<gate>.md` is its only write),
   then launch it with the `delegate` skill: `subagent_type="batuta:adversary"` or `"batuta:reviewer"`, model from `route show`.
4. Check the evidence file the agent wrote (verdict PASS, FAIL or PASS-WITH-FIXES; commands with output; a findings table):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate evidence-lint specs/FEATURE/evidence/GATE.md`
5. Check the agent's report against the brief:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" report check --brief BRIEF`
6. Re-run one or two of its load-bearing commands yourself before you rely on it.
7. On PASS, record the gate (it is a dry run until you add `--apply`, which writes the status):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate status FEATURE --set GATE=passed`
8. On FAIL or PASS-WITH-FIXES, the builder fixes every finding and this skill runs again on the new commit. Never waive a
   finding yourself; a waiver is a human's dated line.

On a non-zero exit: exit 1 from `evidence-lint` means the evidence is invalid (a claim without command and output, a
wrong role or model): send it back, the gate stays open. Exit 1 from `gate status --set` refuses the pass: read the reason.
Exit 2 is a warning: report it and do not treat the gate as passed.
