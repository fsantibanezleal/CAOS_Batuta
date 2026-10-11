# Data contracts

Every artifact that crosses a unit boundary (a file, a command output, a hook payload, a configuration) has a
versioned contract in this folder. Producers validate what they write, consumers validate what they read, and CI
validates every fixture and every artifact against its contract with `harness.py contract lint` and
`harness.py contract validate <id> <file>`.

A contract changes only by a new version: bump the major version for a breaking change, the minor version for an
additive one, and keep the old version until no producer emits it. Changing a frozen contract reopens the spec freeze
(the approval hashes every contract file).

## Catalog

| Id | File | Artifact and location | Producer | Consumers | Version |
|---|---|---|---|---|---|
| C01 | `C01-harness-config.schema.json` | `harness.json` configuration | user, `init` | every area | 1.0 |
| C02 | `C02-brief.schema.json` | Brief `.harness/delegation/<id>.brief.md` | `brief new`, main session | agents, `brief lint`, `report check`, SubagentStop hook | 1.0 |
| C03 | `C03-report.schema.json` | Report (path named by the brief) | agents | `report check`, hook, ledger | 1.0 |
| C04 | `C04-ledger.schema.json` | Ledger `.harness/delegation/ledger.jsonl` (one object per line) | `brief new`, `report ledger-status` | main session, `gate check` | 1.0 |
| C05 | `C05-spec.schema.json` | Spec `specs/<NNN-slug>/spec.md` | main session, `spec new` | `spec lint`, `spec trace`, `spec freeze`, test-author | 1.0 |
| C06 | `C06-approval.schema.json` | Approval `specs/<NNN-slug>/approvals/<stamp>.json` | approval hook, `spec approve` | `gate check`, approvals guard | 1.0 |
| C07 | `C07-test-lock.schema.json` | Test lock `.harness/test-locks.json` | `tdd lock` | locked-test guard, `tdd check` | 1.0 |
| C08 | `C08-trace-matrix.schema.json` | Trace matrix `specs/<NNN-slug>/trace.json` | `spec trace` | `gate check`, CI | 1.0 |
| C09 | `C09-evidence.schema.json` | Gate evidence `specs/<NNN-slug>/evidence/<gate>.md` | adversary, reviewer | `gate check`, `gate evidence-lint` | 1.0 |
| C10 | `C10-status.schema.json` | Status `specs/<NNN-slug>/status.md` | main session, `gate status` | `gate check`, doctor, Stop hook | 1.0 |
| C11 | `C11-thresholds.schema.json` | Thresholds `specs/000-foundation/thresholds.json` | owner | `gate thresholds`, CI | 1.0 |
| C12 | `C12-knowledge-manifest.schema.json` | Knowledge manifest `.harness/knowledge/manifest.json` | owner | `context build`, `context check` | 1.0 |
| C13 | `C13-memory-topics.schema.json` | Memory topics `memory_topics.json` | owner | `memory index` | 1.0 |
| C14 | `C14-context-budget.schema.json` | Context budget (the `budgets` block of C01) | owner | `context check`, doctor | 1.0 |
| C15 | `C15-device-profile.schema.json` | Device profile `<deploy root>/device.json` | `device deploy` | `device restore`, doctor, renderers | 1.0 |
| C16 | `C16-hook-io.schema.json` | Hook input subset and hook output | Claude Code, our hooks | our hooks, Claude Code | 1.0 |
| C17 | `C17-settings-preset.schema.json` | Settings preset fragment `templates/presets/*.json` | harness | `device restore`, `init` | 1.0 |
| C18 | `C18-agent-definition.schema.json` | Agent definition front matter `plugins/harness/agents/*.md` | harness | Claude Code, `route check` | 1.0 |
| C19 | `C19-lessons-line.schema.json` | Lessons entry line in `LESSONS.md` | main session | P7 gate check | 1.0 |
| C20 | `C20-cli-output.schema.json` | CLI machine output (`--json`) | every area | scripts, CI, skills | 1.0 |
| C21 | `C21-tasks.schema.json` | Tasks `specs/<NNN-slug>/tasks.md` | main session | wave planner, briefs, `spec trace` | 1.0 |
| C22 | `C22-interfaces.schema.json` | Interface table in the spec (a section of C05) linking each interface to its contract | main session | `contract graph`, `spec lint` | 1.0 |
| C23 | `C23-system-map.schema.json` | System map `docs/design/system-map.json` (sizing and decomposition) | main session | `size lint`, `contract graph`, wave planner | 1.0 |
| C24 | `C24-adr.schema.json` | ADR front matter `docs/decisions/ADR-NNNN-*.md` | main session | `adr lint`, freeze | 1.0 |
| C25 | `C25-tech-evaluation.schema.json` | Technology evaluation `docs/design/tech/<id>.json` | main session, research agents | `tech lint`, ADRs | 1.0 |
| C26 | `C26-provider-registry.schema.json` | Provider registry `contracts/providers.json` | main session | `provider lint`, `provider check`, runtime | 1.0 |
| C27 | `C27-readiness-matrix.schema.json` | Readiness matrix `docs/design/readiness.json` | `provider check`, main session | `skeleton check`, status | 1.0 |
| C28 | `C28-model-card.schema.json` | Model card `models/<id>/card.json` | data and model units | `provider lint`, adapters | 1.0 |
| C29 | `C29-previews.schema.json` | Preview deployment record `docs/design/previews.json` | deploy step | `skeleton check` | 1.0 |

## Layout

```
contracts/
  README.md                         this catalog
  C<nn>-<name>.schema.json          the schema (front matter, row or whole-file schema)
  C<nn>-<name>.sections.json        Markdown contracts only: required sections, tables, rules
  fixtures/C<nn>/valid-*.{json,md,jsonl}
  fixtures/C<nn>/invalid-*.{json,md,jsonl}
```

Every contract has at least two valid and three invalid fixtures (a missing required field, a bad enum or pattern, a
type error). An invalid fixture states which rule it breaks and which error text the validator must produce:

| Format | Reason | Expected error text (optional) |
|---|---|---|
| `.json` | top-level `"_why"` | top-level `"_expect"` |
| `.md` | first line `<!-- why: ... -->` | next line `<!-- expect: ... -->` |
| `.jsonl` | first line `# why: ...` | next line `# expect: ...` |

The validator ignores `_why` and `_expect` and skips those comment lines. `contract lint` fails when a valid fixture
does not validate, an invalid one validates, an invalid one states no reason, or its errors do not contain the
expected text.

## Schema dialect

JSON Schema draft 2020-12 restricted to: `type` (a name or a list of names), `enum`, `const`, `pattern` (a search,
anchor it), `required`, `properties`, `additionalProperties` (boolean or schema), `items`, `minItems`, `minimum`,
`maximum`, `maxLength`, `minLength`, `$ref` to `#/$defs/<name>` in the same file, `$defs` (root only) and
`description`. Root-only metadata: `$schema`, `$id`, `title`, `contract_id` (the catalog id) and `contract_version`
(`"1.0"`, the version of the contract). `harness_lib/contract.py` refuses a schema that uses anything else, so a
schema never promises more than the validator checks. Rules the subset cannot express (a conditional `required`, an
acyclic graph) are semantic checks in `harness_lib/contract.py` for C12, C16, C25 and C26, and rules in the sections
file for the Markdown contracts.

Every JSON artifact carries `"contract_version": "1.0"`. The exceptions are artifacts the harness does not own: C16
(Claude Code hook payloads), C14 (a block that lives inside C01 and is validated standalone) and the Markdown
contracts (the version lives in the schema file). Unknown keys are rejected in the integrity records C04, C06, C07
and C08 and allowed elsewhere.

## Markdown contracts and the sections file

C02, C03, C05, C09, C10, C18, C19, C21, C22 and C24 are Markdown. The front matter is the subset read by
`harness_lib/frontmatter.py`: `key: value`, `key: [a, b]`, indented `- item` lists, quoted strings, integers,
booleans, plus the two extensions C10 needs (a one-level indented map, and list items written as inline maps
`- {gate: P3-red, reason: "x", by: me, date: 2026-10-11}`). The schema validates the front matter; the sections file
next to it validates the body:

| Key | Meaning |
|---|---|
| `front_matter` | `"required"` (default) or `"none"` (the file has no machine front matter; C03, C21, C22) |
| `mode` | `"lines"` for C19: every line starting with `line_prefix` is validated as a string, at least `min_lines` of them |
| `sections` | required `##` titles, exact text, in this order (other sections may appear between them) |
| `section_patterns` | `[{"pattern", "min"}]`: at least `min` section titles match (C03: one `## D<n> ...` per deliverable) |
| `line_rules` | `{"<title>": {"pattern", "min"}}`: at least `min` lines of that section match (C02: `- D<n>: ...`) |
| `forbidden` | regexes that must match no line of the file (C03: placeholder text) |
| `final_lines` | regexes the last non-empty lines must match, in order (C03: `BRIEF:` and `REPORT:`) |
| `tables` | `[{"name", "headers", "row_def", "min_rows", "optional", "section", "coerce"}]`: the first table with exactly those headers; each row is validated as an object keyed by header against `$defs/<row_def>` (or the root schema when `row_def` is null); `coerce` maps a column to `"int"` or `"list"` (comma separated, `-` or empty is the empty list) |
| `rules` | `nonempty_sections`, `forbid_text`, `forbid_rows`, `require_text_if_rows`, `unique_column`, `ids_match`, `require_keys`, `forbid_keys`; each may carry `"when": {"<front matter key>": [values]}` |

## Using the contracts

```
python plugins/harness/scripts/harness.py contract lint                      # schemas, fixtures, spec interface rows
python plugins/harness/scripts/harness.py contract validate C02 path/to/brief.md
python plugins/harness/scripts/harness.py contract graph --tasks specs/001-x/tasks.md --interfaces specs/001-x/spec.md
```

`contract graph` puts tasks that share no unfrozen contract and no Depends edge in the same wave. A contract is
frozen when its file is declared in the C22 table and exists under the root. A Depends edge between two tasks that
both list the same frozen contract is reported as a coupling warning; a cycle is a failure.
