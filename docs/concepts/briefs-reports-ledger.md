# Briefs, reports and the ledger

A delegation is a brief in, a report out, and a row in a ledger that says how it ended. The agent has not seen the
conversation, so the brief is its complete instruction set; nothing it returns is accepted on its word, because the
report is checked against the brief by a script.

![The delegation loop: brief, plan the lane, launch, agent works, report check, re-check by the main session, ledger and gate. A defective report goes back once.](../assets/delegation-loop.svg)

## The brief (contract C02)

`brief new` writes `<coordination_root>/delegation/<id>.brief.md` from the template and adds a ledger row. The header is a
list of metadata bullets under the title (the keys are read case-insensitively):

| Key | Meaning |
|---|---|
| `id` | `<topic>-<date>`, lower case, for example `docs-2026-10-16` |
| `agent` | one of the agents of the plugin or `general-purpose` |
| `kind` | `implement`, `job`, `skeleton`, `docs`, `review`, `research`, `lookup` or `run` (defaults from the agent) |
| `model` | the model, with the reason when it differs from the role table |
| `working directory`, `write scope`, `budget`, `report`, `serves` | where the agent works, the exact files it may change (or read-only), its size limit, the report path and the task it belongs to |

The sections are Goal, Context and background, Definitions, Spec, Out of scope, Deliverables (`D1`, `D2`, ...), Checks
(`C1`, `C2`, ...), Report layout, Hard constraints and Return message. An `implement`, `job` or `skeleton` brief also
carries the contract-first sections: contracts, invariants, missing-data behavior and environment (see
[contract-first parallel development](contract-first-parallel-development.md)). The template follows Anthropic's own list
for a subagent brief, "an objective, an output format, guidance on the tools and sources to use, and clear task
boundaries" (https://www.anthropic.com/engineering/multi-agent-research-system), and the best-practices guidance that a
spec names the files and interfaces involved, states what is out of scope and ends with an end-to-end verification step
(https://code.claude.com/docs/en/best-practices).

`brief lint` refuses (exit 1) a brief with an unfilled `<fill: ...>` slot anywhere, a missing section or header field, or a
check without a backticked command. It warns (exit 2) about an escalation to a stronger model, the `fable` model, more than
eight deliverables, and a write scope that overlaps another open brief in the same ledger.
Real output for a template that was not filled:

```
FAIL 12 template slot(s) not filled, first: <fill: why this model, per the role table of the configuration> (.batuta/delegation/docs-2026-10-16.brief.md)
FAIL placeholder text matching '(?i)<fill\b[^>]*>' on line 6 (.batuta/delegation/docs-2026-10-16.brief.md)
LINT FAILED: .batuta/delegation/docs-2026-10-16.brief.md
```

and for the filled brief: `OK brief passes the lint`.

## Where the brief runs

`dispatch plan --brief BRIEF --lane subagent|sdk|provider:NAME` validates the brief and the lane against the configuration
and writes a C30 request next to the brief. The default lane `subagent` prints a launch specification for the main session,
which then calls the Agent tool with the role's agent and an explicit model; the other lanes are described in
[dispatch lanes and cost caps](dispatch-lanes.md). The brief itself is provider-neutral, and every run returns a report that
passes the same checks.

## The report (contract C03)

The report path is named by the brief. It carries a short summary, one `## D<n>` section per deliverable with its evidence
(paths with line numbers, commands with their output, URLs), a `## Sources` section for research and documentation work
(anything not confirmed on a primary source is marked UNVERIFIED with what was searched), and a `## Completeness` table
with one row per deliverable and the status DONE, PARTIAL or BLOCKED. An implementation report also has a Red run and a
Green run section, and an exit code of zero in a red run is a defect.

`report check --brief BRIEF` reads the report and exits:

| Exit | Meaning |
|---|---|
| 0 | every deliverable is DONE with evidence |
| 1 | the report is defective: a missing row or section, a placeholder, a bad status word, evidence that is only a dash, green before red |
| 2 | well formed, but some rows are PARTIAL or BLOCKED (an honest partial) |

Real output for a report that does not exist, then for a complete one:

```
FAIL report not found or unreadable: <project>/.batuta/delegation/docs-2026-10-16.report.md (FileNotFoundError)
DEFECTIVE: 0/1 deliverables DONE (1 problems, 0 open) [<project>/.batuta/delegation/docs-2026-10-16.report.md]

OK complete: every deliverable is DONE with evidence
COMPLETE: 1/1 deliverables DONE (0 problems, 0 open) [<project>/.batuta/delegation/docs-2026-10-16.report.md]
```

(`<project>` replaces the path of the scratch project the output was captured in.) PARTIAL stays partial: a report that
says so honestly is accepted as partial, and a gap is never filled from memory.

## The SubagentStop hook

The plugin's hooks file registers `subagent-stop`. It holds a briefed agent once until its report passes: it blocks
(`decision: block`, exit 0) when the agent's final message lacks the `BRIEF:` and `REPORT:` lines or the report is missing,
defective or incomplete. It allows an agent that was not briefed. On the second attempt it allows the stop and appends a
dated UNVERIFIED line to `<coordination_root>/delegation/unverified.log`, so it never loops; an internal error allows the
stop. The shape follows Anthropic's own guidance for a Stop hook: scripts read `stop_hook_active`, and Claude Code
overrides a Stop hook after eight blocks in a row, so a check that could block forever must not
(https://code.claude.com/docs/en/hooks). For Stop and SubagentStop the check cannot fail closed through `onFailure`, so
the report check returns the block decision itself.

## The ledger (contract C04)

`<coordination_root>/delegation/ledger.md` is one Markdown table per coordination root, the only representation of the
ledger (there is no JSONL). The seven mandatory columns come first and in order:

| Column | Values |
|---|---|
| ID | the brief id |
| Agent, Model | the role and the model it ran on |
| Brief, Report | repository-relative paths |
| Status | `drafted`, `pending`, `launched`, `complete`, `incomplete`, `defective`, `accepted`, `superseded`, `lost`, `timeout`, `error`, `over-budget` |
| Accepted | `yes` or `no` (`y` and `n` are read, never written) |

Optional columns follow in any order: Provider, Tokens in, Tokens out, Cost USD (written by the dispatch area), Superseded
by and Notes. Status holds machine states only; the evidence of an acceptance goes in Notes. Real output of the status
update after a complete report:

```
OK docs-2026-10-16 drafted to complete: 1/1 DONE
CHANGED 1 status value(s) written (.batuta/delegation/ledger.md)
OK not yet accepted by the parent: docs-2026-10-16
```

`report ledger-status` is a dry run unless `--write` is given. Every ledger write is atomic: the new file is written next to
the ledger and replaced in one step under a lock file, the ledger is re-read just before the replace so a row a concurrent
writer added is kept, and a result that does not satisfy C04 is refused with the file untouched. The ledger has one writer,
`delegation.update_ledger`, which the dispatch area also uses.

Accepting is a separate act by the main session, after the check passes and after it re-ran the load-bearing commands
itself. A failed agent is not relaunched by default. The `delegate` skill carries the same procedure.

## Sources

- Design: software design document sections 3.5 and 4 (BRIEF-1, BRIEF-2, REPORT-1) and the decisions on the ledger;
  contracts C02, C03, C04 in `plugins/batuta/contracts/`; `plugins/batuta/templates/brief.md`.
- The fragments of the route, brief and report areas, now summarized in the [command reference](../reference/cli.md);
  `plugins/batuta/skills/brief/SKILL.md` and `plugins/batuta/skills/delegate/SKILL.md`.
- https://www.anthropic.com/engineering/multi-agent-research-system, https://code.claude.com/docs/en/best-practices,
  https://code.claude.com/docs/en/hooks
- The output shown was captured with `batuta.py` in a scratch project (see the [first project guide](../guides/first-project.md)).
