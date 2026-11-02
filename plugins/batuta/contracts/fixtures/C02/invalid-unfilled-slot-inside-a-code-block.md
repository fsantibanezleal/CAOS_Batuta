<!-- why: a slot inside a code block is still refused -->
<!-- expect: placeholder text -->
# Brief: Alert ingest API

- id: ingest-api-2026-10-12
- agent: implementer
- kind: implement
- model: sonnet (a scoped implementation from a precise spec)
- working directory: C:/work/alert-triage-api
- write scope: api/, tests/api/
- budget: about 40 turns; the agent stops and reports past it
- report: C:/work/reports/ingest-api-2026-10-12.md
- sizing: wip/alerts/sizing.md
- serves: alert-triage#12

Launch with: `Agent(subagent_type="implementer", model="sonnet")`, the whole brief as the prompt.

## Goal
Serve the alert list over HTTP from the alert-event contract.

## Context and background
The ingest pipeline writes alert events; the API serves them to the operator page. Decisions taken: FastAPI, JSON responses, no authentication in this unit.

## Definitions
An alert event is a JSON object that satisfies docs/contracts/alert-event.schema.json (version 1.0.0). A provider is the fixture that serves a contract until the real producer exists.
## ADR constraints
ADR-0080 (contract-first parallel delivery). No amendment proposed.

## Sizing reference
Unit u-api of wip/alerts/sizing.md: Write scope api/, tests/api/; depends on alert-event.

## Contracts
Consumed: alert-event 1.0.0 (docs/contracts/alert-event.schema.json, owner u-pipeline, consumer test tests/contracts/test_alert_consumer.py). Produced: alert-list 1.0.0 (docs/contracts/alert-list.schema.json, owner u-api, producer test tests/contracts/test_list_producer.py).

## Invariants and edge cases
An empty alert list answers 200 with an empty array; a page size above 500 is refused with 422; timestamps are UTC.

## Missing-data behavior
When the alert source is absent the API answers 503 with the reason and the page shows "not available yet"; the fixture provider serves meanwhile.

## Environment and limits
Python 3.13.1 and FastAPI 0.115.2 verified 2026-10-12 on their primary sources; the preflight output allows 64 GB of memory.

## Owner prerequisites
None.

## Shared files
None. The changelog line goes in changes/u-api.md.

A changelog fragment `changes/<unit-id>.md` holds bullet lines only (`- ...`, continuation lines indented), no
headings: `fragments.py changelog` refuses anything else. An i18n fragment `i18n/<unit-id>.csv` repeats the
dictionary header or none.

## Spec
Implement GET /alerts with paging and GET /alerts/{id}; validate every response against alert-list; transcribe the field list from the contract file.

## Out of scope
The operator page, authentication, deployment.

## Must refute
Empty list, page size 501, a malformed event in the source, the source file absent.

## Production-path check
`python -m api.serve --check` against the real telemetry sample, exit code 0, with the sample larger than the known maximum.

## Deliverables
- D1: GET /alerts and GET /alerts/{id} answer as the alert-list contract says, with tests for the four edge cases.

## Checks
- C1: `python -m unittest discover -s tests/api` passes (exit code 0).

## Report layout
Write the report with the Write tool to the `report` path above, in English, with no em-dash and no emoji:

1. A short summary of what was found or changed.
2. One section per deliverable, headed `## D1 ...`, with its evidence: paths with line numbers, commands with their output, URLs.
3. A `## Red run` section (the failing tests before the code exists: each command with its exit code, non-zero) and then a `## Green run` section (the same checks after: each command with its exit code 0). Red comes first. Kind implement only.
4. A `## Production path` section with the command run on the real path and its output, when the Production-path check above is not "None.".
5. A `## Completeness` table with one row per deliverable, status DONE, PARTIAL or BLOCKED:

| ID | Status | Evidence |
|---|---|---|
| D1 | DONE | where the evidence is (for PARTIAL or BLOCKED: exactly what is missing and why) |

Before finishing, run the checker and fix the report until it exits 0 (complete) or 2 (honest PARTIAL or BLOCKED rows):

    "C:/tools/python/python.exe" "C:/tools/agents/check_report.py" --brief "C:/work/briefs/ingest-api-2026-10-12.brief.md"

## Hard constraints
- Stay inside the write scope. Never push, merge, deploy, publish (Zenodo, PyPI, npm) or touch credentials unless a deliverable says so.
- Temporary files only under `C:/work/_Temp/ingest-api-2026-10-12`; delete them before finishing unless a deliverable keeps them.
- Never switch branches or stash in a shared checkout; never write into another session's worktree.
- An open design question comes back as a question (a BLOCKED row), never as a silent choice.

## Return message
Under 250 words: the status of each deliverable and any blocker, then these two lines exactly:

BRIEF: C:/work/briefs/ingest-api-2026-10-12.brief.md
REPORT: C:/work/reports/ingest-api-2026-10-12.md

```
<fill: command>
```
