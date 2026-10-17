# Principles

Batuta rests on eight principles. Each one names the finding it comes from, with the primary source, and the gate or
check that keeps it true. The same list is recorded as the decision [ADR-0001](../decisions/ADR-0001-architecture.md);
this page adds the evidence behind each line.

Evidence is quoted as the research found it on 2026-10-11. Where a source did not confirm a claim, the page says
UNVERIFIED and what was tried. Numbers carry their source; nothing here is an unmeasured estimate.

## 1. Enforce on artifacts, not prompts

Locked tests, hash-bound approvals, history replay and gate checkers decide. A prompt asks; an artifact check refuses.

Findings:

- Anthropic's own guidance separates the two. The memory documentation states that instructions in CLAUDE.md are
  context, not enforcement, and that "to block an action regardless of what Claude decides, use a PreToolUse hook"
  (https://code.claude.com/docs/en/memory). The best-practices page lists a Stop hook as "a deterministic gate" and asks
  Claude to "show evidence rather than asserting success" (https://code.claude.com/docs/en/best-practices).
- The tools that enforce test-first behaviour in the ecosystem lean on a language model as the judge. Reading the source
  of tdd-guard (https://github.com/nizos/tdd-guard) and Probity (https://github.com/nizos/probity) on 2026-10-11 showed no
  deterministic detector of test tampering, skipped tests or removed assertions in either; Probity's only deterministic
  part is an opt-in counter of new test nodes that counts a `.skip` as a test (landscape research, section 3).
- The academic evidence on cheating says to check both the files and the ambiguity. In EvilGenie
  (https://arxiv.org/abs/2511.21654) test-file tampering was rare on well-specified problems (0.7% of runs modified a
  test file for one agent, 3.4% deleted one for another), while hardcoded or heuristic solutions reached 44.4% on the
  ambiguous problems; test-file edit detection caught the edits, and held-out tests added little. The figures were read
  from the paper's HTML on 2026-10-11 and the fetch tool summarised its tables, so re-read them in the paper before
  quoting them elsewhere.
- UNVERIFIED publicly: ADR-0001 records that prompt-only test-driven development gave no quality gain at 3 to 8 times the
  tokens in a reference harness. That source is a private review and no public source was found that confirms the
  figure, so Batuta does not rest the principle on it.

Checks that keep it true: `tdd check`, `spec freeze --check`, `gate check` and the guards listed in the
[enforcement matrix](../reference/enforcement-matrix.md). See [test-driven development](test-driven-development.md) and
[spec-driven development](spec-driven-development.md).

## 2. The builder never grades itself

Every phase ends with an independent check by an agent with fresh context and no access to the builder's reasoning, and
that agent reproduces every claim.

Findings:

- "A fresh context improves code review since Claude won't be biased toward code it just wrote", and a verification
  subagent exists so that "the agent doing the work isn't the one grading it" (best-practices page above).
- "Out of the box, Claude is a poor QA agent" and tends toward leniency; the evaluator has to be tuned against human
  judgment (https://www.anthropic.com/engineering/harness-design-long-running-apps, March 24, 2026). The same post found
  the evaluator "only worth its cost for tasks beyond what the model could reliably do alone", which is why Batuta
  makes the strong model critical only at three gates (see [the lifecycle](lifecycle.md)).
- A reviewer told to find gaps "will usually report some, even when the work is sound", so the reviewer is told to flag
  only gaps that affect correctness or the stated requirements (best-practices page).
- Two-stage review (spec compliance, then quality) and a fresh subagent per task exist in Superpowers
  (https://github.com/obra/superpowers) and cc-sdd (https://github.com/gotalab/cc-sdd); both enforce it by prompt, not by
  a script (landscape research, section 1; UNVERIFIED beyond the README of each).

Checks that keep it true: `gate evidence-lint` refuses evidence written by the builder or by a script, and
`gate check` refuses a gate with no valid evidence. See [briefs, reports and the ledger](briefs-reports-ledger.md).

## 3. Route by risk and cost

Scripts first; the smallest model for lookups and runs; a mid-size model for implementation, tests, docs and routine
adversarial checks; the strongest model only for critical gates and decisions.

Findings:

- Anthropic recommends `sonnet` for daily coding, `opus` for complex reasoning, `haiku` for simple tasks, and the costs
  page says "Sonnet handles most coding tasks well and costs less than Opus. Reserve Opus for complex architectural
  decisions or multi-step reasoning" (https://code.claude.com/docs/en/model-config, https://code.claude.com/docs/en/costs).
- Multi-agent systems use about 15 times the tokens of a chat, agents about 4 times, and token use alone explained 80
  percent of the variance in BrowseComp; the same post says domains with shared context or many dependencies, which
  include most coding tasks, are not a good fit for wide fan-out
  (https://www.anthropic.com/engineering/multi-agent-research-system, June 13, 2025). Batuta therefore delegates bounded
  units, not wide fan-out on coupled code.
- None of the frameworks read (LangGraph, the OpenAI Agents SDK, CrewAI, AutoGen) enforces a per-task model contract or a
  checked report (landscape research, section 5; absence UNVERIFIED because only documentation pages were read).

Checks that keep it true: `route check`, `brief lint` and the settings preset (`Agent(model:opus)` asks,
`Agent(model:fable)` and the built-in Explore and Plan agents are denied). See [routing](routing.md).

## 4. Small preload, everything else on demand

An always-loaded core under a byte budget, path-scoped rules, an index of knowledge units read by trigger, generated
memory topic pages.

Findings:

- Anthropic targets under 200 lines per CLAUDE.md, loads only the first 200 lines or 25 KB of MEMORY.md, and notes that
  "imports help you organize a long file but don't reduce its context cost" (https://code.claude.com/docs/en/memory).
- A skill's name and description are always in context, its body loads on use, and the listing is capped at 1 percent of
  the context window with each description capped at 1,536 characters (https://code.claude.com/docs/en/skills).
- The principle of "the smallest possible set of high-signal tokens" and just-in-time retrieval comes from
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents (September 29, 2025).
- Long instruction sets degrade: the best frontier models reached 68 percent accuracy at 500 instructions
  (https://arxiv.org/abs/2507.11538, abstract), and relevant information in the middle of a long context is used worse
  (https://arxiv.org/abs/2307.03172, abstract).
- No source read publishes a hard budget gate, a script that fails when the always-loaded set passes N bytes; that gap is
  what `context check` fills. The research marks the absence UNVERIFIED because only documentation pages were read.

Checks that keep it true: `context check`, `context measure`, `memory index`. See [context tiers](context-tiers.md).

## 5. Every hook has a script and a CI twin

A hook is a speed bump on a text command, not a sandbox. It can be blocked by organization policy or dropped from a
settings file that another session rewrote.

Findings:

- Hooks fail open by default: exit 1 is non-blocking and "use exit 2 for policy enforcement"; a timed-out hook does not
  block a PreToolUse call unless `onFailure: "block"` is set, which needs Claude Code v2.1.295 or later
  (https://code.claude.com/docs/en/hooks).
- `allowManagedHooksOnly` in managed settings blocks user, project, local and plugin hooks, and a PreToolUse "allow" never
  widens access past a deny rule (hooks reference; https://code.claude.com/docs/en/permissions).
- A running session can rewrite user settings. Issue 82167 reports `~/.claude/settings.json` replaced by `{}` five times
  in three days with about 15 concurrent sessions and 12 hooks silently ceasing to fire
  (https://github.com/anthropics/claude-code/issues/82167, closed as not planned by a stale bot on 2026-10-09; behavioural
  evidence, not confirmed by maintainers).

Checks that keep it true: every rule in the [enforcement matrix](../reference/enforcement-matrix.md) names its script and
CI equivalent. See [hooks and guardrails](hooks-and-guardrails.md).

## 6. No machine paths

Roots come from environment variables or a configuration file; installed files are rendered per device.

Findings:

- ADR-0001 records the incident: a restored file once pointed every session at another device's drive.
- `${CLAUDE_PLUGIN_ROOT}` changes on every plugin update, so state must not be written there; persistent state belongs
  under `${CLAUDE_PLUGIN_DATA}` or the project (https://code.claude.com/docs/en/plugins).
- `CLAUDE_CONFIG_DIR` relocates `~/.claude` (https://code.claude.com/docs/en/settings), so a path to it cannot be assumed.

Checks that keep it true: `leaks scan`, `scripts/check_content_standards.py` and the render tests. See
[devices and portability](devices-and-portability.md).

## 7. Measured claims only

Token numbers come with their method; no unmeasured savings claims.

Findings: SuperClaude's "30-50% fewer tokens" has no methodology on its page and ruflo's "89% routing accuracy" has no
source (https://github.com/SuperClaude-Org/SuperClaude_Framework, https://github.com/ruvnet/ruflo; both UNVERIFIED in the
research). The simulation values of the Claude Code context-window page are constants, not measurements
(https://code.claude.com/docs/en/context-window). Batuta's own figures, such as the 2008 characters of its 13 skill
listings, come with the command that produces them (`tests/test_skills_content.py`, the test named
`test_listing_budget_of_all_thirteen`).

## 8. Dry run by default, honest exit codes, idempotent writes, atomic replace

Every tool that writes previews first, says what it did, and can be run twice.

Findings: the landscape research concludes that hook and settings edits stay opt-in and previewed, because the guard
hooks change user-level `settings.json`, and that a single-command installer should offer `--dry-run`, `doctor`,
`update` and `uninstall` (`--dry-run` is cc-sdd's, https://github.com/gotalab/cc-sdd; `doctor` is SuperClaude's,
https://github.com/SuperClaude-Org/SuperClaude_Framework; the page of claude-code-templates documents neither an update nor an
uninstall path, https://github.com/davila7/claude-code-templates, UNVERIFIED beyond that page; landscape research,
section 7). The settings-corruption reports under principle 5 are the reason writes replace a file atomically and the
verified settings write re-reads what it wrote.

Exit codes: 0 ok, 1 failure or refusal, 2 warnings or an honest partial. Output lines start with a tag: `OK`, `NEW`,
`CHANGED`, `SAME`, `SKIP`, `MERGED`, `REMOVED`, `MISSING`, `DIFFERENT`, `REFUSED`, `WARN`, `FAIL`. See the
[command line reference](../reference/cli.md).

## Sources

- Research dossiers of the design: official Anthropic guidance, landscape of tools and methods, context organization
  (all dated 2026-10-11, in the project's coordination records; each claim above carries its primary URL).
- Design principles and decisions: the software design document, section 2, and ADR-0001.
- https://code.claude.com/docs/en/memory, /best-practices, /hooks, /permissions, /model-config, /costs, /skills,
  /plugins, /settings, /context-window
- https://www.anthropic.com/engineering/harness-design-long-running-apps,
  https://www.anthropic.com/engineering/multi-agent-research-system,
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://arxiv.org/abs/2511.21654, https://arxiv.org/abs/2507.11538, https://arxiv.org/abs/2307.03172
- https://github.com/anthropics/claude-code/issues/82167
