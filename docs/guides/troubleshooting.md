# Troubleshooting

`init doctor` and `device check` report each probe as `OK`, `WARN` or `FAIL`, and every failure ends with `fix:` followed by
the command or the action. This page lists each message, what it means and what to do. Messages are quoted from the code
(`batuta_lib/areas/init.py` and `batuta_lib/areas/device.py`). In the transcripts `batuta` stands for
`python <plugin folder>/scripts/batuta.py`.

```
batuta init doctor [--project DIR] [--channel auto|device|plugin]
batuta device check [--hook]
```

`doctor` reads only, finishes in a few seconds and exits 1 when any probe fails, 2 when there are only warnings, 0 otherwise.
`--channel auto` picks `plugin` when `CLAUDE_PLUGIN_ROOT` is set, else `device`.

## doctor messages

| Message | Meaning | Fix |
|---|---|---|
| `FAIL Python X is older than 3.10` | the interpreter is too old | install Python 3.10 or newer; for npx set `BATUTA_PYTHON` to its command (for example `py -3`); for the plugin set the plugin option `python` |
| `FAIL Git Bash not found: the plugin's hooks run through bash on Windows` | plugin channel on Windows without Git Bash (the WSL launcher in System32 does not count) | install Git for Windows (https://git-scm.com/download/win) |
| `OK Git Bash not found; the device channel does not need it` | device channel hooks run through the profile's Python | none |
| `WARN Node not found: only the npx channel needs Node` | no Node 18 or newer | install Node 18+ only if you want `npx github:fsantibanezleal/CAOS_Batuta` |
| `WARN Node vX is older than 18` | same | install Node 18 or newer |
| `WARN claude CLI not found: the plugin channel is unchecked here` | no `claude` on the PATH | install Claude Code to use the plugin channel |
| `WARN plugin option python is not set and python3 is not on PATH` | plugin channel, default interpreter missing | set the plugin option `python` to Python 3.10 or newer (on Windows `py` or the full path of `python.exe`) |
| `FAIL plugin option python '<value>' ... cannot be run` | the configured command does not start | set the option to a working Python 3.10 or newer |
| `FAIL plugin option python '<value>' ... is Python X, older than 3.10` | too old | set the option to Python 3.10 or newer |
| `FAIL configuration: ...` | `batuta.json` is invalid against C01 after `$VAR` expansion | fix the file named in the message, or recreate the user file with `init user --apply` |
| `FAIL roots: ...` | a root resolves inside a repository, to a drive root, to the home folder or onto a missing drive | set the root in `batuta.json` or its `BATUTA_*` variable to an absolute folder outside any repository |
| `FAIL root 'temp' ... is a file, not a folder` | the root path is a file | point the root at a folder |
| `FAIL root 'temp' ... is not writable` | no write access | give your account write access or point the root elsewhere |
| `FAIL device copy not found at ...` | no deploy yet (device channel) | run `init user --apply` |
| `SKIP no device copy; the plugin channel does not need one` | plugin channel | none |
| `FAIL project configuration: ...` | `.batuta/batuta.json` of the project is invalid | fix the file named |
| `FAIL .github/workflows/batuta-gates.yml not found: the required CI job batuta-gates is missing` | the workflow was not rendered or was deleted | run `init project --target DIR --apply` |
| `FAIL ... has no test step (the step with id: tests)` | the job lost its `id: tests` step | restore it with `init update`, or add the step |
| `FAIL the batuta-gates test step runs 'A' but tdd.test_command is 'B'` | CI and the replay run different commands; the head check and the CI run must be one process | make them one string: edit the `tests` step or `tdd.test_command` |
| `SKIP <folder> is not a Batuta project` | no `.batuta/batuta.json` and no workflow here | run `init project --apply` there, or run doctor from the project |

## device check messages

| Message | Meaning | Fix |
|---|---|---|
| `FAIL device copy: ...` or `device copy at ... lacks ...` | the copy is missing parts, or its profile is bad | `device deploy --apply` (a broken copy is repaired from the source in `deployed_from`) |
| `FAIL presets: ...` | the preset files in the copy are invalid | `device deploy --apply` |
| `FAIL settings: ... does not exist` | no `~/.claude/settings.json` | `device restore --apply` |
| `FAIL settings.json lacks ...` | settings were reset, or another session dropped items (see [devices](../concepts/devices-and-portability.md)) | `device restore --apply`; it verifies by re-reading, 3 attempts |
| `WARN` lines | a user value kept on purpose, or a preset skipped because the copy has no launcher | read them; they leave the session start line OK |
| `FAIL user core ... ` | the rendered user core differs from its template output | `device restore --apply` (an existing CLAUDE.md keeps its content and gains one managed block) |

At session start `session-check` prints "Batuta device check: OK (N items)" or "INCOMPLETE (k of N items)" with the exact `Fix:`.

## Common situations

- Every shell command or edit is blocked right after install. The plugin option `python` is wrong or missing: the five guards
  are fail-closed, so they block every guarded call until it works. Fix the option (see the [install guide](install.md)), and
  run Claude Code 2.1.295 or later; older clients are UNVERIFIED for `onFailure`.
- `context check` FAIL: a file is over its byte budget. Follow [budgets and memory](budgets-and-memory.md); never raise a budget.
- `tdd check` says the head check cannot read per-test outcomes: configure `tdd.test_command` to report each test (unittest
  `-v`, or pytest `-rA --junitxml=<path>`).
- `tdd check` says the working tree differs from HEAD: commit or run from a clean checkout.
- `gate status --set` is REFUSED: gates pass in order and only with valid evidence ([lifecycle](../concepts/lifecycle.md)).
- `spec approve` refuses: it needs a real console and waits 300 seconds. Type the phrase as a prompt where hooks run.
- A guard blocked something legitimate: it prints the rule id. A text search for a pattern such as `schtasks` is read as the
  command; use the Read or Grep tool instead. To excuse a line in `guard scan`, add `batuta-guard: ignore <rule-id>`.
- `leaks scan` reports user paths in `.batuta/delegation/`: briefs hold absolute paths by contract (C02), so keep that folder
  out of a public repository.
- `dispatch plan` REFUSED for an unset variable: the credential or endpoint variable named in `batuta.json` is not set.
- Hooks do not run on this device: use the CI twins (`guard scan`, `leaks scan`, `tdd check`, `gate check`) and `spec approve`.

## Sources

- `batuta_lib/areas/init.py` (doctor), `batuta_lib/areas/device.py` (check), `plugins/batuta/skills/doctor/SKILL.md`; the
  [enforcement matrix](../reference/enforcement-matrix.md).
