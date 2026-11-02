# Delegating a unit

A unit of work goes to a named agent through a brief, runs on a lane, comes back as a report, and is accepted only after a
script and the main session have both checked it. This guide runs the loop on a small documentation unit. Output is real,
captured in the scratch project of the [first project walkthrough](first-project.md); the scratch folder's absolute path is
shown as `<project>`. In the transcripts `batuta` stands for `python <plugin folder>/scripts/batuta.py`. The concepts behind
each step are in [briefs, reports and the ledger](../concepts/briefs-reports-ledger.md), [routing](../concepts/routing.md)
and [dispatch lanes](../concepts/dispatch-lanes.md).

## 1. Pick the role

Run `batuta route show` (or the `route` skill) and choose by the order: a script, then a named agent, then the main session.
The default table:

```
OK role searcher: model=haiku effort=low omit_claude_md=true
OK role runner: model=haiku effort=low omit_claude_md=true
OK role implementer: model=sonnet effort=medium omit_claude_md=false
OK role test-author: model=sonnet effort=medium omit_claude_md=false
OK role doc-writer: model=sonnet effort=medium omit_claude_md=false
OK role adversary: model=sonnet effort=high omit_claude_md=false
OK role reviewer: model=opus effort=high omit_claude_md=false
7 role(s)
```

This unit writes a documentation page from a frozen spec, so the role is `doc-writer` on sonnet.

## 2. Write the brief

`brief new` creates the brief and its ledger row at once (the brief starts with a status of `drafted`):

```
batuta brief new --slug greet-docs --topic docs --agent doc-writer --title "Document the greeter"
NEW brief docs-2026-10-16 (<project>/.batuta/delegation/docs-2026-10-16.brief.md)
OK the report goes to <project>/.batuta/delegation/docs-2026-10-16.report.md (<project>/.batuta/delegation/docs-2026-10-16.report.md)
CHANGED ledger row added (<project>/.batuta/delegation/ledger.md)
OK next: fill every <fill: ...> slot, then run: brief lint <brief>
brief docs-2026-10-16 written
```

The model and the kind come from the agent file (`doc-writer`: sonnet, kind `docs`). The ledger row is:

```
| ID | Agent | Model | Brief | Report | Status | Accepted |
|---|---|---|---|---|---|---|
| docs-2026-10-16 | doc-writer | sonnet | .batuta/delegation/docs-2026-10-16.brief.md | .batuta/delegation/docs-2026-10-16.report.md | drafted | no |
```

The brief is the agent's complete instruction set, because it has not seen the conversation. Fill every slot: the goal; the
context; the definitions the work relies on, with file references; the spec (for a documentation unit, the sources to
transcribe from, never memory); what is out of scope; numbered deliverables (`D1`, ...); checks (`C1`, ...), each with a
backticked command and its expected result; the working directory, the exact write scope and the budget. Lint until it
passes:

```
batuta brief lint .batuta/delegation/docs-2026-10-16.brief.md
FAIL 12 template slot(s) not filled, first: <fill: why this model, per the role table of the configuration> (...)
FAIL placeholder text matching '(?i)<fill\b[^>]*>' on line 6 (...)
LINT FAILED: .batuta/delegation/docs-2026-10-16.brief.md

(after filling the slots)
OK brief passes the lint (.batuta/delegation/docs-2026-10-16.brief.md)
LINT OK: .batuta/delegation/docs-2026-10-16.brief.md
```

For an `implement`, `job` or `skeleton` brief add the contract-first sections: the contracts the unit produces and consumes,
its invariants, the missing-data behavior and the environment. Never launch an agent on a brief that has not passed lint. A
warning (exit 2) about an escalation, the `fable` model, more than eight deliverables or an overlapping write scope is a
decision for you: resolve it, or write the reason into the brief.

## 3. Plan the lane and launch

```
batuta dispatch plan --brief .batuta/delegation/docs-2026-10-16.brief.md --lane subagent
OK lane subagent, model sonnet, role doc-writer, run docs-2026-10-16
NEW dispatch request written (<project>/.batuta/delegation/docs-2026-10-16.dispatch-request.json)
planned docs-2026-10-16 on subagent
```

The request (contract C30) is a small JSON file: `run_id`, `brief`, `report`, `lane`, `role`, `model`, the `write_scope`
(here `["docs/greeter.md"]`), `max_turns` (here 10), `timeout_s` (3600) and `effort`. A dry run of `dispatch run` shows what the
`subagent` lane prepares; it never launches anything:

```
batuta dispatch run --request .batuta/delegation/docs-2026-10-16.dispatch-request.json
OK launch specification for the main session (not launched): {"lane": "subagent", "tool": "Agent", "subagent_type": "doc-writer", "model": "sonnet", "description": "Run the brief docs-2026-10-16", "prompt": "Your brief is the file .batuta/delegation/docs-2026-10-16.brief.md. Read it in full first; it is your complete instruction set. Write your report to .batuta/delegation/docs-2026-10-16.report.md and finish with the report layout the brief sets.", "run_in_background": true, "launched": false, "note": "Nothing was launched: the main session starts this subagent with the Agent tool, in the background, and checks the report with `report check` before accepting it."}
OK dry run: nothing was written; add --apply to write the pending result
docs-2026-10-16 on subagent: specification only
```

The main session then calls the Agent tool with the specification: `subagent_type` of the plugin's agent (`batuta:doc-writer`),
`model: sonnet` set explicitly, the prompt naming the brief path. An explicit model on every launch always wins over the agent
file and the environment fallback, and the guard `guard-require-brief` refuses a launch whose prompt does not name a valid
brief. For long units that must not use the subscription use the `sdk` lane, and for another model family a `provider:NAME`
lane: [adding a provider](adding-a-provider.md).

## 4. What the agent does, and the stop hook

The agent reads the brief, works inside its write scope, and writes its report in the layout the brief sets, ending with a
Completeness table (DONE, PARTIAL or BLOCKED per deliverable). It runs `report check` on its own report before it stops. If
it stops with a missing or defective report, the `subagent-stop` hook holds it once; on the second attempt the hook lets it
stop and logs a dated UNVERIFIED line to `<coordination root>/delegation/unverified.log`, so it never loops.

## 5. Check the report and accept it

```
batuta report check --brief .batuta/delegation/docs-2026-10-16.brief.md
FAIL report not found or unreadable: <project>/.batuta/delegation/docs-2026-10-16.report.md (FileNotFoundError) (...)
DEFECTIVE: 0/1 deliverables DONE (1 problems, 0 open) [<project>/.batuta/delegation/docs-2026-10-16.report.md]
```

That was before the agent wrote anything (exit 1). With a complete report (here written by hand as a stand-in, to show the
checker):

```
batuta report check --brief .batuta/delegation/docs-2026-10-16.brief.md
OK complete: every deliverable is DONE with evidence (<project>/.batuta/delegation/docs-2026-10-16.report.md)
COMPLETE: 1/1 deliverables DONE (0 problems, 0 open) [<project>/.batuta/delegation/docs-2026-10-16.report.md]

batuta report ledger-status --write
OK docs-2026-10-16 drafted to complete: 1/1 DONE
CHANGED 1 status value(s) written (<project>/.batuta/delegation/ledger.md)
OK not yet accepted by the parent: docs-2026-10-16
1 row(s)
```

Exit 0 is complete, 1 is defective (send it back or fix the brief, never accept it) and 2 is an honest PARTIAL or BLOCKED:
record it as such and decide the next step; a PARTIAL stays partial, and a failed agent is not relaunched by default.

The ledger row says `complete` and `Accepted: no`. Acceptance is yours: re-run one or two of the report's load-bearing
commands in the main session, read the changed files, and only then set `Accepted: yes` with the evidence in the Notes column.
A claim without a command and its output is not evidence. For the independent check of a lifecycle gate, use the `verify`
skill, which launches the adversary (or the reviewer for a critical gate) on its own brief.

## When the check fails

| Symptom | Meaning | What to do |
|---|---|---|
| `brief lint` exit 1 | an unfilled slot, a missing section or header field, a check without a command | fill it; never launch on a failing brief |
| `brief lint` exit 2 | an escalation, `fable`, more than eight deliverables or an overlapping write scope | resolve it or write the reason into the brief |
| `dispatch plan` REFUSED, cost or price | a billed lane with no cap or no verified price | set `caps.max_cost_usd_per_task` or `--max-cost`; a missing price is a decision for you ([dispatch lanes](../concepts/dispatch-lanes.md)) |
| `report check` exit 1 | a missing report, a placeholder, a missing row or section, no evidence | send it back once; do not accept |
| `report check` exit 2 | some rows PARTIAL or BLOCKED | record it honestly; the open items become a new unit |
| the ledger shows `incomplete`, `defective`, `timeout`, `error` or `over-budget` | a machine state from the hook or the dispatch area | read the report or the dispatch result next to it |

## Sources

- The `route`, `brief`, `report` and `dispatch` area fragments, summarized in the [command reference](../reference/cli.md);
  contracts C02, C03, C04, C30; `plugins/batuta/skills/brief/SKILL.md`, `delegate/SKILL.md` and `verify/SKILL.md`.
- https://code.claude.com/docs/en/sub-agents for the model resolution order and the Agent tool.
- All output on this page was captured from `batuta.py` in a scratch project (see the first project walkthrough).
