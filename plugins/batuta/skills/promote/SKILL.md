---
name: promote
description: Use when every gate through L9-promote is green and a human wants to merge a unit: merges only on green checks for the exact head commit.
disable-model-invocation: true
allowed-tools: Bash(python *) Read Grep Glob
argument-hint: <feature id>
---

# Promote: merge only on green

Gate: L9-promote (critical: the independent check is the reviewer on the strong model, see the `verify` skill).

1. Release rules: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate check FEATURE --release`
   (every component of the readiness document real, release evidence current for the head).
2. Walking skeleton and contract tests: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" skeleton check --release`
3. History and replay: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" tdd check --replay`
4. Ratcheting thresholds: `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate thresholds --check`
5. Print the merge command for a pull request (nothing is merged yet):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate promote --repo OWNER/REPO --pr N --require batuta-gates`
   For a repository without CI, promote a local branch with test output that names the full head SHA:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate promote --branch task/x --into develop --local-evidence FILE`
6. Only when the human says to merge, run the same command with `--apply`. It merges only on green for that head, never
   overrides a failed or pending check and never switches branches.
7. Then run the `lessons` skill (L10-lessons).

On a non-zero exit: exit 1 is a refusal (a failed or pending check, a head that moved since review, evidence that does not
name the head): fix the cause and start again from step 1; never merge by another route. Exit 2 is a warning or an honest
partial: it is not green, so do not apply.
