## Areas `size`, `tech`, `adr` and `spec`: the design gates before any code

```
python scripts/batuta.py size lint [--root DIR] [--sizing FILE] [--catalog FILE]
python scripts/batuta.py tech lint [--root DIR] [--sizing FILE] [--max-age-days 90]
python scripts/batuta.py adr new --title TITLE [--apply]      # then: adr lint
python scripts/batuta.py spec new --title TITLE [--tier S|M|L] [--apply]
python scripts/batuta.py spec lint [--spec ID] [--catalog FILE]
python scripts/batuta.py spec trace ID [--tests PATH] [--apply]
python scripts/batuta.py spec show ID
python scripts/batuta.py spec approve ID                      # manual path: a human types the phrase at the console
python scripts/batuta.py spec hook-approval < payload.json     # dry run of the hook handler, never writes
python scripts/batuta.py spec freeze --check ID
```

- `size lint` reads `sizing.md` (C23) from the coordination root and the catalog from `docs/contracts/catalog.md` (C22). A
  component has a unit when its line says `(unit: <id>)` for a Parallel units row, or its name appears in a Modules or
  Parallel units row; a component without a unit is a warning, never a failure. Totals are the counts in the Size estimate cells, per owner unit and per repository.
- `tech lint` fails a range, a missing source or a date that does not exist; a date older than `--max-age-days` is a warning.
- `adr new` and `spec new` are dry runs until `--apply`. A change to a decision is a new ADR that supersedes the old one;
  `adr lint` flags overdue `review-by` dates and broken supersession links.
- A spec lives in `specs/<NNN-slug>/` (`spec.md`, `plan.md`, `tasks.md`, `approvals/`, `evidence/`,
  `test-change-requests.md`); `specs/000-foundation/constitution.md` holds the constitution and the tiers. Template examples
  are HTML comments and never count as requirements, tasks or approvals.
- Every active requirement names a Gate: a backticked command or a test id (`path` or `path::name`). Tests tag requirements
  with a comment line `# REQ: <id>[, <id>]` (Python) or `// REQ: <id>` (JavaScript, TypeScript); `spec trace` fails on
  orphans, unknown or retired ids and test files without a marker (a Draft spec is exempt from the orphan rule).
- The freeze: `spec show ID` prints the files that are hashed and the phrase to type, `approve <spec id> <first 12 hex of the
  spec sha256>`. The prompt hook records it where hooks run; `spec approve ID` is the path where they do not, and it reads the
  phrase from the console device (`CONIN$`, `/dev/tty`), so it refuses piped input and runs only in an interactive terminal.
  `spec hook-approval` is a dry run and never writes. A prefix that is not the current spec's is refused and nothing is written. `spec freeze --check ID` reports VALID, or VOID with the files
  that changed, were deleted or are no longer covered.
- Gates name what the freeze hashes: every token of a Gate that resolves to an existing file or folder under the root is hashed
  (folders expand, backslashes are read as slashes, `..` is folded and one that leaves the root is refused); a Gate in Review
  or Frozen that names none is a lint failure, as is prose around a span, a bare file name or a command that cannot fail
  (`true`, `exit 0`, `echo ...`). A `# REQ:` marker counts only as a real Python comment token, and a `// REQ:` marker only
  outside strings, template literals and block comments.
- Residual risk (waived for this unit, review F-02): a schema-valid approval record written by another process (an inline
  interpreter) is indistinguishable from a captured one. The controls are the approvals write guard, the guard on the three
  approval commands and the permission preset that deny agents those writes, and human review of the committed record.
