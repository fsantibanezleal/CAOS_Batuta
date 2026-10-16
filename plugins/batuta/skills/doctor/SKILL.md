---
name: doctor
description: Use when Batuta seems not to run, after an install or update, or on a new device: checks the setup, routing, contracts, hooks wiring and machine limits.
allowed-tools: Bash(python *) Read Grep Glob
---

# Check that Batuta is set up and working

Gate: none.

1. Device check, read only: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" device check`
2. Roles and agent files agree: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" route check`
3. Contracts, fixtures and the hooks file: every handler id of `hooks/hooks.json` must resolve to one handler:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" contract lint`
4. Machine limits (CPU, memory, free disk per root, Python, Node):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" preflight limits`
5. What a guard checks and what it found in this project:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" guard automation --explain`
6. The hook interpreter is the plugin option `python`: it must start Python 3.10 or newer (`python3` on macOS and Linux; on
   Windows `py` or the absolute path of python.exe, and Git Bash installed, because the hooks run in bash). If hooks never
   fire, the interpreter option is the first suspect; the CI twins (`guard scan`, `leaks scan`, `tdd check`) still enforce.
7. These commands use `python`; where only `py` exists, run the same command with `py`.

On a non-zero exit: exit 1 names a failed check (an agent file out of line with its role, a hook id with no handler, an
invalid contract): fix that item and run the command again. Exit 2 is a warning (a missing optional file, a limit close to
exhausted): report it in your answer with the line that printed it.
