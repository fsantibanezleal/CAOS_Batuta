<!-- why: Contracts holds catalog ids, not file paths -->
<!-- expect: /Contracts -->
# Tasks

| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |
|---|---|---|---|---|---|---|---|
| T-001 | Ingest telemetry files | REQ-ING-001 | docs/contracts/alert-event.schema.json | - | 3 | implementer | u-pipeline |
| T-002 | Serve alerts | REQ-API-001, REQ-API-002 | alert-event | - | 2 | implementer | u-api |
| T-003 | Alert list page | REQ-UI-001 | alert-list | T-002 | | implementer | u-ui |
