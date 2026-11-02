---
name: doctor
description: "Use when Batuta seems not to run, after an install or update, or on a new device: checks the setup, routing, contracts, hooks wiring and machine limits."
allowed-tools: Bash(python *scripts/batuta.py* *) Bash(py *scripts/batuta.py* *) Read Grep Glob
---

# Check that Batuta is set up and working

Gate: none.

1. The installer's own check first, read only (Python, Git Bash on Windows, Node and the `claude` CLI, the plugin option
   `python`, configuration, roots, the device copy and, in a project, that the `batuta-gates` workflow runs exactly
   `tdd.test_command`; each result is OK, WARN or FAIL with its fix):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" init doctor --channel plugin`
2. Device check, read only: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" device check`
3. Roles and agent files agree: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" route check`
4. Contracts, fixtures and the hooks file: every handler id of `hooks/hooks.json` must resolve to one handler:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" contract lint`
5. Machine limits (CPU, memory, free disk per root, Python, Node):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" preflight limits`
6. What a guard checks and what it found in this project:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" guard automation --explain`
7. The hooks run the interpreter of the plugin option `python` (the variable `CLAUDE_PLUGIN_OPTION_PYTHON`): Python 3.10 or
   newer, `python3` on macOS and Linux, on Windows `py` or the absolute path of python.exe, and Git Bash installed because
   the hooks run in bash. That variable is not exported to the Bash tool, which runs the commands above, so it cannot be
   read here: ask the human which interpreter the plugin option holds, or look at the plugin's configuration. A wrong
   or missing interpreter does not silence the hooks: the five guards exit non-zero and block every guarded call (shell
   commands, file edits and reads) until the option is fixed in the plugin configuration; the other hooks fail open. The CI
   twins (`guard scan`, `leaks scan`, `tdd check`) enforce the same rules without hooks.
8. Choose the interpreter for the commands in this skill yourself: `python` where it starts Python 3.10 or newer, else `py`
   on Windows or the interpreter the human names; run the same command with it.

`init doctor` also reports what the checks below cannot see (a missing Git Bash, Node or `claude` CLI, a plugin option
that is not Python 3.10 or newer); read its FAIL and WARN lines first, each ends with `fix:`.

On a non-zero exit: exit 1 names a failed check (an agent file out of line with its role, a hook id with no handler, an
invalid contract): fix that item and run the command again. Exit 2 is a warning (a missing optional file, a limit close to
exhausted): report it in your answer with the line that printed it.
