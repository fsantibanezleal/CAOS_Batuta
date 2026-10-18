# Routing: a script, a named agent on an explicit model, or the main session

Every task is routed before it starts. The user chooses the model and the reasoning effort of the main session; everything
below it is governed. Routing answers three questions in order: does a script already do this, is it a bounded reading or
judgment a named agent can do on a cheaper model, or does it need the main session?

## The order

1. A script already does it: run it.
2. It is deterministic and recurring: write or extend one parameterized, tested script, never a hand-run sequence.
3. It is a bounded reading, run, implementation, test, doc or independent check: launch a named agent on the model its
   role names, with the model set explicitly on the launch.
4. Otherwise the main session: reasoning, plans, specs, integration and verification.

The `route` skill prints this order in a session; `route show` prints the role table from the configuration and
`route check` verifies the agent files against it.

## The role table

The defaults are the built-in configuration of `batuta_lib/config.py` (read by `route show`) and the shipped agent files
in `plugins/batuta/agents/`. A project overrides the models and efforts in `batuta.json` (`roles`, see the
[configuration reference](../reference/configuration.md)).

| Role | Model | Effort | Does | Tools it may use |
|---|---|---|---|---|
| `searcher` | haiku | low | read-only lookups with `path:line` answers; use it instead of the built-in Explore agent | Read, Grep, Glob, Bash, PowerShell, WebFetch, Write (its report) |
| `runner` | haiku | low | runs the commands it is given with bounded waits and reports exit codes and output verbatim | Read, Grep, Glob, Bash, PowerShell, Monitor, Write (its report) |
| `implementer` | sonnet | medium | implements one scoped unit test-first inside the worktree its brief assigns | the default set, no Agent tool |
| `test-author` | sonnet | medium | writes the failing tests of one task before any implementation exists | Read, Grep, Glob, Bash, Write, Edit |
| `doc-writer` | sonnet | medium | transcribes documentation from persisted sources only | the default set, no Agent tool |
| `adversary` | sonnet | high | independent check of one routine gate; writes exactly one evidence file | Read, Grep, Glob, Bash, Write; Edit and NotebookEdit disallowed |
| `reviewer` | opus | high | adversarial review for critical gates and security- or correctness-critical work; read-only | Read, Grep, Glob, Bash, PowerShell, WebFetch, WebSearch, Write; Edit, NotebookEdit and Agent disallowed |

The two haiku roles carry `omitClaudeMd: true` (requirement ROUTE-5): they do not load CLAUDE.md, because their brief
carries the context. `route check` fails when an agent file does not satisfy contract C18, when its `model` differs from
the model of the role of the same name, or when a role that runs on haiku lacks `omitClaudeMd: true`.

Why this roster: Anthropic documents `sonnet` for daily coding, `opus` for complex reasoning and `haiku` for simple tasks
(https://code.claude.com/docs/en/model-config), and the costs page says to "reserve Opus for complex architectural
decisions or multi-step reasoning" (https://code.claude.com/docs/en/costs). The roster is small on purpose: combined agent
descriptions over 15,000 tokens trigger a startup warning (https://code.claude.com/docs/en/sub-agents), and large catalogs
loaded by default raise context cost (the wshobson/agents catalog has 202 agents, https://github.com/wshobson/agents;
landscape research, section 1).

## How the model is chosen

Claude Code resolves a subagent's model in this order: the per-call `model` parameter, then the agent definition's `model`
field, then `CLAUDE_CODE_SUBAGENT_MODEL`, then the session model (https://code.claude.com/docs/en/sub-agents; the order
changed in v2.1.251, before which the environment variable came first). Batuta's rule that every launch names a model
therefore always wins; the agent files and the preset's `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` are the fallbacks. An
escalation to a stronger model is a decision stated in the brief (`brief lint` warns about it), never a default.

The reasoning effort of the main session is the user's: on Opus 5.5 it is set with `modelSettings` or
`CLAUDE_CODE_EFFORT_LEVEL`, because that model ignores a top-level `effortLevel` in user settings
(https://code.claude.com/docs/en/model-config).

## Guardrails that make routing real

The settings preset (`templates/presets/base.json`), applied by `device restore` and `init user`, turns the routing rules
into permission rules instead of prose:

| Setting | Effect | Requirement |
|---|---|---|
| `permissions.deny: Agent(Explore)`, `Agent(Plan)` | the built-in agents that run on the session model are not used; `searcher` replaces Explore | ROUTE-3 |
| `permissions.deny: Agent(model:fable)` | no Fable subagent | ROUTE-2 |
| `permissions.ask: Agent(model:opus)` | an Opus subagent needs confirmation | ROUTE-2 |
| `env.CLAUDE_CODE_SUBAGENT_MODEL=sonnet` | the fallback model of a launch that names none | none (a default of the preset) |
| `env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, `env.CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` | spawn depth and concurrency from `caps` (defaults 1 and 4) | ROUTE-4 |

Two limits are documented and stay: a call that omits `model` is never matched by `Agent(model:opus)`, so an Opus
inheritance from the session is invisible to that rule (permissions documentation,
https://code.claude.com/docs/en/permissions); and a plugin cannot carry `env`, permissions or a CLAUDE.md
(https://code.claude.com/docs/en/plugins/components), which is why these settings reach a machine through the
device channel and not through the plugin install. See [devices and portability](devices-and-portability.md).

A PreToolUse hook closes part of the first gap: `guard-require-brief` inspects the `Agent` call and denies (or asks about,
per `guards.require_brief`) a launch whose prompt does not name a brief that satisfies contract C02. It continues on an
internal error, because it is a delegation discipline check and not a safety boundary (see the
[enforcement matrix](../reference/enforcement-matrix.md)).

## Caps

`caps` in `batuta.json` bounds delegation: `max_concurrent_agents` (4), `max_agents_per_task` (8),
`max_opus_reviews_per_task` (1), `spawn_depth` (1) and, for the lanes that bill, `max_cost_usd_per_task`. The platform's
own defaults are looser (nesting up to three layers, 20 concurrent subagents; https://code.claude.com/docs/en/sub-agents),
so the limits are set by Batuta. The reason for the fan-out limits is the cost evidence in [principles](principles.md),
principle 3.

## What stays in the main session

Reasoning, plans, specs, integration and the re-check of any report. Anthropic's orchestrator-worker pattern is "a central
LLM dynamically breaks down tasks, delegates them to worker LLMs, and synthesizes their results"
(https://www.anthropic.com/engineering/building-effective-agents, December 19, 2024); Batuta adds a checked report and an
independent evaluator, the evaluator-optimizer pattern of the same post. The brief and the report are described in
[briefs, reports and the ledger](briefs-reports-ledger.md).

## Sources

- Design: software design document sections 2 (principle 3), 3.2 and 4 (ROUTE-1 to ROUTE-5); `plugins/batuta/agents/*.md`;
  `plugins/batuta/templates/presets/base.json`; `batuta_lib/config.py`.
- https://code.claude.com/docs/en/sub-agents, /model-config, /costs, /permissions, /plugins
- https://www.anthropic.com/engineering/building-effective-agents
- https://github.com/wshobson/agents (catalog size, landscape research)
