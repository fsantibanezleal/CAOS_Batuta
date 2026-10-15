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
- Cost is cumulative per task: `<id>.dispatch-state.json` next to the result holds the cost, tokens and (sdk lane) the time spent by
  every earlier run, resume and crash of the request; each call gets at most the cap that is left, and a call that ends without usage
  figures (crash, timeout, cut stream, an answer that cannot be parsed and carries none) is charged its full allowed budget, an upper
  bound. A rerun of a request therefore starts with the cap already reduced.
- The sdk guards: the PreToolUse handlers of `hooks/hooks.json` (matcher and timeout of each entry honoured), else every `guard-*` handler
  of the guard area. Every guard runs; the strictest answer wins. The lane refuses to run with no guard. Beyond the guards the session
  policy denies reading the process environment (which holds the key), pushing to protected branches, force pushes, merges, deletions
  and Docker prunes, and limits write tools to the brief's write scope, its report and the temp root.
- A provider lane result is `complete` only when the report gates and the brief's checks pass; with a patch it is `incomplete` until the
  checks can run on the patched tree. The patch scope and the report path are re-read from the brief at run time; a request that differs
  is refused.
- Known limits: the session's working directory is `--root` (the brief's `working directory` line is not used), the allowed tools come
  from the brief kind, there is no credential-helper command (C01 has no field for one), and whether the real SDK ends its CLI child and
  agent `run_in_background` jobs when a run is cancelled is UNVERIFIED (no SDK was installed to test it).
- Bedrock: name the inference profile id in `--model`, for example `global.anthropic.claude-sonnet-5-5`; Bedrock and Vertex rows of the
  price table are unknown, so those lanes need `--allow-unpriced` (the cost cap then cannot be enforced and the cost is recorded as 0
  and for a call that may have billed without usage figures only the token estimates are recorded, because an unpriced model has no rate to charge).
