# Device setup on a new machine

A device gets a copy of the plugin's `scripts/`, `contracts/`, `templates/`, `reference/` and `.claude-plugin/` and a
profile, `device.json` (contract C15), that holds that device's interpreter and roots. This guide takes a clean machine
through deploy, restore, check and backup. All output is real: it was captured with a fake home folder (a throwaway folder
set as `HOME`, `USERPROFILE` and `BATUTA_HOME`), so nothing touched a real `~/.claude`. Paths are shown as `~/.batuta` and
`<python>`. In the transcripts `batuta` stands for `python <plugin folder>/scripts/batuta.py`. The reasoning behind the design
is in [devices and portability](../concepts/devices-and-portability.md).

## Before you start

- Python 3.10 or newer, Git, and (Windows) Git Bash if you use the plugin channel. Node 18 or newer only for the npx channel.
- Decide the roots by role, never by a drive: set `BATUTA_TEMP`, `BATUTA_DATA` and `BATUTA_WORKTREES` in the environment (or
  `roots` in `batuta.json`). Unset, they fall back to `<BATUTA_HOME>/temp`, `data` and `worktrees`. A root that resolves
  inside a repository, to a drive root, to the home folder or onto a missing drive is refused.
- `BATUTA_HOME` defaults to `~/.batuta`.

## 1. Deploy and restore with `init user`

`init user` runs deploy and restore together, writes `<BATUTA_HOME>/batuta.json` when it is missing and installs the agent
files. A dry run first:

```
batuta init user --var user_name=Ada
NEW batuta.json (batuta.json)
NEW device.json
NEW .claude-plugin: 1 file(s)
NEW contracts: 48 file(s)
NEW reference: 4 file(s)
NEW scripts: 66 file(s)
NEW templates: 36 file(s)
SKIP restore of the settings and the user core is planned after the device copy exists (run with --apply)
NEW agents/adversary.md (agents/adversary.md)
NEW agents/doc-writer.md (agents/doc-writer.md)
NEW agents/implementer.md (agents/implementer.md)
NEW agents/reviewer.md (agents/reviewer.md)
NEW agents/runner.md (agents/runner.md)
NEW agents/searcher.md (agents/searcher.md)
NEW agents/test-author.md (agents/test-author.md)
SKIP dry run: nothing written (use --apply)
init user: the user install in ~/.batuta (dry run)
```

With `--apply`. Here the fake home already had a `settings.json` with `{"model": "opus", "env": {"MY_SETTING": "kept"}}`:

```
batuta init user --var user_name=Ada --apply
...
OK backup of settings.json at settings.json.bak-20261016-233137
NEW settings.json env.CLAUDE_CODE_SUBAGENT_MODEL = sonnet
NEW settings.json env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH = 1
NEW settings.json env.CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS = 4
NEW settings.json permissions.deny "Agent(Explore)"
NEW settings.json permissions.deny "Agent(Plan)"
NEW settings.json permissions.deny "Agent(model:fable)"
NEW settings.json permissions.ask "Agent(model:opus)"
NEW settings.json hooks.SessionStart session-check
WARN user core skipped: set user_core.template (and user_core.values) in batuta.json
NEW CLAUDE.md (CLAUDE.md)
NEW agents/adversary.md (agents/adversary.md)
...
init user: the user install in ~/.batuta (applied)
```

(exit code 2: the WARN. The lines marked `...` are the device-copy lines of the dry run, unchanged.) The existing keys
were kept and the presets merged in append-only, after a backup copy:

```json
{
  "model": "opus",
  "env": {
    "MY_SETTING": "kept",
    "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet",
    "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "4"
  },
  "permissions": {
    "deny": ["Agent(Explore)", "Agent(Plan)", "Agent(model:fable)"],
    "ask": ["Agent(model:opus)"]
  },
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "<python>",
                  "args": ["-I", "~/.batuta/scripts/hook.py", "session-check"], "timeout": 10}]}
    ]
  }
}
```

(Reformatted for width; the file keeps Claude Code's own layout.) The SessionStart entry carries the device's absolute
interpreter and the device copy's launcher, rendered from the profile, in exec form; the plugin channel uses the plugin
option instead.

The user core is rendered from a template when `batuta.json` has `user_core.template` (relative to the deploy root) and
`user_core.values`. Add them, for example `"user_core": {"template": "templates/user/CLAUDE.template.md", "values":
{"user_name": "Ada", "language": "English", "tone": "direct", ...}}`; the placeholders are `language`, `tone`, `user_name`,
`python`, `deploy_root`, `temp_root`, `data_root`, `models_root` and `worktrees_root`, and a placeholder without a value is
refused. The shipped template is deliberately generic; keep the length under the budget (7000 bytes by default).

## 2. Check

```
batuta device check
OK device copy ~/.batuta (version 0.01.000)
OK settings.json holds every preset item
OK agents available: 7 role(s)
OK user core current
device check: complete
```

The check reads only, finishes in well under two seconds and never runs git, a subprocess or the network. At every session
start the `session-check` hook prints the same result to Claude Code (`batuta device check --hook` shows the object:
`"Batuta device check: OK (4 items)"`). Without the plugin hooks, run `init doctor` instead, which adds the probes for the
interpreter, Git Bash on Windows, Node, the `claude` CLI, the configuration and the roots:

```
batuta init doctor
OK Python 3.14.4 runs Batuta
OK Git Bash found (<path of bash.exe>)
OK Node v24.15.0 (needed by the npx channel only)
WARN claude CLI not found: the plugin channel is unchecked here; fix: install Claude Code to use the plugin channel
OK configuration valid (user, ~/.batuta/batuta.json)
OK roots writable: temp, data, models, worktrees
OK device copy ~/.batuta (version 0.01.000)
OK settings.json holds every preset item
OK agents available: 7 role(s)
OK user core current
SKIP <folder> is not a Batuta project (no .batuta/batuta.json and no .github/workflows/batuta-gates.yml); run `init project --apply` there to make it one
doctor (device channel): no failures in 1.6s
```

(The Python and Node versions, the Git Bash path and the timing are those of the machine the output was captured on; this machine is Windows, hence the Git Bash line.) `preflight limits` reports CPU,
memory, free disk per root, GPU, Python and Node, and reports a missing GPU or Node as absent, not as an error.

## 3. Restore after the settings were lost

A running Claude session can rewrite `~/.claude/settings.json` at any time, and issue reports describe it reset to `{}`
([devices and portability](../concepts/devices-and-portability.md)). The check catches that at the next session start, with the
exact fix. Real output after resetting the fake home's `settings.json` to `{}`:

```
batuta device check
OK device copy ~/.batuta (version 0.01.000)
FAIL settings.json lacks env.CLAUDE_CODE_SUBAGENT_MODEL = sonnet, env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH = 1, env.CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS = 4, permissions.deny "Agent(Explore)", permissions.deny "Agent(Plan)", permissions.deny "Agent(model:fable)", permissions.ask "Agent(model:opus)", hooks.SessionStart session-check
OK agents available: 7 role(s)
OK user core current
device check: incomplete
```

Restore is a dry run first, then applies:

```
batuta device restore
NEW settings.json env.CLAUDE_CODE_SUBAGENT_MODEL = sonnet
...
NEW settings.json hooks.SessionStart session-check
SAME CLAUDE.md (user core, rendered for this device)
device restore: dry run, nothing written (use --apply)

batuta device restore --apply
OK backup of settings.json at settings.json.bak-20261016-233305
NEW settings.json env.CLAUDE_CODE_SUBAGENT_MODEL = sonnet
...
device restore: applied
```

and `device check` is complete again. The write is verified: restore re-reads the file after writing and merges what is
missing again into the file as it is now, at most 3 attempts 0.5 seconds apart, and an item still missing is an error that
names it. A value of the wrong type refuses and touches nothing. The session-start line is INCOMPLETE only for a failed item
with its exact fix; a user value kept on purpose (an existing `env` key with another value) and a preset skipped because the
device copy has no launcher are notes and leave it OK.

Path-scoped rule stubs from a `context build` are installed with `device restore --stubs RULES_DIR`; a file that is not a
generated stub is never replaced without `--force`.

## 4. Back up what the device learned

```
batuta device backup --out <bundle folder>
SKIP CLAUDE.md is rendered from its template (user_core.template); rebuilt, not backed up
NEW MANIFEST.json
NEW agents: 7 file(s)
NEW config: 1 file(s)
NEW settings.agentic.json
device backup: 10 new, 0 changed, 0 removed, 0 unchanged files in <bundle folder> (dry run, nothing written (use --apply))
```

The backup collects the agent files, the agentic keys of `settings.json` (`env`, `model`, `modelSettings`, `hooks`,
`autoUpdatesChannel`), every project's memory pages, hand-written rules, the user `batuta.json` and, when it is not rendered
from a template, `CLAUDE.md`. Rendered files and generated stubs are rebuilt, never backed up. The set is fixed by design.

Any secret pattern refuses the whole backup and writes nothing. The scan reads every file as UTF-8, UTF-16 (both byte orders)
and as raw bytes with NUL removed, and also scans each file name; a reviewed line is exempted by its sha256 with
`--allow SHA256`. `--out` must be empty, new, or hold a `MANIFEST.json` from an earlier backup, and every path must resolve
inside it once links are resolved. Commit the bundle to your own repository (a private one, because memory pages are
personal).

Restoring on a new machine: install Batuta, run `init user --apply`, copy the agent files, memory pages and rules of the
bundle to their places, and run `device restore --apply` and `device check`. No command reads a bundle back and applies it
(the area has `deploy`, `restore`, `check` and `backup` only), so that copy is a manual step (UNVERIFIED as a documented
procedure: the code and fragments describe the backup but not an apply step).

## 5. Managed settings, for an organization

`plugins/batuta/templates/managed-settings.example.json` is the layer users cannot remove. Copy it to the managed settings
folder of the operating system, keep the deny rules, and set `allowManagedHooksOnly` to restrict hooks to the managed ones.
The exact folders are listed in [devices and portability](../concepts/devices-and-portability.md); confirm them against
https://code.claude.com/docs/en/managed-settings before rolling out (UNVERIFIED in the plugin fragment).

## Troubleshooting

See [troubleshooting](troubleshooting.md) for every `doctor` message and its fix.

## Sources

- The `device` and `preflight` area fragment and the `init` fragment, summarized in the [command reference](../reference/cli.md);
  contracts C01, C15, C17; `batuta_lib/areas/device.py`; plan decisions 19 and 21.
- https://code.claude.com/docs/en/settings, /managed-settings, /hooks; https://github.com/anthropics/claude-code/issues/82167.
- All output captured with `batuta.py` against a throwaway home folder.
