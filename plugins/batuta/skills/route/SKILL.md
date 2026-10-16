---
name: route
description: Use when choosing which agent and model runs a task, or before launching any agent. Prints the role table (model, effort) from batuta.json and checks the agent files against it.
allowed-tools: Bash(python *) Read Grep Glob
---

# Route a task to a script, an agent or yourself

Gate: none. Routing applies to every lifecycle gate (L0-understand to L10-lessons).

1. Print the role table: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" route show`
2. Pick who does the task, in this order:
   - a script that already does it: run it;
   - deterministic and recurring work: write or extend one parameterized, tested script;
   - bounded reading or running: `batuta:searcher` (lookups) or `batuta:runner` (runs), both on the cheap model;
   - implementation, tests or docs: `batuta:implementer`, `batuta:test-author`, `batuta:doc-writer`, on the routine model;
   - the independent check of a gate: `batuta:adversary`; `batuta:reviewer` only for a critical gate or a critical review;
   - reasoning, plans, specs and integration stay in the main session.
3. Use the model the table names for the role and set it explicitly on the launch; an escalation to a stronger model is a
   decision you state, never a default.
4. Stay inside the caps of `caps` in batuta.json (concurrent agents, agents per task, reviews per task, spawn depth, cost).
5. After editing a role or an agent file, check them against each other:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" route check`
6. Next step for a task that goes to an agent: the `brief` skill, then the `delegate` skill.

On a non-zero exit: exit 1 means the configuration or an agent file is invalid or its model differs from its role: fix
the file or the role, never launch on a table that fails. Exit 2 is a warning (for example no configuration file, so the
defaults apply): read the WARN line and say it in your report.
