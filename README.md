# Batuta

The conductor's baton: one hand directing many players to one score.

Batuta is a public, device-agnostic toolkit that governs AI-assisted engineering with Claude Code. You pick the main
session's model and reasoning; Batuta governs everything else: who does each task, on which model, under which spec, with
which tests, guards and gates, what loads into context, and how a device is set up. Only results that pass deterministic
gates and an independent adversarial check are approved and promoted.

**Status: 0.01.000, the first release** (`VERSION`, tag `v0.01.000`). The channels below install from this repository;
nothing is published to a package registry.

## Who it is for

Engineers and teams who let AI agents write code and want it done under a spec, with tests written first and locked, with
the cheapest sufficient model on each task, with guards that fail closed, and with a checker that proves the order from git
history instead of trusting a prompt. It also serves one maintainer's own setup, which sits as a private overlay on a pinned
Batuta release.

## What it is

Eight principles, each with the finding it comes from and the gate that checks it ([principles](docs/concepts/principles.md)):
enforce on artifacts, not prompts; the builder never grades itself; route by risk and cost; small preload, everything else on
demand; every hook has a script and a CI twin; no machine paths; measured claims only; dry run by default.

What ships:

- one command line, `batuta.py <area> <verb>`, standard-library Python 3.10 or newer, with 24 areas (routing, briefs, reports,
  specs, test locks, gates, context, device, guards, dispatch, init and the rest; the
  [command reference](docs/reference/cli.md) lists every verb);
- a Claude Code plugin `batuta`: 7 agents on explicit models, 13 skills, and hooks that run 11 handlers through one launcher
  (five guards fail closed);
- 34 versioned data contracts with fixtures ([contracts catalog](docs/reference/contracts.md));
- a project template with the required CI job `batuta-gates`, a copier template and an npx entry;
- dispatch lanes that run a brief on a Claude Code subagent, the Agent SDK or another model provider under cost caps.

## Install

| Channel | How |
|---|---|
| Claude Code plugin marketplace | `/plugin install batuta --marketplace fsantibanezleal/CAOS_Batuta` (Claude Code 2.1.275 or later; plugin `batuta` in marketplace `caos-batuta`) |
| npx, no install | `npx github:fsantibanezleal/CAOS_Batuta <area> <verb>` (Node 18 or newer) |
| A project | `python plugins/batuta/scripts/batuta.py init project --target . --apply`, or `copier copy gh:fsantibanezleal/CAOS_Batuta <destination>` |
| A device | `python plugins/batuta/scripts/batuta.py init user --apply` |

Every write is a dry run until `--apply`. The one-step line is the form `claude plugin validate` advises; from a shell it needs
Claude Code 2.1.292 or later. The [install guide](docs/guides/install.md) has the details, the plugin option `python` the hooks
need, and what has and has not been verified end to end (the marketplace install and the `npx github:` run were verified from this
repository on 2026-10-26).

## Quick start

Run these in an empty scratch project (the last command creates `specs/` where it runs), with the plugin folder path adjusted.

```
python plugins/batuta/scripts/batuta.py version show          # prints 0.01.000
python plugins/batuta/scripts/batuta.py contract lint         # checks every contract and its fixtures
python plugins/batuta/scripts/batuta.py init project --target . --var project_name=demo          # dry run
python plugins/batuta/scripts/batuta.py spec new --title "Greeting" --tier S --apply
```

The [first project walkthrough](docs/guides/first-project.md) goes from `init project` to a promotion with real captured output.

## Documentation map

- [Concepts](docs/README.md#concepts): why Batuta exists and how it thinks: [architecture](docs/concepts/architecture.md),
  [principles](docs/concepts/principles.md), [lifecycle](docs/concepts/lifecycle.md), [routing](docs/concepts/routing.md),
  [briefs, reports and the ledger](docs/concepts/briefs-reports-ledger.md),
  [spec-driven development](docs/concepts/spec-driven-development.md),
  [test-driven development](docs/concepts/test-driven-development.md),
  [contract-first parallel development](docs/concepts/contract-first-parallel-development.md),
  [context tiers](docs/concepts/context-tiers.md), [hooks and guardrails](docs/concepts/hooks-and-guardrails.md),
  [dispatch lanes](docs/concepts/dispatch-lanes.md), [devices and portability](docs/concepts/devices-and-portability.md).
- [Guides](docs/README.md#guides): [install](docs/guides/install.md), [first project](docs/guides/first-project.md),
  [delegating a unit](docs/guides/delegating-a-unit.md), [device setup](docs/guides/device-setup.md),
  [budgets and memory](docs/guides/budgets-and-memory.md), [adding a provider](docs/guides/adding-a-provider.md),
  [troubleshooting](docs/guides/troubleshooting.md).
- [Reference](docs/README.md#reference): [commands](docs/reference/cli.md), [configuration](docs/reference/configuration.md),
  [contracts](docs/reference/contracts.md) (these three are generated from the code), the
  [enforcement matrix](docs/reference/enforcement-matrix.md), [skills](docs/reference/skills.md) and
  [known limits](docs/reference/known-limits.md).
- [Decisions](docs/README.md#decisions): the architecture decision records.

## Layout

```
.claude-plugin/marketplace.json   marketplace listing for the plugin "batuta"
plugins/batuta/                  the plugin: agents, skills, hooks, scripts, contracts, templates
  scripts/batuta.py              single CLI entry, stdlib Python 3.10+
  scripts/batuta_lib/areas/      one module per command area, discovered at start
bin/batuta.mjs                   npx entry (Node 18+, no dependencies); runs batuta.py
copier.yml                       project template for copier
scripts/                         repository scripts: content standards check, reference generator
docs/                            wiki: concepts, guides, reference, decisions
tests/                           unit tests (stdlib unittest)
```

## Develop and test

```
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_content_standards.py
python scripts/gen_reference.py          # regenerates docs/reference/{cli,configuration,contracts}.md
```

Python 3.10 or newer; no dependencies. The full suite takes about half an hour. CI runs the tests and the standards check on
push to `develop` and `main` (`.github/workflows/ci.yml`). See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch flow,
[CHANGELOG.md](CHANGELOG.md) for what changed and [LESSONS.md](LESSONS.md) for lessons per unit.

## License

Apache-2.0, see [LICENSE](LICENSE). Security reports: [SECURITY.md](SECURITY.md). Conduct:
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
