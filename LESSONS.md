# Lessons

One dated entry per delivery unit (design requirement LESSON-1). Format: date, unit, what happened, what to do
differently. Newest first.

## 2026-10-30, fix: the reserve lock on Windows

- A thread a test starts must hand its exception back to the test (collect it and assert there is none): the
  failed worker died silently and the run showed only a missing result, eleven numbers from twelve reservations.
- Every exclusive-create lock must treat a denied create on Windows as the previous lock still pending deletion and
  wait inside the same deadline; the ledger lock already did and the reserve lock, written later, copied only half.
  When two modules take a lock the same way, test them against one shared table of failure cases.
- An intermittent defect passes the branch run and fails the merge run on `develop`: read the CI run of every merge
  commit before the next merge, and fix a red `develop` before anything else.

## 2026-10-29, U11 end-to-end self-test

- A skipped test is not a pass: the plugin and copier channel tests were written, skipped for missing tools, and
  stayed unrun until the main session closed them. Close them on a machine that has the tools, with the versions
  recorded.
- Test the behaviour the product defines, not the requirement's wording: "promote refused before the gates are
  green" holds through the required `batuta-gates` check, while a local promotion proves a green head only. The
  gap went into the known limits instead of a test that asserts something the product does not do.
- Point every temporary-folder variable at the temp root (`TMPDIR`, `TEMP` and `TMP`): a shell sets `TMPDIR`, which
  Python reads first, so a test run can write outside the folder it was told to use.
- Install channels are verified from the public default branch with a temporary home and an empty folder, and the
  real home is checked afterwards for leftovers.

## 2026-10-26, fix: the CI matrix

- A local suite on one device and one Python version does not stand in for the CI matrix: `develop` was red in every
  test job for four days and eleven merges, on seven causes no run on the newest interpreter could show. Merge only
  on a green `develop`, and read the merge commit's run before the next merge.
- Parse behaviour, not wording: the unittest verbose line has two forms (3.10 and 3.11 and later) and the CONNECT
  line names a different HTTP version before 3.12. A test that matches one interpreter's text fails on another.
- A watchdog that closes a connection opens a race with the reader: contain it on the reading side (set the flag
  first, treat any later exception as the time-budget error) and treat a body shorter than `Content-Length` as an
  error, never as a complete answer.
- An empty unittest run exits 0 before Python 3.12, so check "no test ran" before "tests passed"; and set
  `gc.auto=0` in test repositories, or a background `git maintenance` races the cleanup of the folder.

## 2026-10-18, U10 documentation wiki

- Put a sentence in quotation marks only after reading it on the cited page: two pages quoted a post with words it
  does not contain. Paraphrase without quotes when the wording is not on the page.
- Capture guide transcripts from real runs in a scratch project, label every stand-in file as a stand-in, and
  generate the reference pages from the code with a test that fails on drift.
- A test that checks for private names must read them from a local file, never from a literal: a docs test that
  listed them reached a pushed branch, so the unit was rebuilt as one clean commit and the first pull request closed.
- Reproduce a suspected bypass with the exact input before reporting it: a candidate finding came from the
  reviewer's own probe mangling backslashes and was retracted.

## 2026-10-18, fix: home boundary and test isolation

- Search upward for a project root through one helper that stops before the home folder, and add a test that no
  module keeps its own parent loop: four copies of the search let a hook climb into the home default and write there.
- Guard the real home for the whole suite: snapshot it, point `HOME` and `USERPROFILE` at a temporary folder, and fail
  by name the test that changes it. The guard needs an ignore list for the host tool's own state, or it fails on it.
- Do not assume `python3` exists on Windows: the default name may be a Store stub. Resolve it, run `--version` with a
  short limit, and warn with the exact fix.
- A test fixture that holds a user path fails the public-content scan; use neutral paths in fixtures.

## 2026-10-16, U9b init, doctor, template, workflow and npx

- A file committed with a project is untrusted input to the uninstaller: validate every path it names, including its
  base folders, or a manifest can point a delete outside the project.
- A CI gate step must fail closed when the script it runs is missing: Python and argparse use exit code 2 for "cannot
  open the script" and "bad arguments", so treating 2 as a warning let a job pass with no gate run.
- Every file a template ships must validate against its own contract in a test: the example task list failed the
  contract that the `spec` area itself reads.
- Re-check each fix from red and from green: the first fix of the manifest finding closed three variants and left a
  variant open.

## 2026-10-16, U9a plugin, skills and hooks.json

- A permissive in-house parser hides defects: nine of thirteen skill front matters were not valid YAML (an unquoted
  colon in the description) and the project's own reader accepted them. Validate against a standard parser and the
  host's own strict validator.
- A green suite does not prove every wired hook runs: one registered entry exited with an `AttributeError` in the
  launcher. Run every hook entry through the launcher in a test, not only resolve its id.
- When the reviewer lacks a tool (the `claude` command here), the main session runs it and records the version and
  the result.

## 2026-10-15, U4 test locks, commit grammar, history check and replay

- Code under test can detect and skip anything that only checks it: a replay worktree, then a recording runner run
  with `-c`, then the parent process. Run the head check as the project's own configured test command in the real
  checkout and read the per-test results from that command's output.
- A locked test passes only with exactly one ok line, the result lines must equal the runner's own summary, and a
  static scan flags patches to the runner. In-process forgery cannot be closed from outside: record it as a known
  limit with its controls instead of adding rounds.
- The checker must read its own settings (lock file, markers, test command) from the range's base commit: a
  committed configuration could move the lock file or empty the marker list.
- Never stop a process you did not start: parallel units share one machine, and a broad kill by pattern stopped a
  sibling unit's suite. Match your own process by id or by your own worktree path.

## 2026-10-15, U13 dispatch lanes

- Charge every call that may have billed, including a crash, a timeout, a resume and each retry of an ambiguous
  transport error; a call that ends without usage figures is charged its full allowed budget. The first version
  recorded cost 0 for a paid run that timed out.
- Test a time budget on real loopback sockets: the first test used a fake connection whose close released the hang,
  so it passed while a trickling server held a real call for ten times the budget.
- Redact at every write of every lane (report, patch, error text, ledger cells); one unredacted write is enough.
- Record a price only when it is confirmed on the provider's own page, and leave it unset when it is not. A review
  that was stopped partway is not a review: replace it with a property-by-property one.

## 2026-10-15, U5 gates, evidence, thresholds, readiness, promote and Stop

- A control that depends on a base revision must say so when it finds none: the threshold ratchet and the routing
  check silently did nothing on a repository whose trunk had another name.
- Read the settings a gate relies on (routing, thresholds) from the base commit, never the working tree, or the
  builder weakens them in the same commit as the evidence.
- Test the honest lifecycle as well as the attacks: a rule written to refuse stale evidence refused evidence that was
  right after a normal spec edit, and had to be narrowed.
- Evidence must name the commit it judges, and a run that ran no test is no evidence: `Ran 0 tests` with
  `OK (skipped=40)` was accepted as a green head.

## 2026-10-14, U3 spec, size, adr, tech, approval, freeze and trace

- An approval must have only writers a human can drive: the first version let an agent create it by three routes. The
  console device and the harness's own prompt handler are the writers; the guards deny agents every other path.
- State what the controls cannot stop: a schema-valid record written by an inline interpreter looks like a captured
  one. It is waived with the guards and human review of the committed record as controls, and listed as a residual
  risk.
- A gate must name a test that the freeze hashes: a command that cannot fail, or a path outside the root, does not
  count as a gate.
- A lint never rejects a document its own contract accepts: "every component has a unit" is a warning, not a failure.

## 2026-10-14, U8 launcher, guards, guard scan and leaks scan

- Test guards with the spellings an agent writes without any wish to evade: a PowerShell assignment prefix, an
  unquoted nested shell, a glob, a copy into the folder, a pipeline into a delete. Eleven critical bypasses came from
  plain one-step forms.
- A guard's own switches are protected assets: deleting `.batuta/` or rewriting its configuration switched off the
  locked-test and brief guards, and a change could disable its own CI twin. Warn on any change to the security keys
  inside the checked range.
- Time every regular expression on a 50,000-character run: a lazy quantifier took 27 seconds on one prompt.
- When a reviewer is stopped by a safety classifier, record the cases as not run and never work around the stop; the
  main session re-runs the stored reproductions on an exported copy. Every command is bounded, and a here-document
  terminator stands alone on its line: two interpreters left reading a broken script spun for 13 hours.

## 2026-10-14, U7 device and preflight

- A port inherits the source's bugs and can drop its guards: the backup secret scan missed any file with a NUL byte
  in its first 4 KB, and the check against following a junction was lost in the port. Re-derive the guard list from
  the source before copying.
- Never follow a link or junction while walking a tree you delete from: a junction nested in an area of an existing
  bundle deleted files outside it, and the first fix closed only the top level.
- Never write into an existing folder that is not your own bundle, and never overwrite a value the user set: report
  it and keep it.
- A timing test must measure what the user sees (the first start after a fresh deploy, no bytecode), not the best of
  CPU and wall time on warm files.

## 2026-10-14, U2 route, brief, report and ledger

- Pick the identifier and create the file inside the same lock, and remove only what you created: two concurrent
  `brief new` calls with one topic let the loser delete the winner's brief while the ledger kept its row.
- The linter and the report checker must read a document the same way: a brief whose deliverables sat only inside a
  code fence passed lint and then made every report check of it defective; a tilde fence was handled by one side only.
- Treat a Windows `PermissionError` on a lock create or a replace as a pending deletion and retry; the first full run
  found it in the concurrent ledger test.
- Fixes need their own re-check: the fixes for two majors produced four new minor findings.

## 2026-10-14, U0r5 additive contracts (C01 1.1, C16 1.1, C34)

- Prove an additive revision on documents, not only on the shipped fixtures: all 500 old fixtures kept their verdicts
  and still three documents valid under 1.0 failed at the head (a false scope overlap, a free-form key the old
  schema allowed, an indented fence).
- Write the contract for an external format from the vendor's reference page read on a recorded date, and let the
  reviewer compare the field list with the page.
- When the change contradicts an existing assertion, edit it minimally, say so in the decision record and have the
  reviewer accept the deviation; never loosen a check of another contract to pass.

## 2026-10-13, U0 data contracts C01 to C33

- Re-derive every contract from the method as it stands at freeze: the first round found two contracts describing
  artifacts the method had withdrawn, and two contracts that refused the very brief and report that reviewed them.
  Run each contract against the real artifacts in use, not only fixtures.
- A contract that mirrors a living reference tool needs a differential test against that tool and a dated record of
  every deliberate difference: the tool gained a required section hours after the head and every valid fixture became
  defective.
- Never expand an environment-variable name before validating, and quote values as written in every error: validating
  after expansion printed a secret value in a message.
- Give every finding a test that fails on the pre-fix tree, and assert the specific cause: a restored red test passed
  by an accident of wording and proved nothing.

## 2026-10-12, U6 context and memory

- A generator deletes only files it marked as generated: `memory index --apply` removed hand-written pages in the
  topics folder. Mark generated files with a header line and test an unmarked legacy file.
- A budget check counts what loads, not what is in the file: it ignored `@` imports, so a core of eight bytes with a
  100 KB import passed a 7000-byte budget. Follow imports to the host's depth limit and stop on a cycle.
- Test a budget at the boundary and in bytes (7000 passes, 7001 fails), with multi-byte characters.
- A public repository's tests must not spell the private names they guard against, and a commit that does is
  rewritten before any push.

## 2026-10-11, U1 repository skeleton

- Scaffold defaults must not claim checks that do not exist: the README lists install channels as planned and
  names the one area that ships, so the front page cannot get ahead of the code.
- A dispatcher that imports every area module must treat one broken module as a warning, never a crash; the
  parallel units add areas independently and one bad import must not take the CLI down.
- A guard script must not exempt itself: build fixtures from code points and string pieces so the script scans
  its own source and tests with the same rules as everything else.
