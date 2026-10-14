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
- Console reading (review F-01): `spec approve` needs a console on standard input (on Windows a console handle, on POSIX a tty
  with a `/dev/tty` that opens) and waits at most 300 seconds for the typed phrase, then refuses with exit 1 and writes
  nothing. Keystrokes injected into the console by another local process are the same waived class as the inline interpreter
  above: a deliberate local-process attack that the guards deny on its direct paths.
- A Gate passes only when it yields at least one hashable test file (a path that looks like a test); configuration and
  documentation files named next to it are still hashed but never count. A backticked command starts with a known runner, an
  executable on the PATH or a script of the repository, and a chain that can never fail (`|| true`, `; exit 0`,
  `python -c pass`, `echo ...`) is refused.
- Gate vocabulary: a Gate command starts with a runner of the documented list (python, py, pytest, uv, poetry, tox, nox, hatch,
  node, npm, npx, pnpm, yarn, bun, deno, vitest, jest, go, cargo, dotnet, mvn, gradle, java, make, bash, sh, pwsh, powershell,
  ctest, cmake, bazel, rspec, bundle, ruby, php, phpunit, swift, mix, R, Rscript, julia, among others) or a script of the
  repository that exists; the PATH is never consulted, so lint gives the same answer on every device. A leading `cd <dir> &&`
  and a trailing `&& echo ...` are fine; a command after a double pipe, an unconditional success after the test, `ls`, `cat`
  and other read-only commands alone, and `--collect-only` or `--dry-run` listings are refused. Test files are recognized by
  the common conventions (`test_*.py`, `*_test.py`, `*.test.*`, `*.spec.*`, `__tests__/`, `*_test.go`, `tests/`, `src/test/`,
  `*.Tests` folders); `conftest.py`, `__init__.py` and non-code files never count as the test, though they are hashed when named.
- A Gate's exit status must be the test's: a double pipe, a pipe after the test (unless the Gate starts with `set -o pipefail` in
  bash or sh; PowerShell pipes are refused), a `;` or `&` chain that does not end with a test invocation naming a test path, an
  inline `python -c` that runs no test runner, and info or listing invocations (`--version`, `-h`, `--help`, `--collect-only`,
  `make -n`, `npm ls`, `pip list`) are refused; `bash -c`, `sh -c`, `cmd /c`, `pwsh -Command` bodies are analysed with the same
  rules. Quoting follows POSIX (no escape inside single quotes). Under a test folder only test-named files count as the test
  (`test_*.py`, `*_test.py`, `*.test.*`, `*.spec.*`, `*_test.go`, Rust `tests/*.rs`, Jest `__tests__/*`); helpers and fixtures
  are hashed when named.
