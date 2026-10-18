# Known limits

Batuta guards against agents cutting corners, not against a determined attacker with code execution. Every residual risk the
design accepts is listed here with the decision that accepted it and the controls that remain. Anything a source did not confirm
is marked UNVERIFIED. The rules and their script and CI twins are in the [enforcement matrix](enforcement-matrix.md); the
reasoning is in [hooks and guardrails](../concepts/hooks-and-guardrails.md).

## Accepted residual risks

| Risk | Decision | Controls that remain |
|---|---|---|
| An approval record or a change-request decision written by an inline interpreter (for example `python -c` writing a schema-valid file) cannot be told from a captured one, because contract C06 1.0 carries no provenance | decisions 30, 32 and 33 (waiver F-02) | the approvals guard denies agents every write under `approvals/` and `test-change-requests.md`, every `spec approve`, `spec hook-approval`, `tdd change-request decide` and every direct run of `hook.py`; the permission preset denies `Edit` on the same paths; a person reviews the committed record |
| Keystrokes injected into the console by another local process (a deliberate local-process attack) can satisfy `spec approve` or `tdd change-request decide` | decisions 32 and 33 | the commands read the console device only, need a real console handle, time out after 300 seconds, and the guards deny agents the direct paths; same class as the first row |
| Commands hidden in variables or string concatenation (`$n = 'Register-Sched' + 'uledTask'; & $n`, `f=tests/a.py; echo x > $f`), a path built at run time inside a script, or a program that writes a locked file from its own code are invisible to a PreToolUse guard | the guards' documented limit (enforcement matrix, Known limits) | the CI twins: the lock check against file hashes, the approval hash check, `guard scan --diff`, `leaks scan`; organization policy can also block hooks, which is why every rule has a script twin |
| A replay worktree can be detected by code under test (by its `.git` file, the temp root's path or the recording runner) and the locked tests skipped there, hiding intermediate states only | decisions 34 and 35 | the head check runs the project's configured `tdd.test_command` verbatim in the real checkout and reads outcomes from its own output, and the CI run is the project's real run; nothing a detected worktree hides ships |
| In-process forgery of test output: code under test that forges the result lines it prints (fake `ok` lines, a rewritten `skipped`) in a way none of the three checks sees | decision 37 | a locked test passes only with exactly one `ok` line; the result lines must equal the runner's own summary; a static scan of every Python file flags runner patches, replaced standard streams and reads of the parent process (a FAIL when introduced in the range without an approved change request); and the human review of the diff, since forgery code is conspicuous |
| Writes made by code inside an interpreter (`python -c "open(...)"`) are not seen by the sdk lane's shell-write check | decision 36 and the dispatch fragment | the brief's write scope and the guards; the policy already denies shell writes it can parse outside the scope |
| What the real Claude Agent SDK does with its CLI child and `run_in_background` jobs when a run is cancelled is UNVERIFIED (no SDK was installed to test it) | decision 36 | runs are bounded by `--hours` and the cost cap, started by hand, and end with the command |
| CI must run exactly `tdd.test_command`; a workflow that tests with another command lets product code tell the head run from CI | decisions 35 and 37 | `init doctor` fails when the `tests` step of `batuta-gates` is not exactly `tdd.test_command`; the template renders the step from the same string |

## Platform limits

- A hook is a speed bump on a text command, not a sandbox. Hooks fail open by default; only an entry with `onFailure: "block"`
  fails closed, and that key needs Claude Code 2.1.295 or later. What an older client does with it is UNVERIFIED (the hooks
  reference is silent), so older clients may not block on a guard failure (https://code.claude.com/docs/en/hooks).
- The Bash sandbox of Claude Code does not run on native Windows, so there the only hard guardrails are permission rules,
  hooks and managed settings (https://code.claude.com/docs/en/sandboxing).
- User settings are volatile: a running session rewrites `~/.claude/settings.json`, and users report it reset to `{}` with many
  concurrent sessions (https://github.com/anthropics/claude-code/issues/82167; behavioural evidence, not confirmed by
  maintainers). `device restore` verifies its write and `device check` catches a reset, but a write by another session that lands
  between restore's compare read and its `os.replace` is lost and restore still reports success; closing it needs a file lock
  that Claude Code does not take.
- A plugin cannot carry `env`, permissions, deny rules or a CLAUDE.md, so the cost guardrails reach a machine only through the
  device channel or the project template (https://code.claude.com/docs/en/plugins/components).
- A call that omits `model` is never matched by `Agent(model:opus)`, so an Opus inheritance from the session is invisible to
  that permission rule (https://code.claude.com/docs/en/permissions).
- Whether the skill listing cap of 1 percent of the context window is applied in characters or tokens is UNVERIFIED (the page says
  "character budget"); Batuta measures characters.
- Whether Claude Code keys auto memory by the repository root is UNVERIFIED; a memory index that belongs to an ancestor folder
  is a warning, not a failure.
- The exact managed-settings folders for each operating system are quoted from the official documentation read on 2026-10-11 and
  marked UNVERIFIED in the plugin fragment; confirm them before rolling out managed settings.

## Limits of the tools

- The Stop hook `gate-stop` does not know which session changed the files: a session that changed nothing can be held once by a
  unit another session left dirty in a shared checkout. Recording each session's touched paths would need a PostToolUse hook.
- `gate check` reads only the newest 500 commits of the history for the files a gate judges; a longer range gets a WARN that
  older judged changes were not compared.
- `tdd` replay costs one checkout and one test run per test-changing commit, each bounded by `replay_timeout_seconds`; CI should
  replay `<base>..HEAD`, not the whole history. Git 2.30 or newer is required.
- A skip built from a name made at run time in a test that is not locked is not seen by the static marker rules, except
  `import_module` or `__import__` with a computed name, which is itself flagged; the runtime replay is the control for locked tests.
- The sdk lane uses `--root` as the session's working directory (the brief's `working directory` line is not used), takes the
  allowed tools from the brief kind, and has no credential-helper command (C01 has no field for one). Bedrock and Vertex prices are
  unknown until a page confirms them, so those lanes need `--allow-unpriced` and the cost cap cannot be enforced on them.
- No command reads a `device backup` bundle back and applies it; restoring on a new machine copies its files by hand.
- Briefs carry absolute paths by contract (C02), so `leaks scan` flags a committed brief; keep `.batuta/delegation/` out of a
  public repository.
- The `markers` key of the C01 `tdd` block: the schema description says the list replaces the default, but the code adds to the
  default list (`batuta_lib/test_markers.py`, `weakening_markers`), as the area's documentation says. The contract text is frozen
  and is corrected only by an additive revision; the behaviour documented in the [configuration reference](configuration.md) is the
  code's.
- The plan's lifecycle table names the reviewer on the strongest model at L8, but the default `gates.critical` is `L2-decide`,
  `L5-freeze`, `L9-promote`; list `L8-integrate` in `gates.critical` to get it.

## Install channels not yet verified end to end

- No unit installed the plugin from the GitHub repository with `/plugin install` (no release tag exists yet; unit U11 cuts it).
  The manifests pass `claude plugin validate --strict` on Claude Code 2.1.301.
- `npx github:fsantibanezleal/CAOS_Batuta` was not run against the real repository; the entry is tested locally with Node. That
  npx accepts a `github:` spec as an exec spec is inferred from the npm spec grammar, not stated on its page (UNVERIFIED).
- The copier channel was verified with copier 9.19.1 in a throwaway environment; the equivalence test skips where copier is absent.
- The generated reference was checked on Python 3.14 only; CI runs the drift test on 3.10 and 3.13.

## Sources

- Software design document: decisions 30, 32, 33, 34, 35, 36 and 37, section 7; the [enforcement matrix](enforcement-matrix.md).
- The `spec`, `tdd`, `gate`, `device`, `dispatch`, `init` and `guard` area fragments in `changes/`; `plugins/batuta/skills/doctor/SKILL.md`.
- https://code.claude.com/docs/en/hooks, /sandboxing, /plugins, /permissions;
  https://github.com/anthropics/claude-code/issues/82167.
