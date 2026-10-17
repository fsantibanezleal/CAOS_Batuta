# Devices and portability

Batuta is meant to run the same way on a laptop and on a workstation, on Windows, macOS and Linux, and to be restorable on
a new machine from a versioned bundle. Three rules make that possible: no shipped file contains a machine path, installed
files are rendered per device from a profile, and the one file a running session can rewrite, the user's settings, is
written with a verified merge and checked at every session start.

## No machine paths

Roots come from `batuta.json` (contract C01 `roots`, with `$VAR` expansion) or from the environment: `BATUTA_HOME`,
`BATUTA_TEMP`, `BATUTA_DATA`, `BATUTA_WORKTREES` and `BATUTA_CONFIG` (see the
[configuration reference](../reference/configuration.md)). An unset root variable falls back to `<BATUTA_HOME>/temp`, `data`
or `worktrees`. A root that resolves inside a repository, to a drive root, to the home folder or onto a missing drive is a
configuration error. The code, templates, fixtures and documents carry no drive letter and no user path;
`scripts/check_content_standards.py` and `leaks scan` fail the build on one.

ADR-0001 records the incident that made this a rule: a restored file once pointed every session at another device's drive.
The platform adds its own reasons: `${CLAUDE_PLUGIN_ROOT}` changes on every plugin update, so state is never written there;
`CLAUDE_CONFIG_DIR` relocates `~/.claude`; and plugin paths on Windows are substituted with forward slashes
(https://code.claude.com/docs/en/plugins, https://code.claude.com/docs/en/settings). Every command writes UTF-8 with LF line
endings, uses `pathlib`, and has no shell-specific syntax, so the same code runs on the three systems.

## Two channels

| Channel | What reaches the machine | How |
|---|---|---|
| Plugin | agents, 13 skills, `hooks.json` and the scripts, under `${CLAUDE_PLUGIN_ROOT}` | `/plugin install batuta --marketplace fsantibanezleal/CAOS_Batuta`, see the [install guide](../guides/install.md) |
| Device | a copy of the plugin's `scripts/`, `contracts/`, `templates/`, `reference/` and `.claude-plugin/` under a deploy root, a device profile, the settings presets, the rendered user core and the agent files in `~/.claude/agents/` | `init user --apply` or `device deploy`, then `device restore` |

A plugin cannot carry `env`, permissions or deny rules, a model, or a CLAUDE.md: "a `CLAUDE.md` at the plugin root is NOT
loaded and validation warns", and only `agent` and `subagentStatusLine` of a plugin's `settings.json` take effect
(https://code.claude.com/docs/en/plugins, manifest reference). That is the main portability limit, and it is why the settings
presets, the cost guardrails of [routing](routing.md) and the always-loaded core travel through the device channel and the
project template, not through the plugin install.

## The device profile and the deploy

`device deploy --apply` copies the plugin's own folders to the deploy root (default `<BATUTA_HOME>`), mirrors only its own
folders (a `batuta.json` next to the copy stays), leaves out the contracts' `fixtures/` test data, and writes `device.json`
(contract C15): the interpreter and the roots of that device. It refuses a deploy root inside a repository, on a missing
drive, or in a folder that holds someone else's `scripts/`, and it never descends into or deletes through a symlink or any
Windows reparse point it finds where a managed file or folder belongs. A second `--apply` changes nothing. A broken device
copy is repaired from the source it was deployed from (`deployed_from` in its profile), never by deploying the copy into
itself.

## The verified settings write

Running sessions rewrite `~/.claude/settings.json` as part of normal operation (the model, the effort, plugin and update
choices), and the settings files are reloaded live in every running session. There is no documented guarantee about
concurrent writes: issue 82167 reports the file replaced by exactly `{}` five times in three days with about 15 concurrent
sessions, and issue 95347 reports cross-session collisions on `effortLevel`
(https://github.com/anthropics/claude-code/issues/82167, https://github.com/anthropics/claude-code/issues/95347; behavioural
evidence from users, not confirmed by maintainers; the official pages say nothing about atomicity or locking, UNVERIFIED
beyond that). So user-level settings are not a stable store for policy, and Batuta treats them as volatile:

- `device restore` merges `templates/presets/*.json` (contract C17) into the file without removing or reordering anything,
  after a `.bak-<stamp>` copy, and then re-reads the file and merges what is missing again into the file as it is now, up to 3
  attempts 0.5 s apart; what is still missing is an error that names the items. A value of the wrong type (for example
  `permissions.deny` that is not a list) refuses and touches nothing.
- A re-read or replace that fails with a file-system error, or that finds a half-written file, counts as a lost race and is
  retried. The residual race is a write by another session that lands between restore's compare read and its `os.replace`;
  it is not closable without a file lock that Claude Code does not take, and restore still reports success.
- `device check` runs at every session start through the `session-check` hook. It reads only, finishes in well under two
  seconds, never runs git, a subprocess or the network, and reports each item OK or FAIL with the exact fix. An empty `{}`
  settings file is exactly the case it catches.

Real output on a fake home folder whose `settings.json` was reset to `{}` (the interpreter and deploy paths are replaced by
placeholders):

```
OK device copy ~/.batuta (version 0.01.000)
FAIL settings.json lacks env.CLAUDE_CODE_SUBAGENT_MODEL = sonnet, env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH = 1, env.CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS = 4, permissions.deny "Agent(Explore)", permissions.deny "Agent(Plan)", permissions.deny "Agent(model:fable)", permissions.ask "Agent(model:opus)", hooks.SessionStart session-check
OK agents available: 7 role(s)
OK user core current
device check: incomplete
```

and the SessionStart message Claude Code receives:

```
Batuta device check: INCOMPLETE (1 of 4 items)
- FAIL settings.json lacks env.CLAUDE_CODE_SUBAGENT_MODEL = sonnet, ...
Fix: "<python>" "~/.batuta/scripts/batuta.py" device restore --apply
```

After `device restore --apply` every item is OK again. The line is phrased as facts, because Anthropic advises that
imperative framing in `additionalContext` can trigger prompt-injection defences
(https://code.claude.com/docs/en/hooks); the output is capped at 10,000 characters.

## The user core and the stubs

The user's always-loaded core is rendered from a template when `batuta.json` has `user_core.template` (a path relative to the
deploy root) and `user_core.values` (the `{{name}}` placeholders); a placeholder without a value is refused, and without the
key the step is skipped with a WARN naming it. The shipped template and reference files are in
`plugins/batuta/templates/user/`. `device restore --stubs RULES_DIR` installs the path-scoped stubs of a `context build` into
`~/.claude/rules/`, rewriting each link so it resolves from there. A file that is not a generated stub is never replaced
without `--force`. See [context tiers](context-tiers.md).

## Backup and restore on a new machine

`device backup --out DIR --apply` collects what a device learned and cannot rebuild: the agent files, the agentic keys of
`settings.json`, memory pages, hand-written rules, the user `batuta.json` and, when it is not rendered from a template,
`CLAUDE.md`. Rendered files and generated stubs are rebuilt, never backed up. The set is fixed by design, not configurable
(plan decision 21). Any secret pattern refuses the whole backup and writes nothing; the scan reads every file in every
plausible decoding (UTF-8, UTF-16 little and big endian, and the raw bytes with NUL removed) and each file name, and a
reviewed line is exempted by its sha256 with `--allow`. `--out` must be empty, new, or hold a `MANIFEST.json` from an earlier
backup, and every path must resolve inside it once links are resolved. The [device setup guide](../guides/device-setup.md)
walks through deploy, restore, check and backup.

## Managed settings and protected paths

For an organization, `plugins/batuta/templates/managed-settings.example.json` is the layer users cannot remove. Claude Code
reads `managed-settings.json` from a system folder: `C:\Program Files\ClaudeCode\` on Windows,
`/Library/Application Support/ClaudeCode/` on macOS, `/etc/claude-code/` on Linux and WSL, plus an HKLM registry value named
`Settings` on Windows (https://code.claude.com/docs/en/managed-settings; the plugin fragment marks the exact folders UNVERIFIED
against the live page, so confirm before rolling it out). Writing there needs a local administrator, and a malformed HKLM
value or file makes Claude Code refuse to start. Managed `deniedModels`, `allowManagedHooksOnly` and deny rules are the
unbypassable layer; user-level hooks and rules are protected from a running session only because writes to `~/.claude` are
prompted, classifier-gated or denied in every permission mode except `bypassPermissions`
(https://code.claude.com/docs/en/permission-modes), so agents are not run in `bypassPermissions` when a guard lives in user
settings.

## Sources

- Design: software design document sections 1, 2 (principle 6), 3.2, decisions 19 and 21, requirements DEV-1 to DEV-3 and
  DIST-1; ADR-0001; contracts C01, C15, C17; `batuta_lib/areas/device.py`, `device_profile.py`, `settings_merge.py`.
- The `device` and `preflight` area fragment, summarized in the [command reference](../reference/cli.md); the
  [enforcement matrix](../reference/enforcement-matrix.md).
- https://code.claude.com/docs/en/plugins, /settings, /hooks, /managed-settings, /permission-modes;
  https://github.com/anthropics/claude-code/issues/82167 and /95347 (behavioural evidence).
- Real output captured on a fake home folder in a scratch location.
