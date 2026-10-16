---
name: delegate
description: Use when launching a named agent on a linted brief, on the subagent lane, the Agent SDK lane or a provider lane, and when accepting the agent's report.
allowed-tools: Bash(python *) Read Grep Glob Agent
argument-hint: <brief path>
---

# Delegate a brief to an agent and accept the report

Gate: none. This is how every builder and checker step of L0-understand to L10-lessons runs.

1. The brief passes lint: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" brief lint BRIEF`
2. Plan where it runs and write the request (C30):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" dispatch plan --brief BRIEF --lane subagent`
3. Launch on the lane:
   - `subagent` (default, interactive sessions, your Claude Code login): call the Agent tool with
     `subagent_type="batuta:implementer"` (or the role's agent), an explicit `model` taken from the role table
     (`route show`), and a prompt that names the brief path. The agent's definition carries the delegation contract.
   - `sdk` (long units that must not use the subscription, resumable): `dispatch plan --lane sdk`, then
     `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" dispatch run --request REQUEST` (a dry run), then the same with
     `--apply`. The credential comes from the variable named in batuta.json, never from a file in the repository.
   - `provider:NAME` (another model family, cheaper or local models, a second-opinion adversary): the same two commands
     with `--lane provider:NAME`; a provider lane without tool use returns a patch or a report that you apply after the gates.
   - An unfinished SDK run continues with
     `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" dispatch resume --result RESULT --apply`.
4. When the agent returns, check its report against the brief:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" report check --brief BRIEF`
5. Update the ledger status:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" report ledger-status --write`
6. Accept only after the check passes and you re-checked the load-bearing claims yourself. A PARTIAL or BLOCKED row stays
   partial; a failed agent is not relaunched by default.

On a non-zero exit: `report check` exit 1 means the report is defective (missing rows, placeholders, no evidence): send it
back or fix the brief, never accept it. Exit 2 is an honest PARTIAL or BLOCKED: record it as such and decide the next
step. A `dispatch` refusal (cost cap, time cap, an unpriced model) is a decision for the human, not something to bypass.
