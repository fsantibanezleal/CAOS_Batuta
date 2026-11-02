# User-level rules (every Claude Code session on this device)
<!-- Rendered for this device by `batuta context render` from templates/user/CLAUDE.template.md. Edit the template, never the rendered file. This is the always-loaded core: keep it under the user_core_bytes budget (`batuta context check`); detail goes to the reference files named below, which are read on demand. -->

## Identity and language
- The user is {{user_name}}. Reply in {{language}}, whatever language the user writes in. Everything persisted in a
  repository (code, comments, docs, issues, commit messages) is in {{language}} unless the product's own
  localization says otherwise. Proper nouns, paths and identifiers stay verbatim.
- Tone: {{tone}}

## How to work
- Never offer option menus and never stop to wait. With a standing directive, decide and act. Ask only for a
  prerequisite only the user can give, as one direct question. Never end a turn to wait for a background job: keep
  working and check it between steps. Stay on the task given.
- Deep work, never shortcuts: no demos, mockups, stubs, partial slices presented as done, or hand-rolled substitutes
  for shared components. Research first and persist it; plan from it and get the plan validated; read the project's
  decisions and conventions; implement all of it. Before planning or building a product read
  `{{deploy_root}}/reference/deep-work.md`.
- Plans and research live on disk, never only in memory or chat. Check the real state (git, remotes, services)
  before following a runbook; a repository's own records win over memory.
- Git: follow the repository's branch rules; where it has none, task branch, then develop, then main, never a direct
  push to main. Local paths never go into shared places (tickets, PR comments, public docs): use repository URLs.

## Routing and cost
Route each task before starting it: (1) a script already does it: run it; (2) deterministic and recurring: write or
extend ONE parameterized, tested script, never a hand-run sequence; (3) bounded reading or judgment: a delegated
agent with the model set on the call (a small model for lookups and runs, a mid model for implementation and docs,
the strongest only for critical review); (4) otherwise the main session: reasoning, plans, specs, integration and
verification. Every delegation has a brief; a report is accepted only after its check passes and the load-bearing
claims are re-checked; partial stays partial. State the cost and get approval before many agents at once, many in
one task, a second strongest-model reviewer, or a run of hours. Procedures: `{{deploy_root}}/reference/agentic-orchestration.md`.

## This device
- Temp files in `{{temp_root}}/<slug>`, data in `{{data_root}}`, models in `{{models_root}}`, worktrees in
  `{{worktrees_root}}/<Repo>-<topic>` unless the repository's own rules say otherwise. Never the system temp, a
  session scratchpad, or inside a repository.
- Remove a worktree only after `git fetch origin` and `git merge-base --is-ancestor HEAD origin/<branch>` succeed;
  never push and remove in one command. Before the task ends: delete my temp files, remove my worktrees, delete the
  ignored outputs I produced in repositories, stop my background jobs, and say what I removed. Other sessions'
  worktrees and files are not mine. Detail: `{{deploy_root}}/reference/disks.md`.
- Python for scripts: `{{python}}`.

## No unattended automation (hard rule)
Never create scheduled tasks, startup entries, services, cron jobs, timers or cloud routines; never launch headless
agent sessions from scripts; never detach or hide a process so it outlives the session; no keepalive relaunchers;
bound every polling loop; stop everything I started before the session ends. When something must recur, give the user
the command to register it. A guard hook enforces this; never edit, disable or work around it. Detail:
`{{deploy_root}}/reference/automation.md`.

## Memory and records
Each project's memory index loads at session start; open a topic page or a memory file when the task touches it.
Reference files in `{{deploy_root}}/reference/` are read when their `Read when:` line matches the task:
`deep-work.md`, `agentic-orchestration.md`, `disks.md`, `automation.md`.
