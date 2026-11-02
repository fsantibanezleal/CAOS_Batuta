# Spec-driven development

No code is written before a spec exists and a person has approved it. A Batuta spec is a short Markdown file whose
requirements are written in EARS form, each with a gate that can run and fail, and whose approval is a hash-bound typed
phrase. This page describes the spec, the freeze and what the freeze can and cannot prove.

## Where the method comes from

No Anthropic page uses the term "spec-driven development" (searched code.claude.com, anthropic.com and claude.com on
2026-10-11). The closest official statement is the best-practices page: have Claude interview you, write the result to a
spec, "start a fresh session to execute it", and make the spec "self-contained: they name the files and interfaces involved,
state what is out of scope, and end with an end-to-end verification step that proves the feature works"
(https://code.claude.com/docs/en/best-practices). The tool ecosystem has converged on the same spine: requirements in EARS
or as user stories with acceptance criteria, a design, dependency-annotated tasks and a fresh agent per task (landscape
research, section 2). Batuta borrows:

- from GitHub Spec Kit (https://github.com/github/spec-kit), the constitution of immutable articles with a test-first
  article, and the `[NEEDS CLARIFICATION]` marker that keeps open questions out of a frozen spec;
- from cc-sdd (https://github.com/gotalab/cc-sdd) and Kiro (https://kiro.dev/docs/specs/), requirements in EARS and a
  tasks table with dependency waves, with the write scope and the dependencies named per task;
- from OpenSpec (https://github.com/Fission-AI/OpenSpec), a folder per change.

What Batuta adds is mechanical enforcement: a lint that refuses a requirement with no runnable gate, a hash that binds an
approval to the exact text read, and a freeze check that voids the approval when anything it covered changes.

## The spec folder

`spec new --title TITLE --tier S|M|L --apply` creates `specs/<NNN-slug>/` with `spec.md`, `tasks.md`, `approvals/` and
`evidence/`; `specs/000-foundation/constitution.md` holds the constitution and the tiers. `plan.md` is required for tiers M
and L, and a tier L spec must reference at least one ADR so that the freeze hashes it.

| File | Contract | Holds |
|---|---|---|
| `spec.md` | C05 | front matter (`id`, `title`, `status` Draft, Review, Frozen or Retired, `tier`, `owner`, `created`), then Problem, Scope and out of scope, Requirements, Interfaces, Edge cases, Open questions |
| `tasks.md` | C21 | one row per task: Task (`T-NNN`), Title, Requirements, Contracts, Depends, Wave, Owner role, Unit |
| `plan.md` | none | the constitution check (each decision names its article and the simpler alternative rejected), design, test strategy, risks |
| `approvals/<stamp>.json` | C06 | the typed approval and its hashes |
| `evidence/<gate>.md` | C09 | the independent check of each gate |
| `test-change-requests.md` | C33 | requests to change a locked test; created by the first request |

## Requirements: EARS, ids never reused, a gate each

A requirement is one table row with an id of the form `REQ-<AREA>-NNN`, a kind, the EARS text, a gate, how it is verified
and a status (`active` or `retired`). The ids are never reused, in the spec or in any other, and `unique_column` rules
refuse a duplicate. The kinds are the EARS patterns:

| Kind | Form |
|---|---|
| `ubiquitous` | The system shall ... |
| `event` | When ..., the system shall ... |
| `state` | While ..., ... |
| `unwanted` | If ..., then the system shall ... |
| `optional` | Where ..., ... |

The Gate column is a backticked command or a test id (`path` or `path::name`). The lint is strict about what counts. A gate
passes only when it yields at least one hashable test file under the repository root (a path that looks like a test by the
common conventions, such as `test_*.py`, `*.test.*`, `__tests__/`, `*_test.go`); a command that cannot fail (`true`,
`exit 0`, `echo ...`, `|| true`, `python -c pass`, a listing with `--collect-only` or `--dry-run`) is refused; a command
must start with a known test runner or a script of the repository (never the `PATH`, so the lint gives the same answer on
every device); and a pipe after the test or a chain that does not end with the test invocation is refused because it would
hide the test's exit status. The complete rules are in the [command reference](../reference/cli.md) and in the area's
tests.

Open questions are marked with the clarification tag, and a spec in Review or Frozen has none. A spec in Review or Frozen
also lists every interface it touches by catalog id (or the word `none`), which ties it to the data contracts
([contract-first parallel development](contract-first-parallel-development.md)).

## Tiers and the constitution

The constitution is seven articles (real, not demo; spec before code; tests first from an independent oracle; contracts
first; determinism; honesty; simplicity). The tier of a spec decides which artifacts it needs:

| Tier | For | Artifacts |
|---|---|---|
| S | a small, local change | `spec.md`, `tasks.md` |
| M | a feature across several files or one contract | tier S plus `plan.md` with the constitution check |
| L | a feature that crosses units or repositories, or changes a contract | tier M plus at least one referenced ADR |

## Trace

Tests tag the requirements they serve with one comment line, `# REQ: <id>[, <id>]` in Python or `// REQ: <id>` in
JavaScript and TypeScript; the same convention feeds `tdd lock`. `spec trace SPEC_ID --apply` writes
`specs/<id>/trace.json` (C08): per requirement its gate, tests and tasks, plus the orphans, unknown ids and untagged
tests. It fails on an orphan requirement, an unknown or retired id, or a test file without a marker; a Draft spec is exempt
from the orphan rule. In the [first project guide](../guides/first-project.md) the trace of two requirements is
`ok=true`.

## The freeze

The freeze is the approval of the exact spec a person read. `spec show SPEC_ID` prints every file the approval hashes and
the phrase to type; for the example in the guide it printed:

```
OK hashes specs/002-greeting/spec.md (6b4ab454260c)
OK hashes tests/test_greeter.py (fd508c2222be)
OK approval phrase to type: approve 002-greeting 6b4ab454260c
```

The 12 hex digits are the first 12 of the SHA-256 of the spec text (LF-normalized), so the approval binds to the version the
person read: if the spec changes before the phrase is typed, the digits no longer match and nothing is written. The person
types the phrase as a prompt. The first line of the prompt, trimmed, must be exactly `approve <spec id> <12 hex>` (keyword
and hex in any case); other text on that line, even after a correct phrase, is refused, so "approve 001-x abc123def456 --
no wait, do not" records nothing, and a sentence that merely contains the phrase is not an attempt.

The record (`approvals/<stamp>.json`, contract C06) holds the hashes of everything the approval covers: the spec, every
contract the spec's Interfaces section references (catalog ids resolved to schema files), every accepted ADR it references
and every test file a Gate names. Real record of the guide's example (the OS account name is replaced by `<user>`):

```json
{
  "contract_version": "1.0",
  "spec_id": "002-greeting",
  "spec_sha256": "6b4ab454260c97ac9ecbb42ff9574dd8debc5582e88d134bd1984980ac70b0d4",
  "approved_spec_sha256_prefix": "6b4ab454260c",
  "contracts_sha256": {},
  "adrs_sha256": {},
  "named_tests_sha256": {
    "tests/test_greeter.py": "fd508c2222beb0630c12916c8ec465f6a90b0fe393a5d52af0d102159d5a2e21"
  },
  "approved_by": "<user>",
  "prompt_excerpt": "approve 002-greeting 6b4ab454260c",
  "approved_at": "2026-10-17T02:20:38Z",
  "tool_version": "0.01.000"
}
```

`spec freeze --check SPEC_ID` reports VALID, or VOID with the files that changed, were deleted or are no longer covered. Any
later change to a hashed file voids the approval and the person approves the new phrase. The newest schema-valid record of a
spec is the one that counts. `gate check` repeats the same check at L5 and refuses an approval written by an agent role.

Because the freeze hashes the test files a gate names, those files exist before the approval: `spec lint` warns about a missing one at Review and fails at
Frozen, and the approval is refused while one is missing. They are locked and committed afterwards, in the red step of
[test-driven development](test-driven-development.md).

## Who can write an approval

An approval has two writers and no others: the `spec-approval` handler that the harness runs on `UserPromptSubmit` when a
person types the phrase, and `spec approve SPEC_ID`, the manual path for a device where hooks do not run. `spec approve`
reads the phrase from the console device itself (`CONIN$` on Windows, `/dev/tty` elsewhere), never from standard input: it
needs a real console handle (on Windows `GetConsoleMode` must succeed on the stdin handle, which a stdin of NUL, a pipe or a
file fails), waits at most 300 seconds, and refuses with exit 1 and nothing written otherwise. `spec hook-approval` is a dry
run that never writes.

The approvals guard denies agents every invocation of `spec approve`, `spec hook-approval` and `hook.py spec-approval`, and
every write under `specs/<id>/approvals/` through Edit, Write, MultiEdit, NotebookEdit and a shell. The project template's
`.claude/settings.json` adds the permission rule `Edit(/specs/**/approvals/**)` to the deny list.

Residual risk, accepted and recorded (plan decisions 30 and 32): a schema-valid approval record written by another process,
such as an inline interpreter, is indistinguishable from a captured one, because contract C06 1.0 carries no provenance.
The same class covers keystrokes injected into the console by another local process. The controls are the approvals guard,
the permission preset and human review of the committed record. See [known limits](../reference/known-limits.md).

## Sources

- Design: software design document sections 3.3, 4 (SDD-1 to SDD-5) and decisions 11, 16, 28, 29, 30 and 32; contracts
  C05, C06, C08, C21 in `plugins/batuta/contracts/`; `batuta_lib/approval.py`; the constitution and spec templates under
  `plugins/batuta/templates/`.
- The spec, size, adr, tech and tdd area fragments, summarized in the [command reference](../reference/cli.md); the
  [enforcement matrix](../reference/enforcement-matrix.md).
- https://code.claude.com/docs/en/best-practices
- https://github.com/github/spec-kit, https://github.com/gotalab/cc-sdd, https://kiro.dev/docs/specs/,
  https://github.com/Fission-AI/OpenSpec (landscape research, section 2)
- The `spec show` output and the approval record were captured in a scratch project (see the
  [first project guide](../guides/first-project.md)).
