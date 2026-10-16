---
name: lessons
description: Use when a unit's build has passed, to record its dated lesson (L10-lessons) and check LESSONS.md and overdue ADR reviews.
allowed-tools: Bash(python *) Read Grep Glob Edit
argument-hint: <unit>
---

# Record the lesson of a unit

Gate: L10-lessons. Every unit with a passed build has a dated lesson.

1. Add an entry to `LESSONS.md`, newest first: a heading `## YYYY-MM-DD, <unit>` and lines that start with `- ` (C19): what
   happened and what to do differently. Say it generically and concretely; no private names, no machine paths.
2. Check that every unit with a passed build has a lesson line:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" lessons check`
3. Revisit the decisions whose review trigger fired; a change goes through a new ADR that supersedes the old one:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" adr lint`
4. Record the gate after the `verify` skill passed (a dry run until you add `--apply`):
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/batuta.py" gate status FEATURE --set L10-lessons=passed`

On a non-zero exit: exit 1 from `lessons check` names the unit without a lesson or a blank field: write the line. Exit 1 from
`adr lint` is a malformed ADR or a broken supersession link: fix it. Exit 2 is a warning (an overdue review): schedule the
review or write the new ADR.
