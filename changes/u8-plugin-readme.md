## Areas `guard` and `leaks`, and the hook launcher

Guardrails run as PreToolUse hooks through one launcher, `scripts/hook.py <handler id>`, and each has a script and a CI
equivalent (see `docs/reference/enforcement-matrix.md`).

```
python scripts/batuta.py guard automation|locked-tests|approvals|secrets|destructive|require-brief --payload FILE [--explain]
python scripts/batuta.py guard scan --diff origin/develop..HEAD [--root DIR]
python scripts/batuta.py leaks scan [--root DIR] [--deny-list FILE] [--allow-email PATTERN]
```

- The launcher fails open: any problem of its own (unknown id, crash, invalid result) exits 1 with the reason on
  stderr, which Claude Code treats as a non-blocking error. A guard that must block when it cannot decide is wired with
  `onFailure: "block"` in `hooks/hooks.json`; the matrix lists which ones.
- `guard <name>` exits 0 for allow, 1 for deny, 2 for ask. `--explain` says what the guard checks and what it found
  (for example, no lock file means nothing is locked yet).
- Optional `batuta.json` keys: `tdd.lock_file`, `guards.secret_globs`, `guards.protected_branches`,
  `guards.destructive_disable`, `guards.require_brief` (`deny`, `ask`, `off`), `guards.scan_ignore`, `leaks.allow_emails`.
- `leaks scan` never reads a deny-list from inside the repository; keep that file outside it and pass `--deny-list` or
  set `BATUTA_LEAKS_DENY_LIST`.
