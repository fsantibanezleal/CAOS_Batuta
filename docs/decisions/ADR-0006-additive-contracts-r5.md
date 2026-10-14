---
id: ADR-0006
title: First additive revision of the frozen contracts: C01 1.1 with the tdd block, C34 the contract-tests record, C16 1.1 with the UserPromptSubmit output, and two corrections of the checkers
status: Accepted
date: 2026-10-14
review_trigger: whenever the tdd area, the gates area or the hooks platform changes what these contracts describe
supersedes: none
superseded_by: none
---

# ADR-0006: First additive revision of the frozen contracts

Status: Accepted, 2026-10-14. It amends no earlier ADR. It applies plan decision 23 (after the freeze a contract evolves
only additively, by a minor `contract_version` with an adversarial check) and decision 30 (a checker corrected to the
rule its contract already states needs no version bump).

## Context

Three parallel units found that a frozen contract did not describe what a running tool reads or writes: the tdd area reads
optional `tdd.*` keys that C01 does not name; the gates area reads a local JSON of contract-test results that no contract
defines; and the approval handler of the spec area returns a UserPromptSubmit output that C16 does not define, so the
launcher check (C31) refuses it. The review of the spec unit also found two checkers that were looser or stricter than the
rule they state. Decision 5 holds: contracts follow the running tools.

## Decision

1. **C01 1.1 adds an optional, closed `tdd` block.** Keys, all optional: `test_command` (non-empty string),
   `replay_timeout_seconds` (integer, at least 1), `lock_file` (the shared relative path pattern; default
   `.batuta/test-locks.json`, a JSON file that is never `batuta.json`) and `markers` (array of non-empty strings, the weakening
   markers). The block is checked only when `contract_version` is "1.1": a 1.0 document may hold any `tdd` value, as the open
   root always allowed (adversary finding F2). The schema holds the block as `$defs.tdd`, applied by a semantic check. It accepts
   `contract_version` "1.0" and "1.1"; every 1.0 document stays valid. The `budgets` block and every other key are untouched.
2. **C34 1.0, the contract-tests record, is new.** JSON, closed: `contract_version`, `commit` (7 to 40 lowercase hex),
   `generated` (date) and `results` (key: a repository-relative test path, optionally followed by `::<name>`; value `pass`,
   `fail` or `skip`). An empty `results` means nothing ran. The key shape is a semantic check in `contract.py` because the
   schema dialect has no property-name rule. Produced by `gate tests-record` (built in the gates area), read by
   `skeleton check --tests-record`. A key is a file path: no trailing `/`, no control character or line break, and a
   non-blank name after `::` (F6). Frozen on merge.
3. **C16 1.1 adds the UserPromptSubmit output.** Closed, with the fields of the Claude Code hooks reference, section
   "UserPromptSubmit decision control" and "JSON output": the universal `continue`, `stopReason`, `suppressOutput`,
   `systemMessage` and `terminalSequence`; the top-level `decision` (only `block`) with an optional `reason`; and `hookSpecificOutput`
   with `hookEventName` "UserPromptSubmit", `additionalContext`, `sessionTitle` and `suppressOriginalPrompt`. The reference does not
   require a reason, so a block needs none (F4); a present `reason` is non-blank. A field of another event (for example `permissionDecision`) is refused here. C16 1.0 defined
   none of the universal fields, so none is reused; the 1.0 outputs and every 1.0 fixture are unchanged. The launcher check of
   C31 accepts the new output because it validates `output` against C16.
   Primary source, read on 2026-10-14: https://code.claude.com/docs/en/hooks
4. **Correction, not a revision: the C23 overlap check.** `scopes_overlap` compares write scopes with `str.casefold()` (`pipeline/`
   and `PIPELINE/` are one folder on Windows and default macOS; `straße/` and `STRASSE/` too, conservative where NTFS keeps them
   apart) and treats a bare name without glob characters as a prefix of paths below it (`pipeline` with `pipeline/x.py`, never a
   sibling such as `pipeline.py` or `ab/` for `a`). A scope with a glob overlaps another only when one matches the other by pattern
   or one is a folder prefix of the other's fixed leading part, as in 1.0, so `tests/unit/test_*.py` and `tests/unit/conftest.py`
   stay disjoint (F1). The wording of the failure is unchanged. C23 keeps version 1.0 because its text already says that a
   directory above a path overlaps it.
5. **Correction, not a revision: the fence rule of the placeholder check.** `prose()` stripped only backtick fences, so a
   placeholder word inside a `~~~` fence failed `contract validate C03`. `strip_fences()` now applies to tildes exactly the rule
   1.0 applied to backticks: a fence opens on a line that starts, after any whitespace (a fence inside a nested list item counts),
   with three backticks or three tildes, and closes on the next line that starts the same way with the same character; an
   unclosed fence is not stripped (F3, F5). A test compares it with the 1.0 regular expression on a corpus of backtick inputs.
   Text outside a fence is still checked. No contract version changes.

Accepted as is (F6): `additionalContext` keeps the 10000-character cap of the C16 1.0 SessionStart output, a Batuta limit the
reference does not set; `systemMessage` has no cap; `lock_file` and C34 keys are not percent-decoded, because no consumer
decodes them.

## Consequences

- C01 and C16 are at 1.1, C34 is new at 1.0; the catalog in `contracts/README.md` says so. The tdd, gates and spec units
  adapt to the contracts after this merges.
- Additivity is the binding test: the adversary check ran every 1.0 fixture and the reproductions of F1 to F3 against develop
  and the head.
- `tests/test_contract_fixtures.py` expected every schema at exactly "1.0"; it now expects the minor-revised ones at 1.1
  and the artifact version const-or-first-enum at "1.0".
- Not done here: the producer `gate tests-record` and any change to the tdd or gate areas.
