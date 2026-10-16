---
name: freeze
description: Use when the spec, contracts and ADRs are ready and a human is about to approve them (L5-freeze). Prints the phrase to type and checks that the approval still matches.
disable-model-invocation: true
allowed-tools: Bash(python *) Read Grep Glob
argument-hint: <spec id>
---

# Freeze a spec with a hash-bound human approval

Gate: L5-freeze (critical: the independent check is the reviewer on the strong model, see the `verify` skill).

1. Lint the spec: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" spec lint --spec SPEC_ID`
2. Show the human what is being approved and the phrase to type:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" spec show SPEC_ID`
   It lists every file the approval hashes and prints `approve <spec id> <first 12 hex of the sha256>`.
3. The human reads the files and types the phrase in the prompt. The UserPromptSubmit hook records it as the approval
   (C06). You never type it, never write under `specs/<id>/approvals/` and never run an approve command: the approvals
   guard denies it. On a device where hooks do not run, the human runs the manual approve command in their own terminal.
4. Check that the approval still matches every hashed file (VALID or VOID):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" spec freeze --check SPEC_ID`
5. Run the gate check: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate check SPEC_ID`
6. Any later change to a hashed file voids the approval: the human approves the new phrase again.

On a non-zero exit: exit 1 from `spec freeze --check` means VOID or no approval: show `spec show` again and ask the human
to type the new phrase. Exit 1 from `gate check` is a failed rule (gate out of order, evidence missing): fix it, do not
work around it. Exit 2 is a warning: read it and report it.
