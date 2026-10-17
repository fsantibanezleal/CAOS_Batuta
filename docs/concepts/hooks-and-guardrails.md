# Hooks and guardrails

A hook is a speed bump on a text command, not a sandbox. Batuta uses hooks to refuse what must not happen in a session, and
backs every one with a script that runs without hooks and a CI check, because a hook can be blocked by organization policy,
dropped from a settings file another session rewrote, or defeated by a command the hook cannot read. The complete list of
rules, handlers and equivalents is the [enforcement matrix](../reference/enforcement-matrix.md); this page explains the
mechanism and the reasoning.

## What Claude Code guarantees, and what it does not

From the hooks reference (https://code.claude.com/docs/en/hooks):

- Exit code 0 is success; exit code 2 is a blocking error on the events that can block, with stderr as the reason; "exit 1 is
  non-blocking. Use exit 2 for policy enforcement." Any other exit code is non-blocking.
- Hooks fail open by default: a crashed or timed-out hook lets the action through. `onFailure: "block"` (Claude Code v2.1.295
  or later) turns a start failure, an exit code other than 0 or 2, invalid JSON or a timeout into a block, but it has no
  effect on Stop, SubagentStop, TaskCompleted, TeammateIdle or async hooks. The page does not say what an older client does
  with the key, so that behaviour is UNVERIFIED: run the plugin on v2.1.295 or later, or the five guards may not fail closed.
- `if` is best-effort and not a security boundary; "command hooks execute shell commands with your full user permissions".
- A PreToolUse "allow" never overrides a deny rule, and a hook decision does not bypass permission rules
  (https://code.claude.com/docs/en/permissions). So a guard is additive: the unbypassable layer is `permissions.deny` in
  managed settings.
- A plugin's `hooks/hooks.json` wraps the event map in a top-level `hooks` key, plugin subagents ignore `hooks`,
  `mcpServers` and `permissionMode` frontmatter, and `allowManagedHooksOnly` blocks plugin hooks entirely
  (https://code.claude.com/docs/en/plugins). Batuta's agent files therefore carry no hooks; every check is a plugin-level
  entry.

## The launcher and the contract of a handler

Every hook entry runs one launcher, `scripts/hook.py <handler id>` (contract C31). A handler is a function
`handler(payload: dict) -> dict` that takes the C16 input of the event and returns a handler result (`contract_version`,
`exit_code` 0 or 2, `output` a C16 output object or null, `message` required for exit code 2). An area module declares its
handlers in a literal `HOOKS = {"<id>": handler}`, ids are unique across areas, and the launcher resolves the id. The
launcher prints `output`, writes `message` to stderr and exits with `exit_code`.

The launcher itself fails open (requirement GUARD-2): an unknown id, a handler that raises, an invalid result or a malformed
lock file writes the reason to stderr and exits 1, a non-blocking error. It validates every handler result through the
contract with no event list of its own, so the C16 output of any event the contract knows passes. It never decides that a
failure should block: only an entry marked `"onFailure": "block"` in `hooks.json` does. A guard that must block when it cannot
decide is wired that way; one that is only a discipline check is not.

## What is wired

`plugins/batuta/hooks/hooks.json` has 11 entries. Each runs `"$CLAUDE_PLUGIN_OPTION_PYTHON" -I
"${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" <id>` in shell form with `shell: "bash"`, a bounded `timeout` (15 s for guards, 30 s
for the others) and a short status message.

| Event | Handler id | Does | onFailure |
|---|---|---|---|
| SessionStart (`startup\|resume`) | `session-check` | the device check; "Batuta device check: OK" or INCOMPLETE with the exact fix, within two seconds | continue |
| PreToolUse | `guard-automation` | blocks scheduled tasks, autostarts, services, WMI, cron or systemd enablement, headless Claude, detached or hidden processes, unbounded polling loops, `.wslconfig` and `wsl.conf` edits | block |
| PreToolUse | `guard-destructive` | blocks force-push to protected branches, hard reset, git clean, `rm -rf` of roots, disk formatting | block |
| PreToolUse | `guard-locked-tests` | denies a change to a locked test or to the lock file; points to `tdd change-request new` | block |
| PreToolUse | `guard-approvals` | denies agents any write under `approvals/`, every `spec approve`, `spec hook-approval`, `tdd change-request decide` and every direct run of `hook.py` | block |
| PreToolUse | `guard-secrets` | denies reading files that match the secret globs | block |
| PreToolUse (`Agent\|Task`) | `guard-require-brief` | an Agent launch must name a brief that satisfies C02 | continue |
| SubagentStop | `subagent-stop` | holds a briefed agent once until its report passes `report check` | not applicable |
| UserPromptSubmit | `spec-approval`, `tdd-change-request` | record a typed approval or change decision | continue |
| Stop | `gate-stop` | blocks once while a unit with uncommitted changes has a failing gate check | not applicable |

Matchers: a command guard reads `tool_input.command` of any tool that carries one, so its entry matches `Bash|PowerShell|Monitor`;
omitting `Monitor` would let a command through the Monitor tool that the shell tools would stop. The file guards match
`Edit|Write|MultiEdit|NotebookEdit`, and `guard-secrets` also matches `Read|Grep|Glob|NotebookRead`. `guard-automation` matches
both groups because it also denies writes to `.wslconfig` and similar paths. `hooks.json` refuses a `matcher` on an event that has
none (Stop, UserPromptSubmit) and refuses `onFailure` together with `async`, because the platform ignores it there and a guard
marked fail-closed would fail open.

Why `guard-require-brief` continues: it is a delegation discipline check, not a safety boundary; a crash must not stop the
session, and the ledger and report checkers catch an undelegated launch afterwards. The other five guards protect state that
cannot be restored, so a failure to decide blocks.

## Choosing the interpreter

Hooks run the interpreter named by the plugin option `python` (the variable `CLAUDE_PLUGIN_OPTION_PYTHON`, exported by
Claude Code to every hook process): `python3` on macOS and Linux, `py` or the absolute path of `python.exe` on Windows,
Python 3.10 or newer, and Git Bash installed on Windows because the hooks run in bash (plan decision 19, from the hooks
reference). The shell form runs `sh` on macOS and Linux and Git Bash on Windows; the exec form needs a real executable on
the `PATH`, and no Python name exists on every OS, so the shipped file uses the shell form. A wrong or missing interpreter
does not silence the hooks: the five guards exit non-zero and, being fail-closed, block every guarded call until the option is
fixed; the others fail open. `init doctor` checks that the option resolves to Python 3.10 or newer. Settings written for a
device by `device restore` (the non-plugin channel) carry the device's absolute interpreter path and launcher path instead;
contract C31 validates both profiles.

## How the guards read a command

The guards parse shell text, not intent. Every pattern is bounded (keyword gaps never cross another occurrence of the keyword,
repetitions are bounded, quoted strings are found by a linear scan), and `tests/test_guard_review_timing.py` runs every
pattern against 50,000-character hostile inputs. A command is analysed through nesting (`bash -c`, `cmd /c`, `pwsh -c`),
chaining and the usual spellings. Creating a link (`ln -s`, `mklink`, `New-Item -ItemType SymbolicLink`) with a protected
path as an operand is denied outright, with no later read or write needed. The reason string tells the agent not to retry
through another shell, script or tool and to give the human the exact command instead.

`guard <name> --explain` prints what a guard checks and what it found in the current project; `guard <name> --payload FILE`
runs one guard on a payload and exits 0 for allow, 1 for deny, 2 for ask. Real output on the first project guide's scratch
project, for an Edit of a locked test and for a scheduled-task command:

```
REFUSED BLOCKED by guard-locked-tests: tests/test_greeter.py is a locked test (task T-001). A locked test changes only through an approved change request: file one with `tdd change-request new` ...
guard locked-tests: deny

REFUSED BLOCKED by guard-automation (no unattended automation): creates or changes a Windows scheduled task (schtasks). Do not retry it through another shell, script or tool. If this was only a plain text search for the pattern, use the Grep or Read tool instead. Otherwise stop and give the user the exact command so they can run it themselves.
guard automation: deny
```

Through the launcher the same command produces a C16 PreToolUse output with `permissionDecision: "deny"` and exit code 0,
which is how Claude Code receives a denial.

## The CI twin of every rule

Principle 5 ([principles](principles.md)) says every hook has a script and a CI twin. In practice: `guard scan --diff RANGE` runs
the automation and destructive rules over the lines a change adds, `leaks scan` checks public hygiene, `tdd check` checks the
lock against file hashes, `spec freeze --check` and `gate check` check the approval hashes, and the project template's
`batuta-gates` workflow runs them on every push and pull request. The scan settings (`guards.scan_ignore`,
`protected_branches`, `destructive_disable`) come from the base revision of the range, never from the change under review,
and nothing is exempt silently: a hit in an ignored file and a hit excused by an inline marker are WARN lines with a count; the
marker `batuta-guard: ignore <rule-id>` excuses only the rule it names. A change to the security keys of `batuta.json`
(`guards.*`, `tdd.lock_file`) in a reviewed diff is a WARN, and a write to that file by an agent is an `ask`.

## Known limits of the guards

Variables and string concatenation (`$n = 'Register-Sched' + 'uledTask'; & $n`, `f=tests/a.py; echo x > $f`) hide a command or
a path from every guard: a documented limit, with the CI equivalents as the backstop. A path built at run time inside a script,
a variable that holds a path, or a program that writes a locked file from its own code is not visible to a PreToolUse guard.
The bash sandbox of Claude Code does not run on native Windows (macOS, Linux and WSL2 only; "on native Windows, Claude Code runs
commands unsandboxed"), so on Windows the only hard guardrails are permission rules, hooks and managed settings
(https://code.claude.com/docs/en/sandboxing; the route to a real sandbox is WSL2 or a container). The full list of residual
risks, each with its controls, is in [known limits](../reference/known-limits.md).

## The no-unattended-automation rule

`guard-automation` exists because a session that schedules work, installs an autostart or detaches a process outlives the
attention of the person who started it. Batuta's rule is stricter than Anthropic's guidance, which supports unattended runs
inside containers or VMs with credentials held outside the agent (https://code.claude.com/docs/en/agent-sdk/secure-deployment);
under Batuta every run is started by hand, bounded in time and ends with the command. A repository's own `.claude/settings.json`
hooks run under `claude -p` without a trust dialog (https://code.claude.com/docs/en/headless), which is one more reason the
guard denies headless launches.

## Sources

- Design: software design document sections 2 (principle 5), 3.3 decisions 8, 12, 15, 17, 19 and requirements GUARD-1 to
  GUARD-3; contracts C16, C31; `plugins/batuta/hooks/hooks.json`; `batuta_lib/guards/` and `scripts/hook.py`.
- The guard area, leaks area and plugin fragments; the [enforcement matrix](../reference/enforcement-matrix.md).
- https://code.claude.com/docs/en/hooks, /permissions, /plugins, /sandboxing, /headless, /agent-sdk/secure-deployment
- Real output captured in a scratch project (see the [first project guide](../guides/first-project.md)).
