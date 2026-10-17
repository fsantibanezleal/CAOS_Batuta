# Agentic orchestration on a device: procedures

Read when: delegating work to an agent, writing a brief, accepting an agent's report, checking or restoring the
device's agent setup, or changing what loads at session start.

The routing rule is in the always-loaded core; this file holds the procedures. `{{python}}` is the interpreter and
`{{deploy_root}}` the folder this device's rendered files live in.

## Why
Every subagent that inherits the strongest model exhausts the subscription limit. Reasoning stays in the main
session (research synthesis, plans, design decisions, specs, acceptance criteria); implementation of a validated
plan is delegated, spec-driven and test-driven. The main session's hard task is the brief: context and background,
definitions, the spec with what is out of scope, acceptance criteria as runnable checks (tests first), and the scope
(working directory, branch, files, budget, report path and format). The model is chosen on purpose at every launch
and re-evaluated at each step.

## Scripts, briefs, cost
1. Scripts before agents: deterministic work that recurs becomes ONE parameterized, tested script in the
   repository's `tools/` or `scripts/` (dry run by default, honest exit codes), never a hand-run sequence and never
   a copy per release.
2. Every delegation has a brief and a checked report: create the brief with the harness, lint it before the launch;
   the launch names the brief and sets the model; the report is accepted only after the report check passes and the
   load-bearing claims are re-checked. A partial or blocked row stays partial or blocked in the reply.
3. A failed agent is not relaunched by default: assume the loss and decide.
4. Cost gate: many agents at once, many in one task, more than one strongest-model reviewer, or a run of hours: state
   agents, models and expected duration and wait for approval.
5. Multi-hour work, or work that must survive the subscription limit, goes through an external orchestrator run
   by hand and bounded in time; training and heavy jobs run as external monitored processes.

## Context budget
6. What loads at every session start (the rendered user core, the project CLAUDE.md chain, unscoped rules and each
   project's memory index) is measured by `batuta context check` against the budgets in `batuta.json`. Over budget
   fails the check; move detail into a reference file, a path-scoped rule or a memory topic page, never raise the
   budget. `batuta context measure` prints the breakdown; `batuta memory index` regenerates a memory index.

## How a change reaches the device
7. Edit the template and the reference files, never the rendered output; render with `batuta context render`, then
   check. Commit the sources so every device can render the same files.
