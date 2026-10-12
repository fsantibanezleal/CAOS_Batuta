<!-- why: a row without evidence is refused -->
<!-- expect: /Evidence -->
# Report: alert ingest API

## Summary
Added GET /alerts and GET /alerts/{id}; both validate against the alert-list contract. 12 tests pass.

## D1 GET /alerts and GET /alerts/{id}
api/routes.py:14 serves the list, api/routes.py:41 serves one alert; tests/api/test_routes.py covers the four edge cases.

## Red run
`python -m unittest discover -s tests/api` exit code 1: 12 tests failed with ImportError before api/routes.py existed.

## Green run
`python -m unittest discover -s tests/api` exit code 0: 12 tests, OK.

## Production path
`python -m api.serve --check` against the real telemetry sample: exit code 0, 3 alerts served.

## Completeness

| ID | Status | Evidence |
|---|---|---|
| D1 | DONE | - |
