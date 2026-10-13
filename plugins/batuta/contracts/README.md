# Data contracts

Every artifact that crosses a unit boundary (a file, a command output, a hook payload, a configuration) has a
versioned contract in this folder, `plugins/batuta/contracts/`, which ships inside the plugin: every loader resolves
it relative to the plugin, never to a repository root. A project that uses Batuta keeps its own `contracts/`
folder (the default for project contracts) and lints it with `contract lint --root <project>`. Producers validate what they write, consumers validate what they read, and CI
validates every fixture and every artifact against its contract with `batuta.py contract lint` and
`batuta.py contract validate <id> <file>`.

A contract changes only by a new version: bump the major version for a breaking change, the minor version for an
additive one, and keep the old version until no producer emits it. Changing a frozen contract reopens the spec freeze
(the approval hashes every contract file).

Batuta describes the formats the running tools produce and the method CAOS uses: the brief and the report are the
files `delegation.py` and `check_report.py` write and read, the sizing is the CPD `sizing.md`, the interface artifact
is the CPD contract catalog. There is no second machine-readable inventory (ADR-0003).

## Catalog

| Id | File | Artifact and location | Producer | Consumers | Version |
|---|---|---|---|---|---|
| C01 | `C01-batuta-config.schema.json` | `batuta.json` configuration: roots, roles, caps (with `max_cost_usd_per_task`), gates (lifecycle names), dispatch (lanes, providers as environment variable names), budgets | user, `init` | every area, through `batuta_lib/config.py` | 1.0 |
| C02 | `C02-brief.schema.json` | Brief `.batuta/delegation/<id>.brief.md`: title, metadata bullets, sections (the CPD sections for implement, job and skeleton) | `brief new`, main session | agents, `brief lint`, `report check`, SubagentStop hook | 1.0 |
| C03 | `C03-report.schema.json` | Report (path named by the brief): Completeness table, one `## D<n>` section per deliverable, Red and Green run, Sources, Production path when present | agents | `report check`, hook, ledger | 1.0 |
| C04 | `C04-ledger.schema.json` | Ledger `ledger.md`: the Markdown table the CAOS delegation tool writes (ID, Agent, Model, Brief, Report, Status, Accepted) plus the optional columns Provider, Tokens in, Tokens out, Cost USD and Superseded by | `brief new`, `report ledger-status`, `dispatch run` | main session, `gate check` | 1.0 |
| C05 | `C05-spec.schema.json` | Spec `specs/<NNN-slug>/spec.md`; its Interfaces section lists catalog ids | main session, `spec new` | `spec lint`, `spec trace`, `spec freeze`, test-author | 1.0 |
| C06 | `C06-approval.schema.json` | Approval `specs/<NNN-slug>/approvals/<stamp>.json`: `spec_sha256`, `approved_spec_sha256_prefix` (the first 12 hex the human types in `approve <spec id> <first 12 hex of the spec's sha256>`; it must equal `spec_sha256[:12]`), `contracts_sha256`, `adrs_sha256` (every accepted ADR the spec references) and `named_tests_sha256` | approval hook, `spec approve` | `gate check`, approvals guard | 1.0 |
| C07 | `C07-test-lock.schema.json` | Test lock `.batuta/test-locks.json` | `tdd lock` | locked-test guard, `tdd check` | 1.0 |
| C08 | `C08-trace-matrix.schema.json` | Trace matrix `specs/<NNN-slug>/trace.json` | `spec trace` | `gate check`, CI | 1.0 |
| C09 | `C09-evidence.schema.json` | Gate evidence `specs/<NNN-slug>/evidence/<gate>.md` | adversary, reviewer | `gate check`, `gate evidence-lint` | 1.0 |
| C10 | `C10-status.schema.json` | Status `specs/<NNN-slug>/status.md` | main session, `gate status` | `gate check`, doctor, Stop hook | 1.0 |
| C11 | `C11-thresholds.schema.json` | Thresholds `specs/000-foundation/thresholds.json` | owner | `gate thresholds`, CI | 1.0 |
| C12 | `C12-knowledge-manifest.schema.json` | Knowledge manifest `.batuta/knowledge/manifest.json` | owner | `context build`, `context check` | 1.0 |
| C13 | `C13-memory-topics.schema.json` | Memory topics `memory_topics.json` | owner | `memory index` | 1.0 |
| C14 | `C14-context-budget.schema.json` | Context budget (the `budgets` block of C01) | owner | `context check`, doctor | 1.0 |
| C15 | `C15-device-profile.schema.json` | Device profile `<deploy root>/device.json` | `device deploy` | `device restore`, doctor, renderers | 1.0 |
| C16 | `C16-hook-io.schema.json` | Hook input subset and hook output | Claude Code, our hooks | our hooks, Claude Code | 1.0 |
| C17 | `C17-settings-preset.schema.json` | Settings preset fragment `templates/presets/*.json` | Batuta | `device restore`, `init` | 1.0 |
| C18 | `C18-agent-definition.schema.json` | Agent definition front matter `plugins/batuta/agents/*.md` | Batuta | Claude Code, `route check` | 1.0 |
| C19 | `C19-lessons-line.schema.json` | Lessons entry line in `LESSONS.md` | main session | L10-lessons gate check | 1.0 |
| C20 | `C20-cli-output.schema.json` | CLI machine output (`--json`) | every area, through `batuta_lib/output.py` | scripts, CI, skills | 1.0 |
| C21 | `C21-tasks.schema.json` | Tasks `specs/<NNN-slug>/tasks.md`: catalog contract ids, the sizing unit, one wave numbering | main session | `contract graph`, briefs, `spec trace` | 1.0 |
| C22 | `C22-catalog.schema.json` | Contract catalog `docs/contracts/catalog.md`: the 12 columns of the CPD template and an optional `frozen` column | main session, units | `contract graph`, `spec lint`, `provider lint`, `skeleton check` | 1.0 |
| C23 | `C23-sizing.schema.json` | Sizing `sizing.md` in the coordination root: 12 sections (with the Executive brief), 4 tables, disjoint write scopes | main session | `size lint`, `contract graph`, briefs | 1.0 |
| C24 | `C24-adr.schema.json` | ADR front matter `docs/decisions/ADR-NNNN-*.md` | main session | `adr lint`, freeze | 1.0 |
| C25 | `C25-evaluations.schema.json` | Technology decision `docs/design/tech/<tool>.json`: a Technology matrix row plus optional evaluation | main session, research agents | `tech lint`, ADRs | 1.0 |
| C26 | `C26-availability.schema.json` | The availability state vocabulary and the runtime block `{state, reason, source, age, provenance}` an artifact or response carries (the per-boundary declaration is the catalog's missing-data behavior column, C22) | adapters | `provider lint`, `provider check`, runtime, UI | 1.0 |
| C27 | `C27-readiness.schema.json` | Readiness document `data/derived/readiness.json` (the product template's) | `provider check`, product build | `skeleton check`, the page | 1.0 |
| C28 | `C28-model-registry.schema.json` | Model registry entry `models/<id>/card.json` | data and model units | `provider lint`, adapters | 1.0 |
| C29 | `C29-previews.schema.json` | Preview deployment record `docs/design/previews.json` | deploy step | `skeleton check` | 1.0 |
| C30 | `C30-dispatch.schema.json` | Dispatch request and result (`kind` request or result) | `dispatch run` | lanes, ledger | 1.0 |
| C31 | `C31-hooks.schema.json` | `plugins/batuta/hooks/hooks.json` (the registry and the file Claude Code reads, with the official entry fields), the handler discovery rule (`HOOKS = {id: handler}` in an area module) and the handler result | every unit that owns a hook (guards, SubagentStop, approval capture, SessionStart), distribution unit | `init`, the launcher, Claude Code | 1.0 |
| C32 | `C32-commit-grammar.schema.json` | TDD commit message: `[red\|green\|refactor] T-NNN <title>` and the `Test-Change-Approved:` trailer | test-author, implementer | `tdd check`, the locked-test guard | 1.0 |
| C33 | `C33-test-change-requests.schema.json` | Test change requests `specs/<NNN-slug>/test-change-requests.md`: Id (the C07 `change_request` and the `Test-Change-Approved` trailer value), Date, Test path, Requirement, Reason, Proposed change, Status (open, approved, rejected), Decided by | main session, `tdd` | `tdd check`, the locked-test guard | 1.0 |

## Layout

```
plugins/batuta/contracts/
  README.md                         this catalog
  C<nn>-<name>.schema.json          the schema (front matter, row or whole-file schema)
  C<nn>-<name>.sections.json        Markdown contracts only: required sections, tables, rules
  fixtures/C<nn>/valid-*.{json,md,jsonl,txt}
  fixtures/C<nn>/invalid-*.{json,md,jsonl,txt}
```

Every contract has at least two valid and three invalid fixtures (a missing required field, a bad enum or pattern, a
type error), and `contract lint` fails below that. An invalid fixture breaks exactly one rule, states which and states
the error text the validator must produce:

| Format | Reason | Expected error text (optional) |
|---|---|---|
| `.json` | top-level `"_why"` | top-level `"_expect"` |
| `.md` | first line `<!-- why: ... -->` | next line `<!-- expect: ... -->` |
| `.jsonl`, `.txt` | first line `# why: ...` | next line `# expect: ...` |

The validator ignores `_why`, `_expect` and `_recorded` in fixtures and skips those comment lines (in a `.txt` commit message every
line starting with `#` is a git comment). Every C16 fixture carries
`"_recorded": false`: the hook payload fixtures are shaped like Claude Code payloads but synthetic, until a later unit
records real ones. `contract lint` fails when a valid fixture
does not validate, an invalid one validates, an invalid one states no reason, or its errors do not contain the
expected text.

## Schema dialect

JSON Schema draft 2020-12 restricted to: `type` (a name or a list of names), `enum`, `const`, `pattern`, `required`,
`properties`, `additionalProperties` (boolean or schema), `items`, `minItems`, `minimum`, `maximum`, `maxLength`,
`minLength`, `$ref` to `#/$defs/<name>` in the same file, `$defs` (root only), `description` and `format` (only `date`: a
real calendar date written YYYY-MM-DD). Root-only metadata:
`$schema`, `$id`, `title`, `contract_id` (the catalog id) and `contract_version` (`"1.0"`, the version of the contract).
`batuta_lib/contract.py` refuses a schema that uses anything else, so a schema never promises more than the validator
checks. It also refuses a `$ref` chain that returns to where it started.

Patterns follow ECMA-262: `\d` is an ASCII digit and `$` is the end of the text, never the position before a trailing
newline, so `T-001\n` and `T-Ù¡Ù¢Ù£` do not match `^T-\d{3}$`. JSON artifacts are read strictly: `NaN`, `Infinity`
duplicate object keys and a number that overflows to infinity (`1e999`) are refused, and a UTF-8 byte order mark is
accepted. A relative path in a contract is a POSIX path with one pattern everywhere (C01, C07, C28 and C30 carry the
same text, `contract lint` checks it equals the validator's): no leading `/`, no drive letter, no backslash, no control
character (an embedded newline cannot hide a segment), no empty segment and no `.` or `..` segment (so no leading `./`). Rules the subset cannot express (a conditional `required`, an acyclic graph, an
availability rule) are semantic checks in `batuta_lib/contract.py` for C01, C06, C07 (a path has one live lock), C12, C16, C25, C26,
C27, C28, C30, C31 and C32, and rules in the sections file for the Markdown contracts.

Every JSON artifact carries `"contract_version": "1.0"`. The exceptions are artifacts Batuta does not own or that
another tool reads: C16 (Claude Code hook payloads), C14 (a block that lives inside C01 and is validated standalone),
C27 (the product's readiness document, identified by its `schema` field), C26 (a block embedded in other artifacts), the
hooks file of C31 (read by Claude Code), and the Markdown and text contracts (the version lives in the schema file).
Unknown keys are rejected in the integrity records C06, C07, C08 and C27 and allowed elsewhere. The keys `_why`,
`_expect` and `_recorded` are ignored only in a fixture (a file named `valid-*` or `invalid-*`); in any other artifact
they are unknown keys like any other.

## Markdown contracts and the sections file

C02, C03, C04, C05, C09, C10, C18, C19, C21, C22, C23, C24 and C33 are Markdown. Their header is one of three kinds, named by
`front_matter` in the sections file:

- `required`: the front matter subset read by `batuta_lib/frontmatter.py`: `key: value`, `key: [a, b]`, indented
  `- item` lists, quoted strings, integers, booleans, plus one-level maps: an indented map (`key:` then `  sub: value`),
  an inline map (`key: {a: 1, b: x}`) and list items written as inline maps (`- {gate: L3-contracts, reason: "x", by: me,
  date: 2026-10-11}`). Nothing nests deeper than one level: a map inside a map, a list inside a list and a map inside an
  inline list are refused with an error. The schema validates the front matter.
- `bullets`: metadata bullets under the title, before the first `##` heading (`- id: x-2026-10-12`), the format of
  delegation briefs. Keys are lowercased with single spaces (`working directory`), a repeated key is refused, and the
  schema validates the resulting object of strings (`coerce` turns a comma separated value into a list).
- `none`: no machine header (C03, C04, C21, C22, C23, C33).

The sections file next to the schema validates the body:

| Key | Meaning |
|---|---|
| `front_matter` | `"required"` (default), `"bullets"` or `"none"`; `"mode": "lines"` is for C19: every line starting with `line_prefix` is validated as a string, at least `min_lines` of them |
| `coerce` | for `bullets`: header key to `"list"` |
| `case_insensitive_titles` | compare section titles and `section` names lower-cased |
| `sections` | required `##` titles, exact text, in this order (other sections may appear between them) |
| `required_sections` | `##` titles required in any order, matched case-insensitively by title prefix (as the delegation lint does) |
| `required_sections_when` | `[{"when": {"<header key>": [values]}, "sections": [...]}]`: sections a header value requires (C02: the CPD sections for implement, job and skeleton) |
| `section_patterns` | `[{"pattern", "min"}]`: at least `min` section titles match (C03: one `## D<n> ...` per deliverable) |
| `line_rules` | `{"<title>": {"pattern", "min"}}`: at least `min` lines of that section match (C02: `D<n>` lines) |
| `forbidden` | regexes that must match no line of the file |
| `forbidden_prose` | regexes that must match no line of the prose, with fenced code and inline code removed (C03: placeholder text) |
| `final_lines` | regexes the last non-empty lines must match, in order |
| `tables` | `[{"name", "headers", "headers_match", "optional_headers", "row_def", "min_rows", "optional", "section", "coerce"}]`: the first table with those headers; each row is validated as an object keyed by header against `$defs/<row_def>` (or the root schema when `row_def` is null). `headers_match` is `exact` (default) or `contains`: compared lower-cased, extra columns allowed, rows keyed by the spec's spelling (C22, C23, C03). Blank rows are dropped. `coerce` maps a column to `"int"` or `"list"` (comma separated; `-`, `none` or empty is the empty list) |
| `rules` | `nonempty_sections`, `forbid_text`, `forbid_rows`, `require_text_if_rows`, `lines_per_row`, `unique_column`, `ids_match`, `min_rows`, `disjoint_scopes`, `row_requires`, `relpath_columns`, `item_rule`, `section_text`, `section_order`, `exit_code`, `labeled_parts`, `cell_items`, `require_keys`, `forbid_keys`; each may carry `"when": {"<header key>": [values]}` and `"message"`. `lines_per_row` with `id_column` needs, per matching row, a line outside code blocks that matches the pattern with `{id}` replaced by the row's id (C09: one `Re-check: <finding id>` line per fixed finding). `labeled_parts` is a section of `Label: text` lines (C23's Executive brief). `cell_items` splits a table cell into declarations and checks each against a pattern (C22's missing-data behavior) |

A sections file is checked when it loads: an unknown key, an unknown rule type, an invalid pattern or a value outside
its set (`front_matter`, `mode`, a `coerce` kind, an `exit_code` expectation) is an error, so a misspelled key or value
never silently turns a rule off. When a table's `section` is missing the missing section is reported once.

## The artifacts of the method

- **Sizing (C23)** is `sizing.md` of the contract-first method (`tools/agents/sizing-template.md` in CAOS): the sections
  Problem, Executive brief (the four parts Initiative, Outcomes, Positioning and Credibility, each of five or more words, the
  Initiative quantified with a number and a source; or `Not a product: <reason>` for a base repository), ADR constraints, Repositories, Components, Modules and functions, Boundaries, Technology matrix, Machine
  limits, Parallel units, Integrator and merge order and Reservations, each non-empty (`none` is allowed), with the four
  tables Modules and functions, Boundaries, Technology matrix and Parallel units. A technology row has an exact version
  (no range), an `https?://` URL and a `YYYY-MM-DD` date that exists. The write scopes of the units are pairwise disjoint (the same
  path, a directory above another path or globs that meet are overlaps). It lives in the coordination root
  (`coordination_root` of C01, `.batuta/` by default), never in the product repository.
- **Catalog (C22)** is `docs/contracts/catalog.md` (`tools/agents/contracts-template.md`): one row per boundary and per
  model slot. Its `missing-data behavior` cell is the declaration of the boundary's states (ADR-0080 section 3, one
  vocabulary): `;`-separated items `<state>: <behavior> (test: <path>[::name])`, the state one of `available`, `partial`,
  `stale`, `provider(stub|simulator|fixture|baseline)`, `training`, `missing`, each declared once, with `available` and at
  least one other; the provider state names its provenance kind and each state names the test that proves it. A row has a
  semver version, a `kind:path` provider (stub, simulator, fixture or baseline), a baseline provider
  for every model slot (a non-empty `model io`), a unique id and repository-relative paths. `status` is `active`
  (a provider serves the boundary) or `real`. The optional column `frozen` (`yes` or `no`) is the freeze: **a contract is
  frozen when its catalog row says `frozen: yes`**; the approval (C06) proves it by hashing the contract file, the spec,
  every accepted ADR and every named test.
- **Waves.** `contract graph --catalog <catalog> [--sizing <sizing>] [--tasks <tasks>]` numbers waves once: wave 0 is the
  contracts (the frozen ones are listed), wave 1 the walking skeleton, the sizing's units and the tasks start at wave 2.
  A unit that depends on a frozen contract starts at wave 2; one that depends on an unfrozen contract starts after the
  unit that owns that contract's row. A task runs in the wave of its unit; a task without a unit is ordered by its
  `Depends` and the unfrozen contracts it shares.
- **Technology decision (C25)** is a Technology matrix row as a file, with an optional evaluation of candidates; a risky
  candidate carries a spike and a risky chosen candidate needs a spike that passed. `contract lint --root` checks that
  each file equals a row of the sizing.

## Using the contracts

```
python plugins/batuta/scripts/batuta.py contract lint                      # Batuta's own contracts, inside the plugin
python plugins/batuta/scripts/batuta.py contract lint --root path/to/project   # its contracts/, sizing.md, catalog, readiness, tech and specs
python plugins/batuta/scripts/batuta.py contract validate C02 path/to/brief.md
python plugins/batuta/scripts/batuta.py contract validate C22 docs/contracts/catalog.md --root .   # also: every path exists
python plugins/batuta/scripts/batuta.py contract validate C27 data/derived/readiness.json
python plugins/batuta/scripts/batuta.py contract validate C32 commit-message.txt
python plugins/batuta/scripts/batuta.py contract graph --catalog docs/contracts/catalog.md --sizing sizing.md --tasks specs/001-x/tasks.md
```

`contract lint --root` finds the sizing under the coordination root (`<coordination_root>/sizing.md`,
`<coordination_root>/*/sizing.md` or `sizing.md`), the catalog at `docs/contracts/catalog.md`, the readiness document
at `data/derived/readiness.json` or `docs/design/readiness.json`, technology decisions in `docs/design/tech/`, and
`specs/*/spec.md` and `tasks.md`; `--sizing`, `--catalog` and `--readiness` name them explicitly. Cross-file rules: every
Boundaries contract id, every unit dependency, every spec interface and every task contract is a row of the catalog; every
task unit is a row of the Parallel units table; every technology decision equals a matrix row; a readiness entry is a
catalog row and a readiness document whose `catalog_sha256` is not the hash of the catalog is reported stale.

## Shared helpers

Every area reads its configuration through `batuta_lib/config.py`: the order is `--config`, `BATUTA_CONFIG`, the project
file `.batuta/batuta.json`, the user file `<BATUTA_HOME>/batuta.json` (`BATUTA_HOME` defaults to `~/.batuta`), then the
built-in defaults; a named file that is missing is an error; `$VAR` and `${VAR}` expand from the environment and an unset
root falls back to `<BATUTA_HOME>/temp|data|worktrees`. The loader never expands a field that holds an environment variable
NAME (`dispatch.providers.*.credential_env` and `endpoint_env`): they refuse any `$`, and every ConfigError quotes the value
as written in the file, never an expanded one (an environment value can be a secret). Every area prints through `batuta_lib/output.py`: tag lines
(`OK`, `NEW`, `CHANGED`, `SAME`, `SKIP`, `MERGED`, `REMOVED`, `MISSING`, `DIFFERENT`, `REFUSED`, `WARN`, `FAIL`), the C20 object with
`--json`, and the exit code (1 for a `FAIL` or `REFUSED`, 2 for a `WARN`, else 0).

## Availability vocabulary

The six availability states are `available`, `partial`, `stale`, `provider`, `training` and `missing`
(case-sensitive), the states of the dimensioned contract-first method. There is no alias: `synthetic` is not a state. A
`provider` answer carries `provenance`, the kind of provider that answered: `stub`, `simulator`, `fixture` or `baseline`.
**Where each boundary declares what it does in each state** is the `missing-data behavior` column of the contract catalog
(C22): one declaration per state with the test that proves it (see above). C26 keeps only the vocabulary and the runtime
block `{state, reason, source, age, provenance}` an artifact or response carries: `reason` is required for every state but
`available`, `age` is an ISO 8601 duration and is null only for `available` and `missing`, `source` names what answered (the
real producer, a cached snapshot, the provider's path, a model version or the baseline), `provenance` is required for
`provider`. C27 reads the same states per catalog row, with the rules of the
product template's readiness schema: an `available` entry has no reason and is served by the real producer, a
non-available one states a reason, `missing` is listed only for `partial`, a `missing` state has no provenance and any
other has one, a `provider` entry is served by a provider kind, a `training` entry by the released model or the
baseline, and a row whose status is a provider is not served by `real`. Its `status` is `real`, the catalog's `active`
or the provider kind. Evaluation rings are `adopt`, `trial`, `assess` and `caution`; model registry status is `planned`,
`training`, `candidate`, `released` or `retired`, and a model that is not released reports in its `serving` block which
released version or the baseline answered.

## Approval phrase

The approval record (C06) keeps what the human typed in `prompt_excerpt`, and it starts with the phrase
`approve <spec_id> <approved_spec_sha256_prefix>` after any leading whitespace: text may follow it, but a sentence that merely
contains it (`do not approve 001-x ab12...`) is no approval. The keyword and the hex match case-insensitively (`APPROVE 001-x AB12...`
is accepted), the spec id matches exactly, and the stored prefix is lower case. The phrase ends at whitespace or the end of
the text, never inside a longer token (a 13th hex character is refused).

## Ledger

C04 is the Markdown table the CAOS delegation tool writes, so there is one representation: the columns ID, Agent, Model,
Brief, Report, Status and Accepted, plus the optional Provider, Tokens in, Tokens out, Cost USD and Superseded by. A row is
billed when its Provider is not `-` (`anthropic` for the sdk lane, the provider name for a provider lane): it then records
Tokens in, Tokens out and Cost USD (a number, never negative). Status maps the C30 result of a dispatch to the ledger as it
is: C30 `complete`, `incomplete`, `defective`, `pending`, `error`, `timeout` and `over-budget` are C04 statuses of the same
name (`contract lint` checks that every C30 result status is a C04 status); the ledger adds `drafted`, `launched`,
`accepted`, `superseded` and `lost`. `accepted` goes with Accepted `yes`, `superseded` with a Superseded by value. Status is
a strict enum: the evidence of an acceptance ("accepted after verification: ...", "check_report COMPLETE and diff re-read")
goes in the optional free-text Notes column. Accepted is `yes` or `no`; `y` and `n` in any case are aliases, anything else is
refused. The seven mandatory columns come first and in that order (the CAOS reader is positional) and the optional columns
follow in any order; Brief and Report are relative paths of the shared pattern. The ledgers the coordination repository holds
today carry free text in Status and Accepted; the contract does not admit them and the CAOS side migrates them to Notes. The sdk
lane reads the key from `ANTHROPIC_API_KEY` or from the file named by `dispatch.sdk.key_file` of C01 (a path, never the key).

## Hooks

`plugins/batuta/hooks/hooks.json` is the registry and the file Claude Code reads (C31): the event map under `hooks`, each
entry with the official fields (`type`, `command`, `args`, `timeout`, `if`, `shell`, `onFailure`, `async`, `asyncRewake`, `statusMessage`,
`once`). Every entry runs the one launcher `${CLAUDE_PLUGIN_ROOT}/scripts/hook.py` with the handler id as its last argument,
in shell form with the placeholder in double quotes (the shipped form: `"command": "\"$CLAUDE_PLUGIN_OPTION_PYTHON\" -I
\"${CLAUDE_PLUGIN_ROOT}/scripts/hook.py\" report-check", "shell": "bash"`) or in exec form (`"command": "python", "args": ["-I",
"${CLAUDE_PLUGIN_ROOT}/scripts/hook.py", "report-check"]`, the rendered default, see the profiles below). A fail-closed handler (a guard that must block when it cannot decide)
sets `"onFailure": "block"`, accepted on the events that can block through it (`PreToolUse`, `UserPromptSubmit`) and refused
on `SessionStart`, `SubagentStop` and `Stop`; a fail-open handler leaves it out or writes `"onFailure": "continue"` (the
official default, accepted everywhere). `onFailure` is refused together with `"async": true` or `"asyncRewake": true`: the
platform ignores it on an async hook, so a fail-closed entry would fail open. Matchers are allowed on `PreToolUse` (tool
names), `SessionStart` (the start source) and `SubagentStop` (the agent type) and refused on every other event (`Stop`,
`UserPromptSubmit`), where the platform ignores them and a hook scoped by one would run unscoped.

The entry check has two profiles, `check_hook_entry(entry, event, mode)` in `batuta_lib/contract.py` (`mode` is `shipped` or
`rendered`; `check_rendered_entry` adds the structure). The **shipped profile** is the file the plugin ships
(`hooks/hooks.json`): the launcher is `"${CLAUDE_PLUGIN_ROOT}/scripts/hook.py"` and the interpreter is a bare name; in shell form
only, it may instead be exactly `"$CLAUDE_PLUGIN_OPTION_PYTHON"` (in double quotes, the user's python option), and such an entry
sets `"shell": "bash"`; exec form keeps the bare name. The **rendered profile** (`$defs/rendered_entry`) is an entry a device
writes into its settings, with nothing left to resolve: the interpreter is a bare name or an absolute path (exec form: the
command is the path; shell form: the path in double quotes), the launcher is an absolute path ending in `/scripts/hook.py`
(in double quotes in shell form), paths use forward slashes (`/...` or `C:/...`), and no `{{placeholder}}`,
`${CLAUDE_PLUGIN_ROOT}` or `$CLAUDE_PLUGIN_OPTION_PYTHON` remains. Flags, the one handler id, the `onFailure` and matcher
rules are the same in both. `contract validate C31` selects the profile with a top-level `"profile": "rendered"` in the
document (default shipped).

Handlers are discovered like command areas: an area module under `scripts/batuta_lib/areas/` may define a literal
`HOOKS = {id: handler}`; the launcher resolves the id across the areas, an id defined twice is a lint failure and so is a
`hooks.json` id that no area defines (`contract lint` reads the modules without importing them). A unit that owns a hook
therefore needs only its own area module and its entry in `hooks.json`, never the launcher's code. A handler is
`handler(payload: dict) -> dict`: the payload is the C16 input of the event, the result is `{"contract_version": "1.0",
"exit_code": 0 or 2, "output": a C16 output object or null, "message": the reason, required for exit code 2}`. The launcher
prints `output` as JSON, writes `message` to stderr and exits with `exit_code`; an unknown or missing handler id, an invalid handler result or an exception writes the reason to stderr and exits 1, which Claude Code treats as a non-blocking error unless the entry has `onFailure: "block"`.

## Gates

Gate names are the lifecycle names `L0-understand`, `L1-size`, `L2-decide`, `L3-contracts`, `L4-boundaries`, `L5-freeze`,
`L6-skeleton`, `L7-build`, `L8-integrate`, `L9-promote` and `L10-lessons`, the same in C01 (`gates.critical`), C09 and C10;
`contract lint` fails when the three differ. The default critical gates are `L2-decide`, `L5-freeze` and `L9-promote`,
plus `L7-build` for the units listed in `gates.critical_units`. The earlier P-names map to them (P0 to L0, P1 and P2 to
L5, P1b to L3, P3 and P4 to L7, P5 and P6 to L9, P7 to L10) and are refused.
