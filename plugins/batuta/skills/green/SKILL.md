---
name: green
description: "Use when locked red tests exist and the code must make them pass (L7-build, green): minimal code, a [green] commit, history check and trace."
allowed-tools: Bash(python *scripts/batuta.py* *) Bash(py *scripts/batuta.py* *) Read Grep Glob Edit Write
argument-hint: <task id T-NNN>
---

# Green: the minimum code that passes the locked tests

Gate: L7-build (green half). The code is written by `batuta:implementer`; the locked tests are not edited.

1. Launch the implementer with the `brief` and `delegate` skills (`subagent_type="batuta:implementer"`, model from `route show`).
2. Write the minimum code that makes the locked tests pass, then run the project's test command; all green.
3. Commit the green step with the C32 message, naming the files explicitly:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tdd commit --green T-001 -m "TITLE" src/x.py --apply`
4. Refactor with every test green, one commit per step:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tdd commit --refactor T-001 -m "TITLE" src/x.py --apply`
5. Prove the rules from history and replay the locked tests:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tdd check --replay`
6. Update the trace matrix:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" spec trace SPEC_ID --apply`
7. If a locked test is wrong, open a request; never edit the test:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tdd change-request new --test tests/test_x.py --requirement REQ-X-001 --reason "TEXT" --proposed "TEXT" --feature SPEC_ID --apply`
   The human decides it: `tdd change-request show` prints the phrase `approve|reject CR-<n> <12 hex>` and the human types it in
   the prompt (the hook `tdd-change-request` records it). You never decide a request. After an approval, commit the change
   with `--approved CR-001`.
8. Run the independent check with the `verify` skill.

On a non-zero exit: exit 1 from `tdd check` names the broken rule (a locked test changed, skipped or removed, a skip added,
fewer assertions): restore the test or open a request, never weaken it. Exit 1 from `tdd commit` is a refusal (a file
outside the task, an unlocked test): fix the cause. Exit 2 is a warning: read it and report it.
