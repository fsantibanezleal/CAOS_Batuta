# Brief: {{title}}

- id: {{id}}
- agent: {{agent}}
- kind: {{kind}}
- model: {{model}} (<fill: why this model, per the role table of the configuration>)
- working directory: <fill: absolute path of the worktree or checkout the agent works in>
- write scope: <fill: read-only, or the exact files and folders the agent may change>
- budget: <fill: expected size, for example about 30 turns; the agent stops and reports past it>
- report: {{report}}
{{#sizing}}- sizing: {{sizing}}
{{/sizing}}- serves: <fill: the task or issue this delegation is part of>

Launch with: `Agent(subagent_type="{{agent}}", model="{{model}}")`, the whole brief as the prompt.

## Goal
<fill: one sentence: the question this answers or the change this makes>

## Context and background
<fill: why this unit exists, the plan or issue it belongs to, what it connects to upstream and downstream, decisions already taken. The agent has not seen the conversation.>

## Definitions
<fill: terms, data shapes, units, invariants and conventions the work relies on, with file references, not recalled from memory. Write "None." for a plain lookup or run.>
{{#cpd}}
## ADR constraints
<fill: ADR ids that constrain this unit, and the amendment proposal if one must change; write "None." if no ADR applies>

## Sizing reference
<fill: the unit id and row of the sizing document this unit implements; write "None." only for a unit outside any product>

## Contracts
<fill: consumed and produced contracts, each with name, version, file, owner and the contract test on this side>

## Invariants and edge cases
<fill: empty sets, limits, paging, units, ordering, encoding the unit must handle>

## Missing-data behavior
<fill: what this unit does when an input is absent or late, and the provider it uses meanwhile>

## Environment and limits
<fill: versions verified on a primary source with date; measured limits or the preflight output>

## Owner prerequisites
<fill: none, or each item with its probe command and status>

## Shared files
<fill: none, or the fragment paths this unit writes instead of shared files>

A changelog fragment `changes/<unit-id>.md` holds bullet lines only (`- ...`, continuation lines indented), no
headings. A dictionary fragment repeats the dictionary header or none. A unit never edits the shared changelog or
dictionaries itself.
{{/cpd}}

## Spec
<fill: for implement and docs: the behavior, interfaces, edge cases and the sources to transcribe from. For lookup, run, review and research: what exactly to find, run, review or establish.>

## Out of scope
<fill: what the agent must not touch or decide>
{{#cpd}}

## Must refute
<fill: claims the reviewer must try to break, for example empty set, limit, order, secret present, restart>

## Production-path check
<fill: the exact command run on the real path (same inputs, secrets, volume, restart for long jobs), or "None." with the reason>
{{/cpd}}

## Deliverables
- D1: <fill: one checkable outcome>

## Checks
{{#cpd}}
- C1: <fill: a backticked command with its expected result>
{{/cpd}}
{{^cpd}}
- C1: <fill: an acceptance criterion as a runnable check: a command with its expected result, or a criterion a reader can verify>
{{/cpd}}

## Report layout
Write the report with the Write tool to the `report` path above, in English, with no em-dash and no emoji:

1. A short summary of what was found or changed.
2. One section per deliverable, headed `## D1 ...`, with its evidence: paths with line numbers, commands with their output, URLs.
{{#cpd}}
3. A `## Red run` section (the failing tests before the code exists: each command with its exit code, non-zero) and then a `## Green run` section (the same checks after: each command with its exit code 0). Red comes first. Kind implement only.
4. A `## Production path` section with the command run on the real path and its output, when the Production-path check above is not "None.".
5. A `## Completeness` table with one row per deliverable, status DONE, PARTIAL or BLOCKED:
{{/cpd}}
{{^cpd}}
3. For research and docs work: a `## Sources` section listing every URL or source file used. Anything not confirmed on a primary source is marked UNVERIFIED with what was searched; never fill a gap from memory.
4. A `## Completeness` table with one row per deliverable, status DONE, PARTIAL or BLOCKED:
{{/cpd}}

| ID | Status | Evidence |
|---|---|---|
| D1 | DONE | where the evidence is (for PARTIAL or BLOCKED: exactly what is missing and why) |

Before finishing, run the checker and fix the report until it exits 0 (complete) or 2 (honest PARTIAL or BLOCKED rows):

    "{{python}}" "{{batuta}}" report check --brief "{{brief}}"

## Hard constraints
- Stay inside the write scope. Never push, merge, deploy, publish or touch credentials unless a deliverable says so.
- Temporary files only under `{{temp_root}}/{{id}}`; delete them before finishing unless a deliverable keeps them.
- Never switch branches or stash in a shared checkout; never write into another session's worktree.
- An open design question comes back as a question (a BLOCKED row), never as a silent choice.

## Return message
Under 250 words: the status of each deliverable and any blocker, then these two lines exactly:

BRIEF: {{brief}}
REPORT: {{report}}
