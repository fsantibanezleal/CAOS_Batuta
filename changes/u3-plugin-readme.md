## Areas `size`, `tech`, `adr` and `spec`: the design gates before any code

```
python scripts/batuta.py size lint [--root DIR] [--sizing FILE] [--catalog FILE]
python scripts/batuta.py tech lint [--root DIR] [--sizing FILE] [--max-age-days 90]
python scripts/batuta.py adr new --title TITLE [--apply]      # then: adr lint
python scripts/batuta.py spec new --title TITLE [--tier S|M|L] [--apply]
python scripts/batuta.py spec lint [--spec ID] [--catalog FILE]
python scripts/batuta.py spec trace ID [--tests PATH] [--apply]
python scripts/batuta.py spec show ID
python scripts/batuta.py spec approve ID                      # manual path: the typed phrase on stdin
python scripts/batuta.py spec freeze --check ID
```

- `size lint` reads `sizing.md` (C23) from the coordination root and the catalog from `docs/contracts/catalog.md` (C22). A
  component has a unit when its line says `(unit: <id>)` for a Parallel units row, or its name appears in a Modules or
  Parallel units row. Totals are the counts in the Size estimate cells, per owner unit and per repository.
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
  spec sha256>`. The prompt hook records it where hooks run; `spec approve ID` is the path where they do not. A prefix that is
  not the current spec's is refused and nothing is written. `spec freeze --check ID` reports VALID, or VOID with the files
  that changed, were deleted or are no longer covered.
