<!-- why: a model slot needs a baseline provider -->
<!-- expect: a model slot (a non-empty model io) needs a baseline provider -->
# Contract catalog: Telemetry alert triage

| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io | swap test | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| severity-score | 1.2.0 | u-model | docs/contracts/severity-score.schema.json | docs/contracts/examples/severity-score.json | tests/contracts/test_severity_producer.py | tests/contracts/test_severity_consumer.py | use the baseline score and label it baseline | fixture:tests/fixtures/severity.json | in: alert-event, out: severity-score | tests/contracts/test_severity_swap.py | active |
