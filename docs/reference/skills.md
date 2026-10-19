# Skills

The plugin ships thirteen skills, each a numbered procedure over the commands of the [command line](cli.md), the lifecycle gate it
serves and what to do on a non-zero exit. Invoke one in Claude Code as `/batuta:<name>`; Claude can also start the ones that are
not marked human-only when the description matches the task. The trigger column is the skill's `description`, copied verbatim from
`plugins/batuta/skills/<name>/SKILL.md` (a test compares them). The listing of all thirteen is 2008 characters, measured as name
plus description plus `when_to_use` per skill (`tests/test_skills_content.py`).

| Skill | Trigger (description) | Gate | Runs | Started by |
|---|---|---|---|---|
| `/batuta:route` | Use when choosing which agent and model runs a task, or before launching any agent. Prints the role table (model, effort) from batuta.json and checks the agent files against it. | none | `route show`, `route check` | the model or a person |
| `/batuta:brief` | Use when about to hand work to an agent: write the brief first. Creates a brief from the template with its ledger row and lints it before launch. | none | `brief new`, `brief lint` | the model or a person |
| `/batuta:delegate` | Use when launching a named agent on a linted brief, on the subagent lane, the Agent SDK lane or a provider lane, and when accepting the agent's report. | none | `brief lint`, `dispatch plan`, `dispatch run`, `dispatch resume`, `report check`, `report ledger-status` | the model or a person |
| `/batuta:spec` | Use when starting a feature or product, before any code: understand, size, decide technology, write contracts and the spec (L0 to L5, up to the freeze). | L0-understand, L1-size, L2-decide, L3-contracts, L5-freeze | `size lint`, `adr new`, `adr lint`, `tech lint`, `contract lint`, `contract graph`, `spec new`, `spec lint`, `spec trace` | the model or a person |
| `/batuta:freeze` | Use when the spec, contracts and ADRs are ready and a human is about to approve them (L5-freeze). Prints the phrase to type and checks that the approval still matches. | L5-freeze | `spec lint`, `spec show`, `spec freeze`, `gate check` | a person only (`disable-model-invocation`) |
| `/batuta:red` | Use when a task's tests must exist before its code (L7-build, red): a test-author writes failing tests, they are locked by hash and a [red] commit records them. | L7-build | `tdd lock`, `tdd commit`, `tdd check` | the model or a person |
| `/batuta:green` | Use when locked red tests exist and the code must make them pass (L7-build, green): minimal code, a [green] commit, history check and trace. | L7-build | `tdd commit`, `tdd check`, `spec trace`, `tdd change-request` | the model or a person |
| `/batuta:gate` | Use when asking whether a lifecycle gate is passed or what blocks the next one: status, evidence files and the deterministic checks for L0 to L10. | L0-understand to L10-lessons | `gate status`, `gate check`, `gate evidence-lint`, `provider lint`, `skeleton check`, `gate thresholds` | the model or a person |
| `/batuta:verify` | Use at the end of every gate: an independent agent with fresh context reproduces each claim at the reviewed commit and writes the evidence file. | the one being verified | `gate evidence-lint`, `report check`, `gate status` | the model or a person |
| `/batuta:promote` | Use when every gate through L9-promote is green and a human wants to merge a unit: merges only on green checks for the exact head commit. | L9-promote | `gate check`, `skeleton check`, `tdd check`, `gate thresholds`, `gate promote` | a person only (`disable-model-invocation`) |
| `/batuta:context-audit` | Use when a session feels heavy or before adding rules or memory: measures what loads at session start and checks it against the budgets. | none | `context measure`, `context check`, `memory index`, `context build` | the model or a person |
| `/batuta:doctor` | Use when Batuta seems not to run, after an install or update, or on a new device: checks the setup, routing, contracts, hooks wiring and machine limits. | none | `init doctor`, `device check`, `route check`, `contract lint`, `preflight limits`, `guard automation` | the model or a person |
| `/batuta:lessons` | Use when a unit's build has passed, to record its dated lesson (L10-lessons) and check LESSONS.md and overdue ADR reviews. | L10-lessons | `lessons check`, `adr lint`, `gate status` | the model or a person |

Command words above are the first one or two words after `batuta.py` in the skill (a verb or a verb and its sub-verb); the
exact options are in each SKILL.md and in the [command reference](cli.md). Every command a skill names is checked against the dispatcher
by `tests/test_skills_content.py`. Each skill's `allowed-tools` grants Bash only for `python` or `py` running the plugin's `batuta.py`,
plus the read and edit tools the procedure needs.

## Sources

- `plugins/batuta/skills/*/SKILL.md`; https://code.claude.com/docs/en/skills for the skill format and the listing budget.
