---
id: ADR-0005
title: The contracts after the third review: a ledger that takes notes, a bound approval phrase, hook entry rules, names that are never expanded, two hook entry profiles
status: Accepted
date: 2026-10-12
review_trigger: before the contracts are frozen in full, and whenever the hooks platform, the delegation tool or the configuration loader changes what a contract describes
supersedes: ADR-0004 (in part)
superseded_by: none
---

# ADR-0005: The contracts after the third review

Status: Accepted, 2026-10-12. Supersedes the parts of ADR-0004 listed under "What changes in ADR-0004". It does not change
ADR-0001 to ADR-0003.

## Context

The third review of the contracts (revision 3, `c41b967`) ended FAIL with 0 critical, 3 major and 9 minor open findings
(R3-01 to R3-12), all new and local. The decisions below are decisions 14 to 18 of the plan, plus decision 19 sent while this
revision was in progress. R3-08 (the plan row) and R3-10 (the CAOS template row) are coordination work done outside this
repository.

## Decision

14. **The ledger keeps a strict Status and gains a Notes column (R3-02, R3-06).** C04 keeps the Status enum strict, adds the
    optional free-text `Notes` column for acceptance evidence, accepts `yes`, `no`, `y` and `n` in any case in Accepted (the
    reader maps them, the sections file coerces `yesno`), requires the seven mandatory columns first and in order (the CAOS
    reader is positional; the sections key `headers_lead`), the optional columns after them in any order, and the shared
    relative path pattern in Brief and Report (`contract lint` checks it equal). The free-text ledgers of the coordination
    repository are migrated to Notes later by U12; the contract does not admit them.
15. **The launcher exits 1 for a missing handler (R3-07).** An unknown or missing handler id, an invalid handler result or an
    exception makes the launcher exit 1 with the reason on stderr; stated once in C31 and once in `contracts/README.md`.
16. **The approval phrase is bound (R3-03).** `prompt_excerpt` of C06 contains the whole phrase
    `approve <spec_id> <approved_spec_sha256_prefix>`: the keyword and the hex match case-insensitively, the spec id exactly,
    the stored prefix is lower case, and the phrase is delimited by whitespace or the ends of the text (never a piece of a
    longer token).
17. **Hook entry rules (R3-04, R3-05).** `onFailure` is `continue` or `block`, `asyncRewake` is a boolean, `onFailure` with
    `async: true` or `asyncRewake: true` is refused (the platform ignores it, so a fail-closed entry would fail open), and
    `matcher` is refused on Stop and UserPromptSubmit. `block` stays refused on SessionStart, SubagentStop and Stop;
    `continue`, the official default, is accepted anywhere.
18. **Environment variable names are never expanded (R3-01).** `credential_env` and `endpoint_env` (the C01 fields whose
    pattern is the name pattern, found from the schema) are skipped by the `$VAR` expansion and refuse any `$`; every
    ConfigError quotes values as written in the file, never an expanded value, so no environment value reaches a message.
19. **Two profiles of the hook entry check (decision 19).** The shipped profile (`plugins/batuta/hooks/hooks.json`) keeps the
    launcher `"${CLAUDE_PLUGIN_ROOT}/scripts/hook.py"`; in shell form only, the interpreter may be a bare name or exactly
    `"$CLAUDE_PLUGIN_OPTION_PYTHON"`, and such an entry sets `"shell": "bash"`; exec form keeps the bare-name rule. The rendered
    profile (`$defs/rendered_entry`, the entries a device writes) takes an absolute interpreter (exec form: the command; shell
    form: the path in double quotes) and an absolute launcher ending in `/scripts/hook.py` (in double quotes in shell form),
    forward slashes, and no `{{placeholder}}`, `${CLAUDE_PLUGIN_ROOT}` or `$CLAUDE_PLUGIN_OPTION_PYTHON` left; flags, the one
    handler id and the `onFailure` and matcher rules are shared. The check is the function
    `contract.check_hook_entry(entry, event, mode, matcher=None)`; `check_rendered_entry` adds the structure; a document
    handed to `contract validate C31` selects the profile with a top-level `profile` key.

Smaller fixes of the same revision: a C07 `supersedes` names the sha256 of an earlier entry of the same path (R3-12); `contract
lint` checks that the change-request id pattern is equal in C07, C32 and C33 (R3-11); the F15 test calls `discover_hook_ids` on
two modules instead of reading its source (R3-09); the red test `test_R16_a_supersedes_that_names_no_entry_of_the_same_path_is_refused`
is restored as written.

## What changes in ADR-0004

- Decision 6: the ledger gains Notes, the `y` and `n` aliases, the column order rule and the path pattern (decision 14).
- Decision 8: the hook entry gains `onFailure: continue`, `asyncRewake` and the async and matcher rules; the launcher exit
  behavior is stated once (decisions 15 and 17); the shell form gains the python option interpreter (decision 19).
- Decision 9: the expansion skips environment variable names and the errors quote the written value (decision 18).
- Decision 11: the typed phrase is bound to `prompt_excerpt` (decision 16).

## Consequences

- C01, C04, C06, C07 and C31 change; every one keeps `contract_version` 1.0, since nothing is frozen yet besides C12 to C14
  and the `budgets` block of C01, which are untouched.
- The CAOS ledgers that hold free text in Status or Accepted fail C04 until U12 moves that text to Notes.
- Units U2, U3, U8, U9 and U13 build against these rules: the capture hook writes the typed text, the guards use
  `check_hook_entry`, the device renderer produces rendered entries, dispatch reads credentials through `config.py`.

## Alternatives considered

- Admit free text in Status: rejected, a gate reads Status. Notes carries the text.
- Refuse any `onFailure` on SessionStart, SubagentStop and Stop, `continue` included: rejected, `continue` is the platform's
  default and changes nothing there; only `block` promises a behavior the platform lacks.
- Redact secrets by value in error messages: rejected for the written-value rule, which never has the value to redact.
