## Areas `route`, `brief` and `report`: delegation with a checkable report

A delegation is a brief in, a report out, and a row in the ledger that says how it ended. Roles and models come from the
configuration (C01), briefs from `templates/brief.md`, and nothing is accepted on the agent's word: the report is checked
against the brief.

```
python scripts/batuta.py route show [--root DIR]
python scripts/batuta.py route check [--root DIR] [--agents-dir DIR]
python scripts/batuta.py brief new --slug S --topic T --agent A --title "..." [--model M] [--kind K] [--sizing PATH] [--report PATH] [--root DIR] [--date YYYY-MM-DD]
python scripts/batuta.py brief lint BRIEF [--root DIR]
python scripts/batuta.py report check --brief BRIEF [REPORT] [--root DIR]
python scripts/batuta.py report ledger-status [--ledger FILE] [--root DIR] [--write]
python scripts/batuta.py report hook-subagent-stop < payload.json
```

- Where things live: briefs in `<coordination_root>/delegation/<id>.brief.md`, the ledger in
  `<coordination_root>/delegation/ledger.md` (`coordination_root` is `.batuta` by default). The ledger is one Markdown
  table (C04): ID, Agent, Model, Brief, Report, Status, Accepted, then the optional Provider, Tokens in, Tokens out, Cost
  USD, Superseded by and Notes. Status is one of drafted, pending, launched, complete, incomplete, defective, accepted,
  superseded, lost, timeout, error, over-budget; Accepted is `yes` or `no` (`y` and `n` are read, never written). The
  evidence of an acceptance goes in Notes.
- `route check` fails when an agent file does not satisfy C18, when its `model` differs from the model of the role of the
  same name, or when its role runs on Haiku and the file lacks `omitClaudeMd: true`. An agent file without a role is a
  warning.
- `brief new` takes the model and the kind from the agent (searcher: haiku, lookup; runner: haiku, run; implementer: sonnet,
  implement; doc-writer: sonnet, docs; reviewer: opus, review; general-purpose needs `--model` and is research). The kinds
  implement, job and skeleton carry the contract-first sections. `brief lint` refuses a brief with an unfilled
  `<fill: ...>` slot, a missing section or header field, or a check without a backticked command, and warns about an
  escalation, the fable model, more than eight deliverables and a write scope that overlaps another open brief.
- `report check` exits 0 when every deliverable is DONE with evidence, 1 when the report is defective (a missing row, a
  placeholder, a bad status, a missing Red run or Production path section), 2 when it is well formed but some rows are
  PARTIAL or BLOCKED. `report ledger-status` is a dry run unless `--write` is given.
- The SubagentStop decision holds a briefed agent once until its report passes: it blocks (`decision: block`, exit 0)
  when the final message lacks the `BRIEF:` and `REPORT:` lines or the report is missing, defective or incomplete. It
  allows an agent that was not briefed, and on the second attempt it allows and appends a dated UNVERIFIED line to
  `<coordination_root>/delegation/unverified.log`, so it never loops. An internal error allows the stop. The plugin's hooks
  file registers it under the id `subagent-stop`.
- Ledger writes are atomic: the new file is written next to the ledger and replaced in one step under a lock file, the
  ledger is re-read just before the replace so a row a concurrent writer added is kept, and a result that does not satisfy
  C04 is refused with the file untouched.
