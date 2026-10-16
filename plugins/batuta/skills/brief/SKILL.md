---
name: brief
description: Use when about to hand work to an agent: write the brief first. Creates a brief from the template with its ledger row and lints it before launch.
allowed-tools: Bash(python *) Read Grep Glob Edit Write
argument-hint: <topic> <agent>
---

# Write and lint a delegation brief

Gate: none. A brief is the input of every delegated step of L0-understand to L10-lessons; the contract is C02.

1. Create the brief and its ledger row (the ledger is `<coordination_root>/delegation/ledger.md`):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" brief new --slug SLUG --topic TOPIC --agent AGENT --title "TITLE"`
   AGENT is any agent of the plugin (searcher, runner, implementer, test-author, doc-writer, adversary, reviewer) or
   general-purpose. Use `--agent test-author` for a red step and `--agent adversary` for a gate check; the model and the kind
   come from the agent file. Add `--sizing PATH` for a product, and `--model` only for an escalation you can justify.
2. Fill every `<fill: ...>` slot: goal, context, definitions, the files in scope, numbered deliverables (D1, D2, ...),
   checks (C1, C2, ...) each with a backticked command, the working directory, the report path. Implement, job and
   skeleton briefs also carry the contract-first sections: contracts, invariants, missing-data behavior, environment.
3. Lint it until it passes:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" brief lint BRIEF`
4. Launch it with the `delegate` skill. Never launch an agent on a brief that has not passed lint.

On a non-zero exit: exit 1 is a refusal (an unfilled slot, a missing section, a check without a command): fix the brief
and lint again. Exit 2 is a warning (an escalation, the fable model, more than eight deliverables, a write scope that
overlaps another open brief): resolve it or write the reason into the brief.
