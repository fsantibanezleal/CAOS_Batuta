# Deep work, never shortcuts: the mandatory sequence

Read when: planning, building, auditing or calling done any product, app, lab or package.

The always-loaded core states the rule in one line; this file holds the sequence. A shortcut that looks done hides
the gap. "To go faster", "it is green" and "just a first slice" are the failure, not a reason. Every product,
app or package follows this order, no step skipped:

1. **Preliminary deep research.** Research the real state of the art (papers, repositories, methods, tools,
   datasets, benchmarks, evaluation); verify every claim against a primary source (the paper, the official
   documentation, the repository); mark anything unconfirmed as UNVERIFIED instead of inventing it. Persist it to
   dated dossiers on disk. Never build a plan from memory or from chat.
2. **Propose the plan from that research**, persisted to the project's plan folder with its state (status, plan,
   backlog, history, findings), covering the whole product: repository, data, models and methods, training,
   packages if required, interface, docs, guides, deploy, scenarios.
3. **The owner validates the plan** before implementation. Never build on an unvalidated plan.
4. **Read the decisions, conventions and templates**, and build on them; never re-derive them.
5. **Implement all of it**: no skips, no deferrals, no toys or demos. Full functional apps, deep repositories, deep
   documentation. Create a package when one is required. A proper deploy path. Nothing deferred; no partial slice
   presented as done.
6. **The interface baseline is the minimum, not the target**: localization, light and dark themes, the shared shell
   and the page structure are the floor; exceed it with real depth. Verify every panel visually (both themes, every
   tab and mode) before anything is done.
7. **Transcribe deep content from the persisted research at build time, never from memory; build vertically, unit by
   unit.** Context is lost over a long build and across compaction. When building a unit (method, engine, case,
   page), open its dossier and transcribe its theory, equations, references and caveats into the docs, and finish
   that unit completely (code, tests, docs) in the same commit before the next. Never horizontally (all code first,
   docs last).

Where the project has its own quality bar or build sequence, that text binds and this file is the minimum.
