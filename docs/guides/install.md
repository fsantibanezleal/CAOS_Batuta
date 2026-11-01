# Install

Batuta has three install channels. They deliver different things (a plugin cannot carry settings or a CLAUDE.md, see
[devices and portability](../concepts/devices-and-portability.md)), so most people use the plugin and one of the other two.
Requirements: Python 3.10 or newer (standard library only), Git 2.30 or newer for `tdd`, Node 18 or newer only for the npx
channel, and on Windows Git Bash for the hooks of the plugin channel.

| Channel | Delivers | Use it for |
|---|---|---|
| Claude Code plugin marketplace | 7 agents, 13 skills, the hooks and the scripts | the guards, skills and agents in every session |
| `npx github:fsantibanezleal/CAOS_Batuta` | the command line, with no install | a one-off command, CI, a machine without the plugin |
| `init user`, `init project` and copier | the settings presets, the rendered user core, the project files and the CI workflow | a device and a project |

## 1. The plugin marketplace

One step, for Claude Code 2.1.275 or later:

```
/plugin install batuta --marketplace fsantibanezleal/CAOS_Batuta
```

The same from a shell needs Claude Code 2.1.292 or later:

```
claude plugin install batuta --marketplace fsantibanezleal/CAOS_Batuta
```

(Source for both versions: the plugin documentation read on 2026-10-11, https://code.claude.com/docs/en/plugins/install.)
The two-step form works on any version that has marketplaces:

```
/plugin marketplace add fsantibanezleal/CAOS_Batuta
/plugin install batuta@caos-batuta
```

The marketplace name is `caos-batuta` and the plugin name is `batuta` (`.claude-plugin/marketplace.json`). Add
`--scope user`, `project` or `local` to choose where `enabledPlugins` is written; project scope writes
`.claude/settings.json`, which is committed, and each collaborator still runs the install command once. To pin a release use
`fsantibanezleal/CAOS_Batuta#<tag>` (for example `#v0.01.000` once that tag exists) when adding the marketplace.

Claude Code asks for the plugin option `python`, the command that starts Python 3.10 or newer, used by every hook. Leave
`python3` on macOS and Linux; on Windows use `py` or the absolute path of `python.exe`, and install Git Bash, because the hooks
run in bash. A wrong interpreter does not silence the hooks: the five fail-closed guards exit non-zero and block every guarded
call until the option is fixed ([hooks and guardrails](../concepts/hooks-and-guardrails.md)).

Claude Code 2.1.295 or later is needed for `"onFailure": "block"`, which makes those guards fail closed. The hooks reference
does not say what an older client does with the key, so run the plugin on 2.1.295 or later (UNVERIFIED for older clients).

Check the install with the skill `/batuta:doctor`, or in a shell:

```
python "<plugin folder>/scripts/batuta.py" init doctor --channel plugin
```

What was verified: the plugin and marketplace manifests pass `claude plugin validate --strict` (Claude Code 2.1.301 and 2.1.310),
and on 2026-10-26 the install from the GitHub repository worked end to end in an empty configuration folder:
`claude plugin marketplace add fsantibanezleal/CAOS_Batuta`, then `claude plugin install batuta@caos-batuta` (Claude Code
2.1.310), left the plugin installed and enabled, with the `python` option still to set. Clients older than 2.1.301 were not
tried ([known limits](../reference/known-limits.md#install-channels)).

Update with `claude plugin update batuta@caos-batuta`. Third-party marketplaces do not auto-update, and Claude Code keeps the
cached copy until the plugin's `version` string changes, so a release bumps `version` in `plugin.json` and tags the commit
(https://code.claude.com/docs/en/plugins/loading, section on versions and updates). Remove with `claude plugin uninstall batuta`.
`claude plugin details batuta` prints the always-on token cost of the plugin.

## 2. npx, no install

```
npx github:fsantibanezleal/CAOS_Batuta <area> <verb> [options]
npx github:fsantibanezleal/CAOS_Batuta#<tag> version show
```

`bin/batuta.mjs` passes the arguments and the exit code through to `batuta.py`. It finds Python in this order: the
environment variable `BATUTA_PYTHON`, then `py -3` on Windows, `python3`, `python`; the first that reports 3.10 or newer wins.
Without a suitable Python it exits 1 and names every candidate it tried. The `package.json` `files` list ships `bin`,
`plugins/batuta`, `copier.yml`, `VERSION` and `LICENSE`, so a copy fetched this way has the contracts, agents and templates
(`tests/test_npx_package.py` checks every needed path against `npm pack --dry-run`).

Status: the entry is tested locally with Node (`tests/test_npx_entry.py`). Running `npx github:owner/repo` against the real
repository has not been done by any unit, and the research marks that `npx github:owner/repo` is accepted as an exec spec
as inferred from the npm spec grammar, not stated on the npm page (https://docs.npmjs.com/cli/v10/commands/npm-exec;
UNVERIFIED).

## 3. The device and the project

On a device, `init user` writes `<BATUTA_HOME>/batuta.json` when it is missing, deploys the device copy, restores the settings
presets and the user core, and installs the agent files into `~/.claude/agents/`. Every write is a dry run unless `--apply`;
what is replaced is backed up as `<name>.bak-<stamp>`; what `init` wrote is recorded in an install manifest
(`<deploy root>/installed.json`). See the [device setup guide](device-setup.md) for real output.

```
python scripts/batuta.py init user --var user_name=Ada            # dry run
python scripts/batuta.py init user --var user_name=Ada --apply
```

In a project, `init project --target DIR` renders `templates/project/` of the plugin: `AGENTS.md`, a short `CLAUDE.md` within
the project core budget, `.claude/settings.json` (merged append-only: the permission rules of the template are added, nothing
is removed or reordered), `.batuta/batuta.json`, the constitution, the thresholds, an example feature with its status file, a
foundation test and the `batuta-gates` workflow. The variables are `project_name`, `python_version` (default `3.12`),
`test_command` (default `python -m unittest discover -s tests -t . -v`), `default_branch` (default `main`) and `batuta_ref`
(the release tag the CI checks are fetched from; `init update` moves it).

```
python scripts/batuta.py init project --target . --var project_name=greeter            # dry run
python scripts/batuta.py init project --target . --var project_name=greeter --apply
```

Copier renders the same files with the same defaults:

```
copier copy gh:fsantibanezleal/CAOS_Batuta <destination>
```

`copier.yml` asks four questions (`project_name`, `python_version`, `test_command`, `default_branch`) and keeps the release tag
hidden; the template uses `{{ name }}` placeholders only, so both renderers produce identical bytes (checked against copier
9.19.1 by `tests/test_template_files.py`; the test skips where copier is absent).

Ownership rules: a seed file (`.batuta/batuta.json`, the constitution, thresholds, the example feature, the foundation test) is
yours after the first install and is never overwritten, even with `--force`. A managed file (`AGENTS.md`, the workflow, the
agent files) is rewritten only while it is an unchanged installed copy; a hand-edited one is kept and reported `DIFFERENT`
(exit 2) unless `--force` replaces it after a backup. An existing `CLAUDE.md` keeps its content and gains one block between
`<!-- batuta:begin ... -->` and `<!-- batuta:end -->`, rewritten in place by `init update`.

## Update and uninstall

`init update [--scope project|user]` renders again from the current templates and backs up every file it changes.
`init uninstall [--scope project|user]` restores the backup of each file `init` replaced and removes each installed file whose
hash (line endings ignored) is unchanged; an edited file is kept and reported `DIFFERENT` with exit 2, and the manifest keeps
it for a later run. Folders `init` created are removed when empty. `uninstall` refuses a manifest whose bases, paths or links
leave the project or the Batuta home, and deletes nothing.

## What to do next

Run the [first project walkthrough](first-project.md), then read the [concepts](../README.md#concepts).

## Sources

- The `init`, `fragments` and `reserve` area fragment and the skills, hooks and plugin manifest fragment, summarized in the
  [command reference](../reference/cli.md); `.claude-plugin/marketplace.json`, `plugins/batuta/.claude-plugin/plugin.json`,
  `package.json`, `copier.yml`, `bin/batuta.mjs`.
- https://code.claude.com/docs/en/plugins/install, /plugins/loading, /hooks (the `onFailure` note);
  https://docs.npmjs.com/cli/v10/commands/npm-exec; research dossier on official guidance, section D2 (2026-10-11).
- The validation record of Claude Code 2.1.301 (`claude plugin validate --strict`, both manifests, exit 0), in the project's
  coordination records.
