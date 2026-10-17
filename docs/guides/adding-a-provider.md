# Adding a provider lane

A provider lane sends a brief to a model outside Claude Code: any OpenAI-compatible endpoint (OpenAI, Azure OpenAI, vLLM, a
LiteLLM gateway, Ollama), Google Gemini, or Claude on Amazon Bedrock or Google Vertex. It makes one tool-less call and returns a
report and an optional patch, which the main session applies only after the gates pass. Use it for cross-model work, cheaper or
local models for lookups, and a second-opinion adversary from a different model family. The design, the cost rules and the
limits are in [dispatch lanes and cost caps](../concepts/dispatch-lanes.md). This guide adds a provider of an existing kind
(part 1) and then describes what adding a new kind of adapter takes (part 2). Output is real, captured in the scratch project
of the [first project walkthrough](first-project.md) against a local Ollama-style endpoint that was not running: the transport
fixture answered. In the transcripts `batuta` stands for `python <plugin folder>/scripts/batuta.py`.

## 1. A provider of an existing kind

Name the provider in `batuta.json` (contract C01). The credential and the endpoint are never written there: the file holds the
NAMES of two environment variables, and a name is never expanded and refuses a `$`.

```json
"dispatch": {
  "default_lane": "subagent",
  "lanes": ["subagent", "provider:local"],
  "providers": {
    "local": {"kind": "openai-compatible", "credential_env": "LOCAL_LLM_KEY", "endpoint_env": "LOCAL_LLM_URL"}
  }
},
"caps": {"max_concurrent_agents": 4, "max_agents_per_task": 8, "max_opus_reviews_per_task": 1, "spawn_depth": 1,
         "max_cost_usd_per_task": 1}
```

`kind` is one of `openai-compatible`, `gemini`, `bedrock` or `vertex` (and `anthropic`, which only names the credential of the
sdk lane). `default_lane` must be one of `lanes`, and a `provider:<name>` lane needs a matching entry in `providers`. Set the
two variables in your shell (a real key comes from your own secret store, never from a file in the repository):

```
export LOCAL_LLM_KEY=...
export LOCAL_LLM_URL=http://localhost:11434/v1
```

Plain HTTP is allowed only for the local host; every other endpoint must be HTTPS, with TLS verification on and redirects not
followed.

Plan the lane for a linted brief. A provider lane needs `--model`, the provider's own model id, and a verified price or an
explicit `--allow-unpriced`:

```
batuta dispatch plan --brief .batuta/delegation/docs-2026-10-16.brief.md --lane provider:local --model llama3
REFUSED no verified price for local/llama3; pass --allow-unpriced to run it anyway (the cost cap cannot then be enforced)
dispatch plan refused

batuta dispatch plan --brief .batuta/delegation/docs-2026-10-16.brief.md --lane provider:local --model llama3 --report-only --allow-unpriced
WARN no verified price for local/llama3: the cost is recorded as 0 and the cap cannot be enforced
OK lane provider:local, model llama3, role doc-writer, run docs-2026-10-16, cap 1 USD
NEW dispatch request written (<project>/.batuta/delegation/docs-2026-10-16.dispatch-request.json)
planned docs-2026-10-16 on provider:local
```

(The second command exits 2: the WARN is honest, not a pass.) `--report-only` is there because the brief kinds that need tools
(`implement`, `job`, `skeleton`, `run`) are refused on a provider lane without it; this brief is a documentation unit. For a local
model the recorded cost of 0 is truthful; for a hosted model do not use `--allow-unpriced` to bypass the cap, add a price (below).

A dry run of the call shows exactly what would be sent, with the credential masked:

```
batuta dispatch run --request .batuta/delegation/docs-2026-10-16.dispatch-request.json --report-only --allow-unpriced
WARN no verified price for local/llama3: the cost is recorded as 0 and the cap cannot be enforced
OK would POST http://localhost:11434/v1/chat/completions
OK header Content-Type: application/json
OK header Accept: application/json
OK header Authorization: Bearer [REDACTED]
OK body: model llama3, max output tokens 4096, 4139 bytes, about 1309 input tokens
OK dry run: nothing was sent; cap 1 USD (0.0 spent), time limit 3600 s; add --apply to run
docs-2026-10-16 on provider:local: dry run
```

Rehearse offline with `--transport-fixture FILE`, a JSON list of `{status, body, headers}` answers replayed in order, with no
network. The fixture here holds one OpenAI-shaped answer whose message is a complete report. With `--apply`:

```
batuta dispatch run --request .batuta/delegation/docs-2026-10-16.dispatch-request.json --report-only --allow-unpriced --transport-fixture fixture.json --apply
WARN no verified price for local/llama3: the cost is recorded as 0 and the cap cannot be enforced
WARN unpriced: the cost is recorded as 0 and the cap could not be enforced on it
NEW report written from the provider answer (<project>/.batuta/delegation/docs-2026-10-16.report.md)
NEW dispatch result written (.batuta/delegation/docs-2026-10-16.dispatch-result.json)
OK ledger row docs-2026-10-16: complete, local, 1309 in, 190 out, 0.0 USD
OK docs-2026-10-16 complete: the report passes the gates and the brief's checks
docs-2026-10-16 on provider:local: complete
```

The C30 result and the ledger row record the run:

```json
{
  "contract_version": "1.0",
  "kind": "result",
  "run_id": "docs-2026-10-16",
  "lane": "provider:local",
  "status": "complete",
  "provider": "local",
  "model": "llama3",
  "duration_s": 1.095,
  "report": ".batuta/delegation/docs-2026-10-16.report.md",
  "tokens_in": 1309,
  "tokens_out": 190,
  "cost_usd": 0.0
}
```

```
| ID | Agent | Model | Brief | Report | Status | Accepted | Provider | Tokens in | Tokens out | Cost USD |
|---|---|---|---|---|---|---|---|---|---|---|
| docs-2026-10-16 | doc-writer | llama3 | .batuta/delegation/docs-2026-10-16.brief.md | .batuta/delegation/docs-2026-10-16.report.md | complete | no | local | 1309 | 190 | 0.0 |
```

`complete` means the report gates and the brief's checks passed; the row still says `Accepted: no`, and accepting is the main
session's re-check ([delegating a unit](delegating-a-unit.md)). A provider that returns a patch leaves the result
`incomplete` until the checks can run on the patched tree.

### Prices and caps for a hosted provider

A billed lane stops at the task's cost cap. The price comes from `plugins/batuta/scripts/batuta_lib/dispatch/prices.json`: USD per
million tokens by provider and model, each entry with `input`, `output`, an optional `long_context` tier (`above_input_tokens`,
`input`, `output`), the `source` URL, the `read` date and `status`:

```json
"gpt-5": {"input": 1.25, "output": 10.0, "source": "https://developers.openai.com/api/docs/pricing", "read": "2026-10-15", "status": "verified", "note": "standard tier; the page lists no long-prompt tier for this model"}
```

Only an entry with `status: verified` counts; the lookup tries the provider's name and then its kind. A new model needs its row,
added by a change to the plugin with the provider's own pricing page as the source and the date read (a price is never copied
from memory; the table's own note says each rate was read on the provider's official page). The Vertex and Bedrock rows are `null`
until a page confirms them. There is no per-project price override in C01 (UNVERIFIED beyond the keys of the schema).
Once a price exists, the cost cap applies: a projected cost over the cap stops the run before anything is sent, and the spend is
cumulative per task across retries and resumes.

Per kind: Azure OpenAI takes the key in the `api-key` header (the adapter sends it when the endpoint host is `openai.azure.com`),
Gemini in `x-goog-api-key`, and a Bedrock API key as `Authorization: Bearer`; the Bedrock model is the id of an inference
profile (for example the `global.` form of a Claude profile id), sent unchanged; Vertex and Bedrock need an endpoint
(`endpoint_env`). Read 2026-10-15 from the providers' pages named in `batuta_lib/dispatch/adapters.py`.

## 2. A new kind of adapter

A new kind (a provider whose HTTP shape is none of the four) is a code change with four parts, each tested before the code
(the plan's test order: contract conformance, then one test per declared state, then behaviour):

1. In `batuta_lib/dispatch/adapters.py` a request builder `build_<kind>(model, system, prompt, max_tokens, credential,
   endpoint)` returning `(url, headers, body)`, a parser `parse_<kind>(data)` returning a `Completion(text, tokens_in,
   tokens_out)` and raising `AdapterError` when the answer has no usable text or no usage figures, a `salvage_usage` branch that
   reads whatever usage a malformed answer still carries (so a call that may have billed is charged what it reports, not its full
   allowed budget), and an entry in the `ADAPTERS` table. The credential goes only into a header, never into a URL, and an
   adapter never prints it.
2. In contract C01 the `kind` enum of a provider gains the new value. A frozen contract changes only additively, by a minor
   `contract_version` with its own adversarial check (plan decision 23, as ADR-0006 did for C01 1.1), so this part is a contract
   revision, not an edit in place.
3. In `prices.json` a verified row per model, each with its source URL and date.
4. Tests with `ReplayTransport`: the builder's URL, headers and body (the secret masked in every output), the parser on a good
   and on a malformed answer, the usage salvage, and a run through `dispatch run --transport-fixture`.

Retries, the redactor, the cost accounting and the time limit are the transport's and the dispatcher's, not the adapter's, so a
new adapter inherits them.

## Check before you rely on it

- `batuta route show` still lists your roles; a provider lane is chosen per brief, not per role.
- `batuta contract validate C01 .batuta/batuta.json` validates the file against C01 as written; every other command also validates it after `$VAR` expansion when it loads it.
- Redaction: a credential value never appears in any output, result, report or ledger cell. Test that with a fixture whose
  answer echoes the key, before trusting a new endpoint.

## Sources

- The `dispatch` area fragment, summarized in the [command reference](../reference/cli.md); contracts C01, C30;
  `batuta_lib/areas/dispatch.py`, `batuta_lib/dispatch/adapters.py`, `prices.py`, `prices.json`, `transport.py`.
- Provider facts as recorded in `adapters.py` (read 2026-10-15): https://learn.microsoft.com/en-us/azure/ai-services/openai/reference,
  https://ai.google.dev/gemini-api/docs/api-key, https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html;
  prices: https://platform.claude.com/docs/en/about-claude/pricing, https://developers.openai.com/api/docs/pricing.
- Output captured with `batuta.py` in a scratch project against a replayed answer.
