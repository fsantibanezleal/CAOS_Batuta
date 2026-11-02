<!-- why: the states are the six of ADR-0080 section 3; synthetic is not one -->
<!-- expect: write each state as -->
# Contract catalog: Telemetry alert triage

| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io | swap test | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| alert-event | 1.0.0 | u-pipeline | docs/contracts/alert-event.schema.json | docs/contracts/examples/alert-event.json | tests/contracts/test_alert_producer.py::test_schema | tests/contracts/test_alert_consumer.py::test_schema | available: the real event is used (test: tests/contracts/test_alert_consumer.py::test_available); synthetic: show invented numbers (test: tests/contracts/test_alert_consumer.py::test_synthetic) | fixture:tests/fixtures/alert-event.json | - | tests/contracts/test_alert_swap.py | active |
