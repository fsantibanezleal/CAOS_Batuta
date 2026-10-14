# Enforcement matrix

Every rule the harness enforces mechanically, the hook handler that enforces it in a session, the script or CI
equivalent that enforces it without hooks (design principle 5: every hook has a script and a CI twin), and whether the
hooks.json entry must fail closed (requirement GUARD-3).

## How a handler is called and what a failure means

Every hook entry runs the one launcher `scripts/hook.py <handler id>` (contract C31). The launcher itself **fails open** (the fail open rule: a guard crash never blocks the session):
an unknown id, a handler that raises, a malformed lock file or an invalid result writes the reason to stderr and exits
1, which Claude Code treats as a non-blocking error, so the tool call goes on. A guard that must block when it cannot
decide is therefore wired with `"onFailure": "block"` in `hooks/hooks.json` (a non-zero exit other than a decision, a
crash or a timeout then blocks the action). The launcher and the handlers never decide this; the last column below is
the recommendation the hooks file (unit U9) follows.

The launcher behaviour is requirement GUARD-2. A deny or an ask is a C16 PreToolUse output with exit code 0; an allow has no output.

## Guards (area `guard`)

| Rule | Handler id | Script or CI equivalent | Requirement | onFailure |
|---|---|---|---|---|
| No unattended automation: scheduled tasks, Run keys, Startup folder, services, WMI, `.wslconfig` and `wsl.conf`, cron and systemd enablement, linger, headless `claude -p`, `--dangerously-skip-permissions`, detached or hidden processes, unbounded polling loops | `guard-automation` | `batuta.py guard automation --payload FILE`; CI: `batuta.py guard scan --diff RANGE` | GUARD-1 | block |
| A locked test file is changed only through an approved change request (C33); the lock file (C07) is protected too | `guard-locked-tests` | `batuta.py guard locked-tests --payload FILE`; CI: the tdd area's lock check against the lock file | TDD-2 | block |
| An agent never writes under `specs/<id>/approvals/`; `spec approve --apply` asks first | `guard-approvals` | `batuta.py guard approvals --payload FILE`; CI: the spec area's approval hash check | SDD-3 | block |
| Files that match the secret globs are never read by an agent | `guard-secrets` | `batuta.py guard secrets --payload FILE`; CI: `batuta.py leaks scan` | GUARD-3 | block |
| Destructive command packs: force-push to protected branches, hard reset, git clean, rm -rf of roots, disk formatting | `guard-destructive` | `batuta.py guard destructive --payload FILE`; CI: `batuta.py guard scan --diff RANGE` | GUARD-3 | block |
| An Agent launch names a brief that satisfies C02 (ask or deny per configuration) | `guard-require-brief` | `batuta.py guard require-brief --payload FILE`; CI: `batuta.py contract validate C02 FILE` | GUARD-3 | continue |

`guard <name> --explain` prints what a guard checks and what it found in the current project (for example "no lock
file"). `guard <name>` exits 0 for allow, 1 for deny and 2 for ask.

Why `guard-require-brief` continues: it is a delegation discipline check, not a safety boundary; a crash must not stop
the session, and the ledger and report checkers catch an undelegated launch afterwards. The other five guards protect
state that cannot be restored, so a failure to decide blocks.

## Public hygiene (area `leaks`)

| Rule | Hook | Script or CI equivalent | Requirement | onFailure |
|---|---|---|---|---|
| No user path, e-mail address outside the allow-list, token or private deny-list term in a tracked file | none (a CI and pre-publish check) | `batuta.py leaks scan [--deny-list FILE]` | GUARD-3 | not a hook |

The deny-list file is private: it lives outside the repository (the scanner refuses a path inside it), comes from
`--deny-list` or `BATUTA_LEAKS_DENY_LIST`, and its terms are never printed.

## Configuration read by the guards (batuta.json)

Every key is optional; a missing key keeps the default, and an unreadable configuration keeps the defaults for every
guard except `guard-locked-tests`, which raises (so that a guard never silently looks at the wrong lock file).

| Key | Used by | Default |
|---|---|---|
| `tdd.lock_file` | `guard-locked-tests`, tdd area | `.batuta/test-locks.json` (relative POSIX path, no `..`) |
| `guards.secret_globs` | `guard-secrets` | the built-in list (environment files, keys, certificates, credentials) plus these |
| `guards.protected_branches` | `guard-destructive` | `main`, `master`, `develop`, `release/*` plus these |
| `guards.destructive_disable` | `guard-destructive` | none; names of packs to switch off |
| `guards.require_brief` | `guard-require-brief` | `deny` (`ask` and `off` accepted) |
| `guards.scan_ignore` | `guard scan` | `tests/**`, the guard pattern tables, this document |
| `leaks.allow_emails` | `leaks scan` | the built-in non-personal addresses |

## Missing data

No lock file, no approvals folder, no deny-list, no configuration: the guard allows (or the scan runs without that
check) and says so in `--explain`. The CI equivalents still run.

## Known limits

A hook is a speed bump on a text command, not a sandbox. A path built at run time inside a script, a variable that
holds a path, or a program that writes a locked file from its own code is not visible to a PreToolUse guard; the CI
equivalents (the lock check against file hashes, the approval hash check, `guard scan`, `leaks scan`) are the
backstop, and organization policy can block hooks entirely, which is why every rule has a script twin.
