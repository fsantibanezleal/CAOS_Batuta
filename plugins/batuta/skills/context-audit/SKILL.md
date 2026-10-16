---
name: context-audit
description: Use when a session feels heavy or before adding rules or memory: measures what loads at session start and checks it against the budgets.
allowed-tools: Bash(python *) Read Grep Glob
---

# Audit the always-loaded context

Gate: none. The budgets are `budgets` in batuta.json (user core, project core, memory index, unscoped rules).

1. Print the session-start payload breakdown: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" context measure`
2. Fail when something always loaded exceeds its budget: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" context check`
3. Fix a memory index that grew (a short index of pinned lines plus topic pages, one page opened when its trigger fires):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" memory index --memory-dir DIR --project NAME`
   Run it again with `--apply` to write.
4. Rebuild the knowledge index, the path-scoped stubs and the core from the manifest (C12):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" context build --manifest FILE --out OUT`
5. Move anything that is not needed every session out of the always-loaded files: a path-scoped rule, a skill or a
   knowledge unit read by trigger. Quote only measured numbers in your report, with the command that produced them.

On a non-zero exit: exit 1 from `context check` names the file and the budget it exceeds: trim or move content, then check
again; never raise a budget to pass. Exit 2 is a warning (for example a missing optional file): report it.
