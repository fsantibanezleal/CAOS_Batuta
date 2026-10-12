<!-- why: test paths are repository-relative -->
<!-- expect: is not a POSIX relative path -->
# Contract catalog: Telemetry alert triage

| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io | swap test | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| alert-event | 1.0.0 | u-pipeline | docs/contracts/alert-event.schema.json | docs/contracts/examples/alert-event.json | tests/contracts/test_alert_producer.py::test_schema | tests/contracts/test_alert_consumer.py::test_schema | drop the event, log a warning, show "no data" | fixture:tests/fixtures/alert-event.json | - | /work/test_alert_swap.py | active |
