## Area `device` and `preflight`: install, verify, restore and back up a device

A device gets a copy of the plugin (`scripts/`, `contracts/`, `templates/`, `reference/`, `.claude-plugin/`) and a
profile, `device.json` (C15), holding that device's interpreter and roots. No shipped file holds a machine path: roots
come from `batuta.json` (C01 `roots`, `$VAR` expanded) or the environment (`BATUTA_HOME`, `BATUTA_TEMP`, ...), and a
root that resolves inside a repository, to a drive root, to the home folder or onto a missing drive is a configuration
error.

```
python scripts/batuta.py device deploy [--deploy-root DIR] [--python PATH] [--apply]
python scripts/batuta.py device restore [--deploy-root DIR] [--stubs RULES_DIR] [--force] [--apply]
python scripts/batuta.py device check [--hook]
python scripts/batuta.py device backup --out DIR [--allow SHA256] [--apply]
python scripts/batuta.py preflight limits
python scripts/batuta.py preflight prereqs --register FILE [--timeout SECONDS]
```

- `device deploy` is a dry run unless `--apply`, refuses a deploy root inside a repository, on a missing drive or in a
  folder that holds a `scripts/` of someone else, and mirrors only its own folders (a `batuta.json` next to the copy
  stays). The contracts' `fixtures/` (test data) are not copied. A second `--apply` changes nothing.
- `device restore` merges `templates/presets/*.json` (C17) into `~/.claude/settings.json` without removing or reordering
  anything, after a `.bak-<stamp>` copy. A running Claude session can rewrite that file at any time (reported with
  about 15 parallel sessions), so the file is re-read after the write and what is missing is merged again into the file
  as it is now, at most 3 attempts 0.5 s apart; what is still missing is an error naming the items. A value of the
  wrong type (for example `permissions.deny` not a list) refuses and touches nothing. The `session-check` preset is
  rendered per device (the absolute interpreter and launcher from the profile, exec form) and skipped with a WARN while
  the device copy has no `scripts/hook.py`.
- The user core is rendered when `batuta.json` has `user_core.template` (a path, relative to the deploy root) and
  `user_core.values` (the template's `{{name}}` values); without it the step is skipped with a WARN naming the key.
  `--stubs` installs the path-scoped stubs of a `context build` into `~/.claude/rules/`, rewriting each link so it
  resolves from there (the build layout's `../../units/...` is valid only next to the build output); a file that is not
  a generated stub is never replaced without `--force`.
- `device check` reads only, finishes in well under two seconds and never runs git, a subprocess or the network.
  `--hook` prints the SessionStart object (at most 10,000 characters) and exits 0; the same check is the `session-check`
  hook handler.
- `device backup` collects agents, the agentic keys of `settings.json`, memory pages, hand-written rules, the user
  `batuta.json` and, when it is not rendered from a template, `CLAUDE.md`. Rendered files and generated stubs are
  rebuilt, never backed up. Any secret pattern refuses the whole backup and writes nothing; a reviewed line is exempted
  by its sha256 with `--allow`.
- The secret scan reads every file in every plausible decoding (UTF-8, UTF-16 little and big endian, and the raw bytes
  with the NUL bytes removed) and also scans each file name; a hit in any refuses the whole backup. `--out` must be
  empty, new, or hold a `MANIFEST.json` from an earlier backup (a bundle), and every path and area must resolve inside
  it once links and junctions are resolved, or nothing is written or removed. Deploy applies the same resolve-inside check.
- A re-read or replace that fails with a file-system error (a sharing violation, which running sessions cause on
  Windows) or that finds a half-written file counts as a lost race: it is retried, and after the last attempt the error
  names the missing items and the cause. Residual race, not closable without a file lock that Claude Code does not
  take: another session's write that lands in the microseconds between restore's compare read and its `os.replace` is
  lost, and restore still reports success; the verified write detects its own items being dropped afterwards, not that.
- The session-start line is INCOMPLETE only for a failed item with its exact fix. A user value kept on purpose (an
  existing `env` key with another value) and a preset skipped for a missing launcher are shown as notes and leave it OK.
  A broken device copy is repaired from the source it was deployed from (`deployed_from` in its profile), never by
  deploying the copy into itself; when no source exists the fix says to reinstall the plugin.
- `preflight limits` reports a missing GPU or Node as absent (Node is needed only by the `npx` entry), not as an error.
  `preflight prereqs` reads a register of `name`, `why`, `owner_action` and `probe` (a command list or a shell string),
  never prints a probe's output, and exits 1 when any prerequisite is missing.

Managed settings (`templates/managed-settings.example.json`) are the layer users cannot remove, for organizations.
Claude Code reads a `managed-settings.json` from a system folder: on Windows `C:\Program Files\ClaudeCode\`, on macOS
`/Library/Application Support/ClaudeCode/`, on Linux and WSL `/etc/claude-code/` (UNVERIFIED here: confirm against
code.claude.com/docs/en/settings before rolling it out). Copy the example there, keep the deny rules, and set
`allowManagedHooksOnly` to restrict hooks to the managed ones.
