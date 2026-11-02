# Documentation

The wiki of CAOS_Batuta. Everything here is transcribed from the persisted research, the design, the decision records and
the code; the command, configuration and contract references are generated from the code and a test fails when they drift.
Where a source did not confirm a claim the page says UNVERIFIED. The [repository README](../README.md) has the overview and
the install lines.

## Concepts

Why Batuta exists and how it thinks.

| Page | Covers |
|---|---|
| [Architecture](concepts/architecture.md) | the four layers, the areas, configuration, the repository layout (diagram) |
| [Principles](concepts/principles.md) | the eight principles, each with its finding and source |
| [The governed delivery lifecycle](concepts/lifecycle.md) | L0 to L10, the gate and the independent check of each, critical gates (diagram) |
| [Routing](concepts/routing.md) | script, named agent on an explicit model, or the main session; the role table |
| [Briefs, reports and the ledger](concepts/briefs-reports-ledger.md) | the delegation loop and its checks (diagram) |
| [Spec-driven development](concepts/spec-driven-development.md) | EARS requirements, the typed hash-bound freeze |
| [Test-driven development](concepts/test-driven-development.md) | locks, red and green grammar, history replay, change requests |
| [Contract-first parallel development](concepts/contract-first-parallel-development.md) | sizing, the catalog, availability states, the skeleton, waves (diagram) |
| [Context tiers and budgets](concepts/context-tiers.md) | what loads when, with the measured limits (diagram) |
| [Hooks and guardrails](concepts/hooks-and-guardrails.md) | the launcher, fail-open and fail-closed, the guards |
| [Dispatch lanes and cost caps](concepts/dispatch-lanes.md) | subagent, sdk and provider lanes |
| [Devices and portability](concepts/devices-and-portability.md) | no machine paths, rendered settings, the verified settings write |

## Guides

How to install, configure and use each area, with real captured output.

| Page | Covers |
|---|---|
| [Install](guides/install.md) | the plugin marketplace, npx, `init` and copier |
| [First project walkthrough](guides/first-project.md) | init, spec, freeze, red, green, gates, promote |
| [Delegating a unit](guides/delegating-a-unit.md) | brief, lane, report check, ledger |
| [Device setup on a new machine](guides/device-setup.md) | deploy, restore, check, backup |
| [Budgets and memory](guides/budgets-and-memory.md) | measure, check, move text between tiers, memory topic pages |
| [Adding a provider lane](guides/adding-a-provider.md) | configuration, prices and caps, a new adapter kind |
| [Troubleshooting](guides/troubleshooting.md) | every `doctor` message and its fix |

## Reference

| Page | Covers |
|---|---|
| [Command line](reference/cli.md) | every area and verb with its arguments (generated) |
| [Configuration](reference/configuration.md) | every `batuta.json` key with type, default and description (generated) |
| [Data contracts](reference/contracts.md) | the catalog C01 to C34 (generated) |
| [Enforcement matrix](reference/enforcement-matrix.md) | every enforced rule, its handler, its script or CI twin |
| [Skills](reference/skills.md) | the 13 skills: trigger and what each runs |
| [Known limits](reference/known-limits.md) | every accepted residual risk with its decision and controls |

Regenerate the generated pages with `python scripts/gen_reference.py` (`--check` compares without writing).

## Decisions

Architecture decision records, one file per decision, never edited in place once Accepted (a change is a new record that
supersedes the old one).

| Record | Title | Status |
|---|---|---|
| [ADR-0001](decisions/ADR-0001-architecture.md) | Principles and architecture | Accepted |
| [ADR-0002](decisions/ADR-0002-contracts-align-adr0080.md) | Align the data contracts with the dimensioned contract-first method and ship them inside the plugin | Superseded in part by ADR-0003 |
| [ADR-0003](decisions/ADR-0003-contracts-after-review.md) | The contracts after the adversarial review | Superseded in part by ADR-0004 |
| [ADR-0004](decisions/ADR-0004-contracts-final.md) | The contracts, final form: one ledger, one availability vocabulary, hooks.json as the registry | Accepted |
| [ADR-0005](decisions/ADR-0005-contracts-third-review.md) | The contracts after the third review | Accepted |
| [ADR-0006](decisions/ADR-0006-additive-contracts-r5.md) | First additive revision of the frozen contracts | Accepted |
