## Area `dispatch`

A brief (C02) is provider-neutral; the dispatcher decides where it runs. Every run returns a report that passes the same
gates and records provider, model, tokens and cost in the ledger. Runs are started by hand, bounded by time and cost, and
end with the command: nothing is scheduled, detached or kept alive.

```
python scripts/batuta.py dispatch plan --brief FILE [--lane subagent|sdk|provider:NAME] [--model ID] [--max-cost USD] [--report-only] [--allow-unpriced] [--root DIR]
python scripts/batuta.py dispatch run --request FILE [--apply] [--hours H] [--report-only] [--allow-unpriced] [--transport-fixture FILE] [--root DIR]
python scripts/batuta.py dispatch resume --result FILE [--apply] [--hours H] [--root DIR]
```

| Lane | Runs on | Credential |
|---|---|---|
| `subagent` (default) | a Claude Code subagent: the command prints the launch specification, the main session launches it | the Claude Code login |
| `sdk` | the Claude Agent SDK on an API key (`pip install claude-agent-sdk`), resumable | `ANTHROPIC_API_KEY`, or the file named by `dispatch.sdk.key_file` |
| `provider:NAME` | one tool-less call: `openai-compatible`, `gemini`, `bedrock` or `vertex`; returns a report and an optional patch | the environment variable named by the provider in `batuta.json` |

- `dispatch run` is a dry run by default: it prints what would be sent with every secret redacted. `--apply` runs the lane,
  writes the report, the C30 result (`<id>.dispatch-result.json` next to the request) and the ledger row.
- A billed lane needs a cost cap (`caps.max_cost_usd_per_task`, or `--max-cost` below it) and a verified price in
  `batuta_lib/dispatch/prices.json`; a model without one is refused unless `--allow-unpriced` (the cap then cannot be
  enforced and the cost is recorded as 0). The run stops BLOCKED (`over-budget`) when the projected or actual cost passes
  the cap.
- A provider lane has no tools: a brief of kind implement, job, skeleton or run is refused unless `--report-only`. A patch
  the provider returns is written next to the report and must stay inside the brief's write scope; apply it only after the
  gates pass.
- The sdk lane runs the batuta guards (the PreToolUse handlers of `hooks/hooks.json`, or the default set) through
  `scripts/hook.py` for every tool call, runs the checks of the brief before marking the result complete, and keeps its
  session id so `dispatch resume` can continue it within the cap that is left.
- `--transport-fixture FILE` answers provider calls from a JSON list of `{status, body, headers}` for offline runs.
