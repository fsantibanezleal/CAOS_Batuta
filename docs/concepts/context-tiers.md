# Context tiers and budgets

What an agent reads at the start of every session costs tokens every time, is paid again by every subagent that loads it,
and competes for attention with the task. Batuta keeps that part small, measures it and fails a check when it grows, and
moves everything else to places that are read only when needed.

![Three tiers of context: L0 loaded at every session start under byte budgets, L1 loaded when a matching file is read, L2 listed in an index and read on demand; enforcement is a hook, not text.](../assets/context-tiers.svg)

## What Claude Code loads

From Anthropic's memory documentation (https://code.claude.com/docs/en/memory):

- CLAUDE.md files of the directory chain above the working directory and the user file load in full at launch; a
  subdirectory CLAUDE.md loads when a file in that directory is read.
- A rule file under `.claude/rules/` without `paths` front matter loads at launch like CLAUDE.md; with `paths` it loads only
  when Claude reads a matching file.
- `@path` imports are expanded at launch, relative to the importing file, to a depth of four hops. "Imports help you organize
  a long file but don't reduce its context cost."
- Auto memory: only the first 200 lines or 25 KB of `MEMORY.md`, whichever comes first, are loaded at the start of every
  conversation; topic files are read on demand.
- Skills (https://code.claude.com/docs/en/skills): the name and description of every skill is always in context; the body
  loads when the skill is used; a skill with `disable-model-invocation: true` costs no listing tokens.
- A subagent starts with fresh context but receives the CLAUDE.md hierarchy (except the built-in Explore and Plan agents)
  unless its definition says `omitClaudeMd: true` (https://code.claude.com/docs/en/sub-agents). So the preload is paid again
  by every subagent, and each subagent also builds its own prompt cache.

## The tiers

| Tier | What | Loads | Held by |
|---|---|---|---|
| L0 | the rendered user core, the project CLAUDE.md chain, unscoped rules, the MEMORY.md index | every session | byte budgets, `context check` |
| L1 | `.claude/rules/<id>.md` stubs with `paths` front matter | when a matching file is read | the stub is a summary and a link |
| L2 | reference units listed in `INDEX.md` with triggers; memory topic pages | when the task matches | zero tokens until read |

An enforcement band sits beside them: anything that must never be violated is a hook with a script and a CI twin, because
instructions in CLAUDE.md are context, not enforcement (see [hooks and guardrails](hooks-and-guardrails.md)). Rules for moving
text between tiers: a statement that must hold in every task stays in L0 as one line plus a pointer; a statement tied to
files goes to L1; procedure text goes to a skill or an L2 unit; anything that must be blocked becomes a hook. Imports are
never used to cut cost.

## Budgets and the measured limits

| Limit | Value | Source |
|---|---|---|
| CLAUDE.md length | target under 200 lines | https://code.claude.com/docs/en/memory |
| MEMORY.md loaded | first 200 lines or 25 KB | https://code.claude.com/docs/en/memory |
| SKILL.md length | under 500 lines | https://code.claude.com/docs/en/skills |
| skill listing | 1 percent of the context window (`skillListingBudgetFraction`, default 0.01) | https://code.claude.com/docs/en/settings-reference |
| one skill description | 1,536 characters (`skillListingMaxDescChars`) | https://code.claude.com/docs/en/settings-reference |
| hook `additionalContext` and plain stdout | 10,000 characters each; over the cap the output goes to a file and Claude gets a 2,000-character preview | https://code.claude.com/docs/en/hooks |
| Batuta user core, project core | 7000 bytes each (C01 default `budgets`) | `batuta_lib/config.py`, enforced by `context check` |
| Batuta unscoped rules | 2000 bytes | same |
| Batuta memory index | 4000 bytes and 60 lines | same |

The Batuta budgets are the defaults of `budgets` in `batuta.json`; a project changes them there, and never raises one to
make a check pass. Measured, with its method: the 13 skills of the plugin list 2008 characters in total (the sum over the
skills of name, description and `when_to_use` lengths; the test asserts at most 3000), printed by
`tests/test_skills_content.py` in the test `test_listing_budget_of_all_thirteen`. Whether the 1 percent cap is applied in
characters or tokens is not settled by the page, which says "character budget" (UNVERIFIED), so Batuta measures the
characters and leaves a wide margin.

`context measure` prints each file's layer, bytes and estimated tokens (bytes divided by 4, an estimate and labelled as
one) and the L0 total; it always exits 0. The documented simulation values of the context-window page are illustrative
constants, not measurements (https://code.claude.com/docs/en/context-window), so the only figures this documentation quotes
for Batuta are the ones its commands print.

## The commands

- `context check` measures bytes, not characters, against the C01 `budgets`. Exactly at a limit passes; one byte over fails
  (exit 1) and names the largest sections with where to move them: "demote them to a reference file listed in the index (L2,
  read on demand) or a path-scoped rule (L1)". `@path` imports are counted the way Claude Code loads them, up to four hops;
  a cycle or more than four hops is a WARN. A MEMORY.md over 200 lines or 25 KB fails for any project; another project's
  index over the C01 budget but under the cap is a WARN. Whether Claude Code keys memory by the repository root is
  UNVERIFIED, so a memory index that belongs to an ancestor folder is a warning, not a failure.
- `context build --manifest FILE --out OUT --apply` validates the knowledge manifest (C12) and writes `INDEX.md` (one line
  per unit with load, triggers and requires, in the style of llms.txt), `CORE.md` (the `load: always` units) and
  `rules/<id>.md` (one stub per `load: path` unit). It refuses when the core or the index exceeds the manifest budget. Output
  is sorted, LF only and carries no timestamp, so a second `--apply` reports `SAME` for every file and the cached prefix stays
  reusable.
- `memory index --memory-dir DIR --project NAME --apply` rewrites an opted-in project's `MEMORY.md` as pinned lines plus one
  line per topic, and writes one page per topic (`topics/<id>.md`). It writes, replaces and removes only pages that carry its
  generation mark; a file in `topics/` without the mark is the owner's and is never touched.

## The knowledge manifest (contract C12)

Each unit has an `id`, `title`, `kind` (`rule`, `procedure`, `decision`, `memory`, `reference`), a `file` inside the manifest
folder, a `summary` of at most 160 characters, and `load`: `always`, `path` (with `paths` globs), `trigger` (with `triggers`
words) or `manual`. `requires` and `related` are the graph edges: the generator checks that they resolve and that `requires`
is acyclic. The graph is small (hundreds of units at most), so it lives in the manifest and is traversed by the generator;
graph databases and embeddings are out of scope for the core, because no source found measures a graph store against a
markdown index for a few hundred rules, and the products read need a database or an LLM for ingestion (Graphiti, Cognee,
GraphRAG; context research, section 2). Real output of `context build` on the template manifest, after the first write:

```
NEW CORE.md
NEW INDEX.md
NEW rules/web-ui-floor.md
context build: written; core 293 bytes (about 74 tokens, estimate), index 736 bytes
```

and the generated stub for the path-scoped unit:

```
---
paths:
  - "web/**"
  - "src/ui/**"
---
<!-- generated by batuta context build -->
# Web UI floor

Minimum for any web interface: sized containers, one navigation row, light and dark themes.

Full text: `../../units/web-ui-floor.md`; read it when this rule applies.
```

## Memory topic pages

A memory index that lists every memory on its own line grows past the 200-line load. `memory index` keeps the index to a few
lines and moves the per-memory lines to topic pages that the agent opens when the task matches. Real output on a demo folder
of five memories (`memory_topics.json`, contract C13, lists the project, its pinned memories and its topics with `when` and
`match` words):

```
# Memory index (generated by batuta memory index; edit the memories or the topics file, not this file)
## Always relevant
- [Decide and act](feedback_decide_and_act.md) - decide the next step and do it
## Topics (open the page when the task matches)
- [Deploy and hosts (2)](topics/deploy.md) - before deploying or touching a host
- [Release (1)](topics/release.md) - before tagging or promoting
- [Other (1)](topics/other.md) - when no topic above fits
```

The index was 454 bytes and 7 lines against a budget of 4000 bytes and 60 lines. A project that is not listed in the topics
file is not opted in: the command exits 2 and writes nothing. Pages written by an older tool, before the mark existed, are
adopted with `--adopt-legacy`.

## Prompt caching and why the core is byte-stable

Anthropic's prompt-caching documentation gives the multipliers relative to base input: a 5-minute cache write 1.25x, a
1-hour write 2x, a read 0.1x (0.05x on Opus 5.5 and Sonnet 5.5)
(https://platform.claude.com/docs/en/build-with-claude/prompt-caching). In Claude Code the order is system prompt and tools,
then project context (CLAUDE.md, auto memory, unscoped rules), then the conversation, and project context changes only at
session start, `/clear` or `/compact`; nested CLAUDE.md files and path-scoped rules load later as conversation content, so
they never break the prefix (https://code.claude.com/docs/en/prompt-caching). The consequences the research drew:

- a preload costs a read per turn after the first, but the first turn, every cache miss after the time-to-live gap and every
  subagent (a cold cache of its own, five-minute lifetime by default) pay the write and the full latency;
- the always-loaded text must be byte-stable: no dates, counters or timestamps in CLAUDE.md or in the SessionStart output,
  which is why the generators sort their output and carry no timestamp;
- volatile material belongs only in on-demand files; the cost of a large preload is also a quality cost independent of price
  (the long-instruction studies cited in [principles](principles.md), principle 4).

## Sources

- Design: software design document section 3 (principle 4), requirements CTX-1 to CTX-3; contracts C12, C13, C14 and the
  `budgets` block of C01; `batuta_lib/config.py`.
- The `context` and `memory` area fragment, summarized in the [command reference](../reference/cli.md);
  `plugins/batuta/skills/context-audit/SKILL.md`; `tests/test_skills_content.py`.
- Research dossier on context organization (2026-10-11), and https://code.claude.com/docs/en/memory, /skills, /sub-agents,
  /hooks, /settings-reference, /prompt-caching, /context-window,
  https://platform.claude.com/docs/en/build-with-claude/prompt-caching,
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents, https://llmstxt.org/ (the index
  format), https://github.com/getzep/graphiti, https://github.com/topoteretes/cognee, https://arxiv.org/abs/2404.16130
- Real output captured on the template manifest and a demo memory folder in a scratch folder.
