<!-- why: a provider state names its provenance kind: provider(stub|simulator|fixture|baseline) -->
<!-- expect: provider(stub|simulator|fixture|baseline) -->
# Contract catalog: Telemetry alert triage

| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io | swap test | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| alert-event | 1.0.0 | u-pipeline | docs/contracts/alert-event.schema.json | docs/contracts/examples/alert-event.json | tests/contracts/test_alert_producer.py::test_schema | tests/contracts/test_alert_consumer.py::test_schema | available: the real event is used (test: tests/contracts/test_alert_consumer.py::test_available); provider: show the fixture (test: tests/contracts/test_alert_consumer.py::test_provider) | fixture:tests/fixtures/alert-event.json | - | tests/contracts/test_alert_swap.py | active |
