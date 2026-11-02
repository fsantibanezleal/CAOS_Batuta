# Dispatch lanes and cost caps

A brief (contract C02) is provider-neutral. The dispatcher decides where it runs, and every run returns a report that
passes the same checks, whichever model produced it. A run is started by hand, bounded in time and in cost, and ends with
the command: nothing is scheduled, detached or kept alive.

## The three lanes

| Lane | Runs on | Use | Credential |
|---|---|---|---|
| `subagent` (default) | a Claude Code subagent; the command prints the launch specification and the main session launches it with the Agent tool | interactive sessions | the user's Claude Code login |
| `sdk` | the Claude Agent SDK on an API key (`pip install claude-agent-sdk`, imported only when this lane runs); resumable | long units that must not consume the subscription | `ANTHROPIC_API_KEY`, or the file named by `dispatch.sdk.key_file` in `batuta.json`; never in the repository |
| `provider:NAME` | one tool-less call through an adapter: `openai-compatible` (OpenAI, Azure OpenAI, vLLM, a LiteLLM gateway, Ollama), `gemini`, `bedrock` (Converse) or `vertex` (Claude `rawPredict`); returns a report and an optional patch | cross-model work, cheaper or local models for lookups, a second-opinion adversary from another model family | the environment variable named by the provider in `batuta.json` |

The adapter is a contract, not ad hoc code: a C30 request names the brief, report, lane, role, model, write scope, turn and
time limits, and the run writes a C30 result next to it (`<id>.dispatch-result.json`). Claude Code itself can also run on
Bedrock, Vertex, Foundry or an LLM gateway through its own settings (`env`, `apiKeyHelper`, `ANTHROPIC_BASE_URL`); Batuta
documents that path and does not replace it.

Commands (see the [command reference](../reference/cli.md)):

- `dispatch plan --brief FILE --lane L [--model ID] [--max-cost USD] [--report-only] [--allow-unpriced]` validates the brief
  and the lane against the configuration and writes the request. A provider lane needs `--model` (the provider's own model
  id).
- `dispatch run --request FILE [--apply] [--hours H] ...` is a dry run by default: it prints what would be sent with every
  secret redacted. `--apply` runs the lane, writes the report, the result and the ledger row.
- `dispatch resume --result FILE --apply` continues the saved SDK session of an unfinished result within the cap that is left.

## Cost caps

A lane that bills needs a cost cap and a verified price. The cap is `caps.max_cost_usd_per_task` (or `--max-cost`, below it);
the price is a row of `batuta_lib/dispatch/prices.json`, USD per million tokens by provider and model, each with the source
URL and the date it was read. A model without a verified price is refused unless `--allow-unpriced`, in which case the cap
cannot be enforced and the cost is recorded as 0. A run stops `over-budget` when the projected or actual cost passes the cap.
The rules after the Opus code review (plan decision 36):

- The cost of a task is cumulative across every call, crash, timeout and resume. The spent amount lives in
  `<brief id>.dispatch-state.json`, keyed by the task, and the task's spend is the larger of that file and the `Cost USD` of its
  ledger row, so deleting the state file cannot reset the cap. A rerun starts with the cap already reduced.
- Each call gets at most the cap that is left; a call that ends without usage figures (a crash, a timeout, a cut stream, an
  answer that cannot be parsed) is charged its full allowed budget, an upper bound.
- The output budget of a call is bounded by what the cap still buys; a projected cost over the cap stops the run before
  anything is sent; an answer that costs more than the cap is discarded and recorded as `over-budget` with its partial cost.
- A retry is charged when the first attempt may have billed (an error after the send, a 5xx or 408 answer) and is sized to what
  is left; a 429 answer and a connection error before the send are free. Retries are bounded (at most four, exponential
  backoff with jitter, `Retry-After` honoured up to 60 seconds, never past the deadline).
- Prices are recorded only when confirmed on the provider's own page. The Vertex and Bedrock rows are unknown (`null`) until a
  page confirms them, so those lanes need `--allow-unpriced`; OpenAI's long-context tier (above 272,000 input tokens for
  `gpt-5.4` and `gpt-5.5`) is applied to the whole call; where a page lists a higher rate for long prompts and the entry has no
  tier field, the entry holds the higher rate so a cap is never under-counted. Bedrock needs the id of an inference profile in
  `--model` (for example the `global.` form of a Claude profile id).

The cost evidence behind the caps is in [principles](principles.md), principle 3: agents use about 4 times and multi-agent
systems about 15 times the tokens of a chat (https://www.anthropic.com/engineering/multi-agent-research-system).

## The sdk lane

The lane drives the Agent SDK with the tool set implied by the brief kind and runs the Batuta guards as the PreToolUse
policy: the handlers of `hooks/hooks.json` (matcher and timeout of each entry honoured), else every `guard-*` handler of the guard
area, each through `scripts/hook.py` as a bounded subprocess. Every guard runs and the strictest answer wins (deny over ask
over allow); the lane refuses to run with no guard. Beyond the guards the session policy denies reading the process
environment (which holds the key), pushing to protected branches, force pushes, merges, deletions and Docker prunes, and
limits write tools to the brief's write scope, its report and the temp root; a shell write (redirects, `tee`, `cp`, `mv`,
`rm`, `touch`, PowerShell cmdlets, nested commands) is parsed with the guards' own shell parser and denied when its target is
outside that scope, including a relative target resolved against a `cd`, `pushd` or `Set-Location` and a writer at the end of
a pipe or under `xargs`.

The lane runs the brief's checks inside the time limit before it marks a result complete, and sends a failure back to the
agent for at most two rounds. It keeps its session id so `dispatch resume` can continue it. Known limits are in the
[known-limits page](../reference/known-limits.md): the shell-write check cannot see writes made by code inside an interpreter
(`python -c "open(...)"`), the session's working directory is `--root`, and whether the real SDK ends its CLI child and
background jobs when a run is cancelled is UNVERIFIED (no SDK was installed to test it).

## The provider lanes

A provider lane makes one call over the standard library's `http.client` (not `urllib.request`), with TLS verification on,
redirects not followed, plain HTTP only for the local host, and a watchdog that closes the socket at the call's total time
budget. It honours `HTTPS_PROXY` (through a CONNECT tunnel) and `NO_PROXY` (host names and domain suffixes; no CIDR ranges).
The credential is read at call time from the environment variable named in `batuta.json` and goes only into a header; every
output, result, report note and ledger cell passes through a redactor that masks the value, its JSON and URL encodings,
common token shapes and credential headers.

A provider lane has no tools, so a brief of kind `implement`, `job`, `skeleton` or `run` is refused unless `--report-only`. A
patch the provider returns is written next to the report, must stay inside the brief's write scope (git-quoted paths decoded
first), and is applied by the main session only after the gates pass. A provider lane result is `complete` only when the
report gates and the brief's checks pass; with a patch it stays `incomplete` until the checks can run on the patched tree.
`--transport-fixture FILE` answers provider calls from a JSON list of `{status, body, headers}` for offline runs. The
[adding a provider](../guides/adding-a-provider.md) guide shows the configuration and real output.

## Why the lanes exist

Anthropic documents the unattended path as containers or VMs with credentials held outside the agent
(https://code.claude.com/docs/en/agent-sdk/secure-deployment) and `claude -p --bare` with an API key for scripted runs
(https://code.claude.com/docs/en/headless). Batuta's no-unattended-automation rule is stricter, so the SDK lane is a bounded,
hand-started run that does not use the subscription, and the provider lanes give a second model family as an independent
check. The plan keeps one decision open for the person (open decision 1 of the design): runs that survive a session crash
would need a detached process, and until that is decided the module is not built.

## Sources

- Design: software design document section 3.5, decision 36 and requirement list; contract C30 and the `dispatch` keys of
  C01; `batuta_lib/areas/dispatch.py`, `batuta_lib/dispatch/adapters.py`, `prices.py` and `prices.json`.
- The `dispatch` area fragment, summarized in the [command reference](../reference/cli.md).
- https://code.claude.com/docs/en/agent-sdk/secure-deployment, /headless, https://platform.claude.com/docs/en/about-claude/pricing
  (the price source recorded in `prices.json`, read 2026-10-15), https://developers.openai.com/api/docs/pricing,
  https://www.anthropic.com/engineering/multi-agent-research-system
