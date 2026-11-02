<!-- why: waves start at 2: wave 0 is the contracts and wave 1 the walking skeleton -->
<!-- expect: /Wave -->
# Tasks

| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |
|---|---|---|---|---|---|---|---|
| T-001 | Ingest telemetry files | REQ-ING-001 | alert-event, severity-score | - | 1 | implementer | u-pipeline |
| T-002 | Serve alerts | REQ-API-001, REQ-API-002 | alert-event | - | 2 | implementer | u-api |
| T-003 | Alert list page | REQ-UI-001 | alert-list | T-002 | | implementer | u-ui |
