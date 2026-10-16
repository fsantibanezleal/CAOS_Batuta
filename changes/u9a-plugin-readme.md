## Skills, hooks and the plugin manifest

The plugin ships thirteen skills (`skills/<name>/SKILL.md`): `route`, `brief`, `delegate`, `spec`, `freeze`, `red`, `green`,
`gate`, `verify`, `promote`, `context-audit`, `doctor` and `lessons`. Each is a numbered procedure over the commands of
this CLI, the lifecycle gate it serves and what to do on a non-zero exit. `freeze` and `promote` are started by a person only.

`hooks/hooks.json` runs every handler through the launcher with the interpreter of the plugin option `python`:

```
"$CLAUDE_PLUGIN_OPTION_PYTHON" -I "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" <handler id>
```

| Event | Handler ids |
|---|---|
| SessionStart (`startup\|resume`) | `session-check` |
| PreToolUse | `guard-automation`, `guard-destructive`, `guard-locked-tests`, `guard-approvals`, `guard-secrets` (each `onFailure: "block"`), `guard-require-brief` |
| SubagentStop | `subagent-stop` |
| UserPromptSubmit | `spec-approval`, `tdd-change-request` |
| Stop | `gate-stop` |

Set the option `python` when Claude Code asks at install: `python3` on macOS and Linux, `py` or the absolute path of
python.exe on Windows (Python 3.10 or newer; Git Bash must be installed on Windows).

`"onFailure": "block"` in hooks needs Claude Code v2.1.295 or later (the hooks reference,
https://code.claude.com/docs/en/hooks, read 2026-10-16). The page does not say what an older client does with the key;
that behavior is UNVERIFIED, so run the plugin on v2.1.295 or later or the five guards may not fail closed.
