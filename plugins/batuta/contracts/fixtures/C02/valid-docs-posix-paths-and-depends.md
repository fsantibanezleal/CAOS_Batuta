# Brief: Document the alert API

- id: api-guide-2026-10-12
- agent: doc-writer
- kind: docs
- model: sonnet (routine documentation)
- working directory: C:/work/alert-triage-api
- write scope: docs/guide/, docs/README.md
- budget: about 25 turns
- depends: alert-event, alert-list, C02
- report: /work/reports/api-guide-2026-10-12.md
- serves: alert-triage#12

Launch with: `Agent(subagent_type="searcher", model="haiku")`, the whole brief as the prompt.

## Goal
Find every HTTP endpoint the alert code defines.

## Context and background
A first inventory before sizing the API unit; no decisions taken yet.

## Definitions
None.

## Spec
List each route with its file and line; do not change any file.

## Out of scope
Any change to the code.

## Deliverables
- D1: GET /alerts and GET /alerts/{id} answer as the alert-list contract says, with tests for the four edge cases.

## Checks
- C1: `python -m unittest discover -s tests/api` passes (exit code 0).

## Report layout
Write the report with the Write tool to the `report` path above, in English, with no em-dash and no emoji:

1. A short summary of what was found or changed.
2. One section per deliverable, headed `## D1 ...`, with its evidence: paths with line numbers, commands with their output, URLs.
3. For research and docs work: a `## Sources` section listing every URL or source file used. Anything not confirmed on a primary source is marked UNVERIFIED with what was searched; never fill a gap from memory.
4. A `## Completeness` table with one row per deliverable, status DONE, PARTIAL or BLOCKED:

| ID | Status | Evidence |
|---|---|---|
| D1 | DONE | where the evidence is (for PARTIAL or BLOCKED: exactly what is missing and why) |

Before finishing, run the checker and fix the report until it exits 0 (complete) or 2 (honest PARTIAL or BLOCKED rows):

    "C:/tools/python/python.exe" "C:/tools/agents/check_report.py" --brief "/work/briefs/api-guide-2026-10-12.brief.md"

## Hard constraints
- Stay inside the write scope. Never push, merge, deploy, publish (Zenodo, PyPI, npm) or touch credentials unless a deliverable says so.
- Temporary files only under `C:/work/_Temp/api-guide-2026-10-12`; delete them before finishing unless a deliverable keeps them.
- Never switch branches or stash in a shared checkout; never write into another session's worktree.
- An open design question comes back as a question (a BLOCKED row), never as a silent choice.

## Return message
Under 250 words: the status of each deliverable and any blocker, then these two lines exactly:

BRIEF: /work/briefs/api-guide-2026-10-12.brief.md
REPORT: /work/reports/api-guide-2026-10-12.md
