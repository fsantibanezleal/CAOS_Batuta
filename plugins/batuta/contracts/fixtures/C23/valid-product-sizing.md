# Sizing: Telemetry alert triage

## Problem
A service reads equipment telemetry files, raises alerts, and shows them to operators in a web page with the
provenance of every value. Done: alerts are ingested, scored, served by an HTTP API and shown in the page, and the
page says which values come from a provider instead of the real source.

## Executive brief
- Initiative: reduce missed equipment alerts by 40 percent for plant operators (https://example.org/study-2026).
- Outcomes: operators see every alert with its provenance within one minute of arrival.
- Positioning: a small service for teams that run telemetry fleets without a monitoring suite.
- Credibility: built from the maintainers' own incident reviews and a recorded fleet sample.

## ADR constraints
- ADR-0080 (contract-first parallel delivery): no deviation.
- ADR-0057 (product repository archetype): no deviation.

## Repositories
- alert-triage: the product repository; branch policy task/<slug> to develop to main.

## Components
- ingest-pipeline (alert-triage): reads telemetry files and writes alert events.
- alerts-api (alert-triage): serves alerts over HTTP.
- ops-ui (alert-triage): the operator page.
- severity-model (alert-triage): scores the severity of an alert, baseline first.

## Modules and functions

| Module | Responsibility | Owner unit | Size estimate |
|---|---|---|---|
| pipeline/ingest.py | read telemetry files and emit alert events | u-pipeline | 6 functions |
| api/routes.py | serve alerts and their provenance | u-api | 8 functions |
| ui/src/AlertList.tsx | render alerts with a provider label | u-ui | 4 components |
| models/severity.py | score severity; the baseline runs without a trained bundle | u-model | 5 functions |

## Boundaries

| ID | Producer | Consumer | Contract ID |
|---|---|---|---|
| B1 | ingest-pipeline | alerts-api | alert-event |
| B2 | alerts-api | ops-ui | alert-list |
| B3 | severity-model | ingest-pipeline | severity-score |

## Technology matrix

Verified on primary sources, never from memory.

| Tool | Version | Primary source URL | Verified date |
|---|---|---|---|
| Python | 3.13.1 | https://docs.python.org/3.13/ | 2026-10-12 |
| FastAPI | 0.115.2 | https://fastapi.tiangolo.com/ | 2026-10-12 |
| React | 18.3.1 | https://react.dev/ | 2026-10-12 |

## Machine limits
Preflight output for the target machine: 64 GB RAM, 500 GB free on the data drive, no GPU needed for the
baseline model. Telemetry batches are capped at 200 MB.

## Parallel units

| Unit | Write scope | Depends on contract ids |
|---|---|---|
| u-pipeline | pipeline/, tests/pipeline/ | severity-score |
| u-api | api/, tests/api/ | alert-event |
| u-ui | ui/ | alert-list |
| u-model | models/, tests/models/ | none |

## Integrator and merge order
The main session merges. Order: u-model, u-pipeline, u-api, u-ui, because each later unit reads the contract the
earlier one produces.

## Reservations
none
