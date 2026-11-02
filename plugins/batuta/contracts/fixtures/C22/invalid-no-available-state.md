<!-- why: the 'available' state is declared -->
<!-- expect: declare the 'available' state -->
# Contract catalog: Telemetry alert triage

| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io | swap test | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| alert-event | 1.0.0 | u-pipeline | docs/contracts/alert-event.schema.json | docs/contracts/examples/alert-event.json | tests/contracts/test_alert_producer.py::test_schema | tests/contracts/test_alert_consumer.py::test_schema | missing: drop the event and show "no data" (test: tests/contracts/test_alert_consumer.py::test_missing); stale: show the cached snapshot (test: tests/contracts/test_alert_consumer.py::test_stale) | fixture:tests/fixtures/alert-event.json | - | tests/contracts/test_alert_swap.py | active |
