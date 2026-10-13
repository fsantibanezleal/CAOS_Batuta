<!-- why: the swap test column is required -->
<!-- expect: swap test -->
# Contract catalog: Telemetry alert triage

| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider |
|---|---|---|---|---|---|---|---|---|
| alert-event | 1.0.0 | u-pipeline | docs/contracts/alert-event.schema.json | docs/contracts/examples/alert-event.json | tests/contracts/test_alert_producer.py | tests/contracts/test_alert_consumer.py | available: use the real producer (test: tests/contracts/test_alert_consumer.py::test_available); missing: drop the event (test: tests/contracts/test_alert_consumer.py::test_missing) | stub:tests/stubs/alert.py |
