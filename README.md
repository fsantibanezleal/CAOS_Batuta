# CAOS_AGENTIC_HARNESS

A public, device-agnostic harness that governs AI-assisted engineering with Claude Code. You pick the main
session's model and reasoning; the harness governs everything else: who does each task, on which model, under
which spec, with which tests, guards and gates, what loads into context, and how a device is set up. Only results
that pass deterministic gates and an independent adversarial check are approved and promoted.

**Status: pre-release, under construction toward 0.01.000.** Version `0.01.000` (`VERSION`). Nothing here is
published to a registry.

## What it is

The harness is built on a few principles, each with a gate that checks it (full text in
[ADR-0001](docs/decisions/ADR-0001-architecture.md)):

1. Enforce on artifacts, not prompts: locked tests, hash-bound approvals and gate checkers decide.
2. The builder never grades itself: every phase ends with an independent check by an agent with fresh context.
3. Route by risk and cost: scripts first, small models for lookups and runs, a large model only for critical gates.
4. Small preload, everything else on demand.
5. Every hook has a script and a CI twin.
6. No machine paths: roots come from environment variables or a config file.
7. Measured claims only.
8. Dry run by default, honest exit codes, idempotent writes.

It has two consumers: anyone, through a plugin, a one-command installer or a project template; and the
maintainer's own setup, which sits as a private overlay on top of a pinned harness version.

## What ships today

Only the repository skeleton and the command dispatcher. The dispatcher discovers area modules and reports one
that fails to load as a warning instead of crashing. Only the `version` area is implemented:

```
python plugins/harness/scripts/harness.py version show      # prints 0.01.000
node bin/harness.mjs version show                           # same, through the npx entry
```

Every other area in the design (routing, briefs, reports, specs, test locks, gates, context, device, guards,
init) is planned and is not available yet.

## Install

All install channels are planned and not yet available:

| Channel | Status |
|---|---|
| Claude Code plugin marketplace (`.claude-plugin/marketplace.json`, plugin `harness`) | planned, not yet available |
| `npx github:fsantibanezleal/CAOS_AGENTIC_HARNESS#<tag> <command>` | planned, not yet available |
| GitHub and copier project template | planned, not yet available |

The manifests and the npx entry exist in this repository so that the channels can be tested, but no release has
been cut and no channel is supported.

## Layout

```
.claude-plugin/marketplace.json   marketplace listing for the plugin "harness"
plugins/harness/                  the plugin
  .claude-plugin/plugin.json      plugin manifest (semver form of VERSION)
  scripts/harness.py              single CLI entry, stdlib Python 3.10+
  scripts/harness_lib/areas/      one module per command area, discovered at start
bin/harness.mjs                   npx entry (Node 18+, no dependencies); runs harness.py
scripts/                          repository maintenance scripts (content standards check)
docs/                             wiki: concepts, guides, reference, decisions
tests/                            unit tests (stdlib unittest)
```

Planned, not present yet: `plugins/harness/agents/`, `skills/`, `hooks/`, `templates/`, `contracts/`.

## Develop and test

```
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_content_standards.py
```

Python 3.10 or newer; no dependencies. CI runs the same two commands on push to `develop` and `main`
(`.github/workflows/ci.yml`). See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch flow and conventions,
[CHANGELOG.md](CHANGELOG.md) for what changed and [LESSONS.md](LESSONS.md) for lessons per unit.

## License

Apache-2.0, see [LICENSE](LICENSE). Security reports: [SECURITY.md](SECURITY.md). Conduct:
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
