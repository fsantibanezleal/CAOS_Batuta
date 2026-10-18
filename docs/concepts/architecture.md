# Architecture

Batuta governs AI-assisted engineering with Claude Code. The user picks the main session's model and reasoning effort;
everything below it (who does each task, on which model, under which spec, with which tests, guards and gates, what loads
into context, how a device is set up) is governed by deterministic checks, and only results that also pass an independent
adversarial check are approved and promoted. It has two consumers: anyone, through a plugin, a one-command installer or a
project template; and the maintainer's own setup, which sits as a private overlay (rules content, memories, device
profiles) on a pinned Batuta release.

![Architecture in four layers: the person and main session; the plugin with 7 agents, 13 skills and one hook launcher; one command line with 24 areas; artifacts under data contracts C01 to C34.](../assets/architecture.svg)

## Layers

1. The person and the main session. The user chooses the model and effort. Reasoning, plans, specs and integration stay in
   the main session, and only the person types an approval (the spec freeze, a decision on a locked-test change request).
2. The plugin `batuta`. Seven agents on explicit models ([routing](routing.md)), thirteen skills that are numbered
   procedures over the command line, and `hooks/hooks.json`, which runs every handler through one launcher
   ([hooks and guardrails](hooks-and-guardrails.md)). The plugin carries no CLAUDE.md and no settings, because a plugin cannot.
3. One command line, `batuta.py <area> <verb>`, standard-library Python 3.10 or newer, with one module per area. The
   dispatcher imports every module of `batuta_lib/areas/` in sorted order; a module that defines `AREA`, `HELP` and
   `register(subparsers)` adds its verbs; a module that fails to import is reported as `WARN area <name> failed to load:
   <error>` and skipped, so the CLI keeps working. A module that defines `HOOKS = {id: handler}` also provides hook handlers.
4. Artifacts under data contracts. Every file that crosses a unit boundary has a versioned JSON Schema with valid and invalid
   fixtures ([contract-first parallel development](contract-first-parallel-development.md), the
   [contracts catalog](../reference/contracts.md)).

## The areas

| Area | Does | Owner unit |
|---|---|---|
| `route`, `brief`, `report` | the role table, briefs and their lint, report checks and the ledger | U2 |
| `spec`, `size`, `adr`, `tech` | specs and their freeze, sizing, decision records, the technology matrix | U3 |
| `tdd` | test locks, the commit grammar, history check and replay | U4 |
| `gate`, `skeleton`, `provider`, `lessons` | evidence, status, thresholds, promotion, the walking skeleton, availability, lessons | U5 |
| `context`, `memory` | the knowledge index, budgets, memory topic pages | U6 |
| `device`, `preflight` | deploy, restore, check and back up a device; machine limits | U7 |
| `guard`, `leaks` | the six guards and the guard scan; the public hygiene scan | U8 |
| `init`, `fragments`, `reserve` | install, doctor, update, uninstall; shared-file fragments and reserved numbers | U9 |
| `dispatch` | plan, run and resume a brief on a lane under cost and time caps | U13 |
| `contract` | lint the contracts, validate an artifact, compute waves | U0 |
| `version` | print the version | U1 |

Every verb and option is in the [command reference](../reference/cli.md). Global options `--config PATH`, `--json` and
`--version` work before or after the verb. Writes are a dry run unless `--apply`, are atomic (a temporary file in the same
folder, then `os.replace`) and idempotent; output lines carry a tag and, with `--json`, the C20 object; exit codes are 0 ok,
1 failure or refusal, 2 warnings or an honest partial.

## Configuration

`batuta.json` (contract C01) is found by `--config PATH`, then `$BATUTA_CONFIG`, then the project file
`.batuta/batuta.json`, then the user file `<BATUTA_HOME>/batuta.json` (`BATUTA_HOME` defaults to `~/.batuta`), then the
built-in defaults; `batuta_lib/config.py` is the only reader. `$VAR` expands from the environment before validation. The keys
are in the [configuration reference](../reference/configuration.md).

## The repository layout

```
.claude-plugin/marketplace.json   marketplace listing for the plugin "batuta"
plugins/batuta/
  .claude-plugin/plugin.json      plugin manifest
  agents/                         the seven roles
  skills/<name>/SKILL.md          the thirteen skills
  hooks/hooks.json                every handler through scripts/hook.py
  scripts/batuta.py               the single command line entry
  scripts/batuta_lib/             areas/ (one module per area), guards/, dispatch/ and shared helpers
  contracts/                      data contracts C01 to C34 with fixtures
  templates/                      project/, user/, spec/, gates/, knowledge/, presets/
bin/batuta.mjs + package.json     the npx entry (Node 18+, no dependencies)
copier.yml                        the project template for copier
docs/                             this wiki
tests/                            unit tests (standard-library unittest)
```

## The install channels

The plugin marketplace, `npx github:fsantibanezleal/CAOS_Batuta <command>`, and `init project` or copier for a project
template. The [install guide](../guides/install.md) describes each; the channels differ in what they can deliver, as the
[devices page](devices-and-portability.md) explains.

## The lifecycle that ties it together

The areas implement the gates of [the lifecycle](lifecycle.md), each ending with an independent check; the
[principles](principles.md) say why.

## Sources

- Design: software design document sections 1 to 3 and 5; [ADR-0001](../decisions/ADR-0001-architecture.md) (written under the
  earlier names of the project; the layout it states is the one above with `batuta` for `harness`).
- `plugins/batuta/scripts/batuta.py` (the dispatcher), `batuta_lib/config.py`, `batuta_lib/output.py`.
- https://code.claude.com/docs/en/plugins for the plugin layout.
