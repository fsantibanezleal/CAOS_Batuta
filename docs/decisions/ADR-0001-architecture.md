---
id: ADR-0001
title: Principles and architecture of CAOS_AGENTIC_HARNESS
status: Accepted
date: 2026-10-11
review_trigger: before release 0.01.000, and whenever a unit changes the layout or the CLI contract
supersedes: none
superseded_by: none
---

# ADR-0001: Principles and architecture

Status: Accepted, 2026-10-11. Transcribed from the software design document (sections 2 and 3). The design rests
on persisted research dossiers (official Anthropic guidance, a landscape of tools and methods, context
organization, and a review of a reference harness); each principle names the finding it comes from. Every
requirement in the design names the gate that verifies it.

## Context

The harness governs AI-assisted engineering with Claude Code: the user picks the main session's model and
reasoning, and everything else (who does each task, on which model, under which spec, which tests, which guards,
which gates, what loads into context, how a device is set up) is governed here. It has two consumers: anyone,
through a plugin, a one-command installer or a project template; and the maintainer's own setup, which becomes a
private overlay (rules content, memories, device profiles) on top of a pinned harness version.

## Principles

1. **Enforce on artifacts, not prompts.** Locked tests, hash-bound approvals, history replay and gate checkers
   decide; prompt-only test-driven development gave no quality gain at 3 to 8 times the tokens (reference
   harness decision record).
2. **The builder never grades itself.** Every phase ends with an independent check by an agent with fresh context
   and no access to the builder's reasoning, reproducing every claim.
3. **Route by risk and cost.** Scripts first; Haiku for lookups and runs; Sonnet for implementation, tests, docs
   and routine adversarial checks; Opus only for critical gates and decisions (the reference harness ran
   everything on Opus).
4. **Small preload, everything else on demand.** An always-loaded core under budget; path-scoped rules; an index
   of knowledge units read by trigger; generated memory topic pages.
5. **Every hook has a script and a CI twin.** Hooks can be blocked by organization policy or dropped from a
   settings file rewritten by another session.
6. **No machine paths.** Roots come from environment variables or a config file; installed files are rendered per
   device (a restored file once pointed every session at another device's drive).
7. **Measured claims only.** Token numbers come with their method; no unmeasured savings claims.
8. **Dry run by default, honest exit codes, idempotent writes, atomic replace** for every tool that writes.

## Architecture

```
CAOS_AGENTIC_HARNESS/
  .claude-plugin/marketplace.json     marketplace listing plugin "harness"
  plugins/harness/
    .claude-plugin/plugin.json        name "harness", version = VERSION semver form
    agents/                           searcher, runner (haiku); implementer, test-author, doc-writer, adversary (sonnet);
                                      reviewer (opus). No frontmatter hooks (ignored in plugins).
    skills/<name>/SKILL.md            route, brief, delegate, spec, freeze, red, green, gate, verify, promote,
                                      context-audit, doctor, lessons (descriptions trigger-first, bodies on demand)
    hooks/hooks.json                  SessionStart doctor; PreToolUse guards; SubagentStop report check keyed by agent;
                                      UserPromptSubmit approval capture; Stop gate. All through scripts/hook.py launcher.
    scripts/harness.py                single CLI entry (stdlib Python 3.10+), subcommands below
    scripts/harness_lib/...           modules (one per area; plain modules, not a published package)
  templates/project/                  copier-compatible project template (AGENTS.md, CLAUDE.md, .claude/settings.json,
                                      .harness/, specs/, .github/workflows/harness-gates.yml)
  templates/user/                     user-level core template and reference files
  bin/harness.mjs + package.json      npx entry: `npx github:fsantibanezleal/CAOS_AGENTIC_HARNESS#vX <cmd>`; delegates to
                                      harness.py (checks Python >= 3.10)
  docs/                               wiki (concepts, guides, reference, decisions)
  tests/                              unit tests per module + end-to-end self-test on scratch projects
  README, LICENSE (Apache-2.0), CODE_OF_CONDUCT, CONTRIBUTING, SECURITY, CHANGELOG, VERSION, LESSONS.md
```

The directories `agents/`, `skills/`, `hooks/` and `templates/` are added by later delivery units; this record
states the target layout.

### CLI contract (`harness.py <area> <verb>`)

| Area | Verbs |
|---|---|
| `route` | `show`, `check` (roles, models, effort, caps from config) |
| `brief` | `new`, `lint` |
| `report` | `check`, `ledger-status` |
| `spec` | `new`, `lint`, `trace`, `freeze`, `approve` (manual fallback) |
| `tdd` | `lock`, `check` (`--replay`) |
| `gate` | `check`, `status`, `evidence-lint`, `thresholds` |
| `context` | `build`, `check`, `measure`; `memory index` |
| `device` | `deploy`, `restore`, `check`, `backup`; `settings merge` |
| `guard` | `automation`, `locked-tests`, `approvals`, `secrets`, `destructive` (hook entry points) |
| `init` | `user`, `project`; plus `doctor`, `update`, `uninstall` |
| `leaks` | `scan` |
| `version` | `show` |

The dispatcher discovers areas: it imports every module in `harness_lib/areas/` (sorted), and each module that
defines `AREA`, `HELP` and `register(subparsers)` adds its verbs. A module that fails to import is reported as
`WARN area <name> failed to load: <error>` and skipped, so the CLI keeps working.

Global flags: `--config PATH`, `--apply` (writes), `--json` (machine output). Exit codes: 0 ok, 1 failure or
refusal, 2 warnings or honest partial. Output lines start with a tag: OK, NEW, CHANGED, SAME, MERGED, REMOVED,
MISSING, DIFFERENT, REFUSED, WARN, FAIL.

### Configuration (`harness.json`)

Resolution order: `--config`, `$HARNESS_CONFIG`, project `.harness/harness.json`, user `$HARNESS_HOME/harness.json`
(`HARNESS_HOME` default `~/.harness`). Keys:

```json
{
  "version": 1,
  "roots": {"temp": "$HARNESS_TEMP", "data": "$HARNESS_DATA", "worktrees": "$HARNESS_WORKTREES"},
  "roles": {
    "searcher": {"model": "haiku", "effort": "low"}, "runner": {"model": "haiku", "effort": "low"},
    "implementer": {"model": "sonnet", "effort": "medium"}, "test-author": {"model": "sonnet", "effort": "medium"},
    "doc-writer": {"model": "sonnet", "effort": "medium"}, "adversary": {"model": "sonnet", "effort": "high"},
    "reviewer": {"model": "opus", "effort": "high"}
  },
  "caps": {"max_concurrent_agents": 4, "max_agents_per_task": 8, "max_opus_reviews_per_task": 1, "spawn_depth": 1},
  "gates": {"critical": ["spec-freeze", "build", "release"], "adversary_model_critical": "opus",
            "adversary_model_routine": "sonnet"},
  "coordination_root": ".harness",
  "knowledge_manifest": ".harness/knowledge/manifest.json",
  "budgets": {"user_core_bytes": 7000, "project_core_bytes": 7000, "memory_index_bytes": 4000,
              "memory_index_lines": 60, "unscoped_rules_bytes": 2000}
}
```

`$VARS` expand from the environment; unset roots fall back to `<HARNESS_HOME>/temp|data|worktrees`. No drive
letter or user path appears in any shipped file.

### The governed delivery lifecycle

Spec-driven development starts before any spec: a system is understood, sized, decomposed and its technology
validated; then every interface gets a data contract; then every external dependency gets an adapter with a
contract-faithful fallback; then a walking skeleton is deployed; only then do parallel waves build the parts.
This is what makes autonomous, parallel, agentic development possible without cross-blocking.

| Phase | What is produced | Gate (deterministic) | Adversary |
|---|---|---|---|
| L0 understand | problem statement, users, constraints, success measures, persisted research | `report check` | claims sample re-fetched (sonnet) |
| L1 size and decompose | system map: repositories, components, modules, data stores, models, UIs, with size estimates and risks | `size lint` | missing components, under-estimates (sonnet) |
| L2 decide and validate technology | ADRs and technology evaluations: candidates, pinned versions, licenses, maturity, a spike per risky choice | `adr lint`, `tech lint` | version, license, maturity, alternatives (opus for the stack decision) |
| L3 contracts | data contracts for every interface: APIs, files, datasets, model I/O, events, UI view models | `contract lint`, `contract graph` (waves) | missing fields, ambiguity, coupling (sonnet) |
| L4 robust boundaries | adapter per external dependency with a fixture provider that honours the contract and declares `degraded`; model cards with a baseline model | `provider lint` | silent fallbacks, behaviour gaps (sonnet) |
| L5 spec and freeze | requirements (EARS) with gates; interfaces; tasks with waves; human approval hashed with ADRs and contracts | `spec lint`, `gate check` | reviewer (opus, critical) |
| L6 walking skeleton | end-to-end thin slice deployed to a preview on fixture providers; contract tests in CI | `skeleton check` | integration and UX review (sonnet) |
| L7 parallel waves | per wave and per unit: red (test-author), green (implementer) | `tdd check`, unit gates | per unit (sonnet; opus for critical units) |
| L8 integrate providers | real providers replace fixtures one at a time behind flags | `provider check` | reviewer for data and model providers (opus) |
| L9 verify and promote | thresholds, replay, trace, evidence; required non-skippable CI job; release | `gate check`, CI `harness-gates` | reviewer (opus) for release |
| L10 lessons | dated lesson per unit; ADRs revisited when their review trigger fires | lessons check; `adr lint` flags overdue reviews | none |

ADRs constrain development and stay open to improvement: each has a status (Proposed, Accepted, Superseded,
Deprecated), a review trigger (date or condition), and a supersession link; a change goes through a new ADR that
supersedes the old one, never an edit in place. Fallback providers are not mockups: they are fixture-backed
implementations of the real contract, labelled degraded at runtime and in the UI, and they are replaced, not kept.

### Phases and gates of the harness CLI

| Phase | Builder | Deterministic gate | Adversarial check | Human |
|---|---|---|---|---|
| P0 research | main session or a general-purpose agent on sonnet | `report check` (sources, UNVERIFIED marked) | adversary re-fetches a sample of claims (sonnet) | none |
| P1 spec | main session | `spec lint` (EARS rows, ids, a runnable Gate per requirement, no open `[NEEDS CLARIFICATION]`) | adversary: ambiguity, untestable rows, missing edge cases (sonnet) | none |
| P1b contracts | main session (design), implementer writes schemas and fixtures | `contract lint`, `contract graph` | adversary: missing fields, ambiguity, hidden coupling (sonnet) | none |
| P2 freeze | none | `gate check` (approval hash equals spec and contracts hashes) | reviewer (opus, critical) | typed approval captured, hash-bound |
| P3 red | test-author (sonnet) | `tdd lock`; tests fail for the right reason; `[red]` commit | adversary: oracle independence, clause coverage (sonnet) | none |
| P4 green | implementer (sonnet) | `tdd check` (locked unchanged, no new skip, assertions not fewer), tests, lint, types, `trace` | adversary two-stage: spec compliance then quality (opus at the build gate) | none |
| P5 verify | runner (haiku) | thresholds (coverage `fail_under`, patch coverage, mutation `break` where available), `report check` | adversary reproduces every load-bearing claim at the reviewed commit (sonnet) | none |
| P6 promote | runner | CI required non-skippable job `harness-gates`; `tdd check --replay` | reviewer (opus) for release | merge approval per repository rules |
| P7 lessons | main session | `LESSONS.md` entry exists for the unit | none | none |

Gate evidence: one file per gate in `specs/<feature>/evidence/<gate>.md` with a fixed schema (verdict PASS, FAIL
or PASS-WITH-FIXES; commands with output; findings table; waivers requested). `gate check` refuses a passed gate
without a valid evidence file, a gate passed out of order, or a waiver without a dated human line.

## Consequences

- The layout above is the contract between delivery units: each unit depends on the frozen data contracts and
  this layout only, never on another unit's code.
- A unit that changes the layout or the CLI contract supersedes this record with a new one.
- Install channels (plugin marketplace, npx from GitHub, project template) are goals of the layout; none is
  available before the first release.
