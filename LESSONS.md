# Lessons

One dated entry per delivery unit (design requirement LESSON-1), each lesson one line in the lesson line format of
contract C19: `- date | unit | lesson | action`. Newest first.

## 2026-10-30, fix: the reserve lock on Windows

- 2026-10-30 | fix: the reserve lock on Windows | A thread a test starts that raises dies silently, and the run showed only a missing result, eleven numbers from twelve reservations. | Hand the worker's exception back to the test (collect it and assert there is none).
- 2026-10-30 | fix: the reserve lock on Windows | The ledger lock already waited on a denied create on Windows, and the reserve lock, written later, copied only half of that rule. | Treat a denied exclusive create on Windows as the previous lock still pending deletion and wait inside the same deadline; when two modules take a lock the same way, test them against one shared table of failure cases.
- 2026-10-30 | fix: the reserve lock on Windows | An intermittent defect passes the branch run and fails the merge run on `develop`. | Read the CI run of every merge commit before the next merge, and fix a red `develop` before anything else.

## 2026-10-29, U11 end-to-end self-test

- 2026-10-29 | U11 end-to-end self-test | A skipped test is not a pass: the plugin and copier channel tests were written, skipped for missing tools, and stayed unrun until the main session closed them. | Close skipped tests on a machine that has the tools, with the versions recorded.
- 2026-10-29 | U11 end-to-end self-test | The requirement's wording is not the behaviour: "promote refused before the gates are green" holds through the required `batuta-gates` check, while a local promotion proves a green head only. | Test the behaviour the product defines, and put the gap into the known limits instead of a test that asserts something the product does not do.
- 2026-10-29 | U11 end-to-end self-test | A shell sets `TMPDIR`, which Python reads first, so a test run can write outside the folder it was told to use. | Point every temporary-folder variable (`TMPDIR`, `TEMP` and `TMP`) at the temp root.
- 2026-10-29 | U11 end-to-end self-test | An install channel can look fine from a working tree and still fail from the public repository. | Verify install channels from the public default branch with a temporary home and an empty folder, and check the real home afterwards for leftovers.

## 2026-10-26, fix: the CI matrix

- 2026-10-26 | fix: the CI matrix | A local suite on one device and one Python version does not stand in for the CI matrix: `develop` was red in every test job for four days and eleven merges, on seven causes no run on the newest interpreter could show. | Merge only on a green `develop`, and read the merge commit's run before the next merge.
- 2026-10-26 | fix: the CI matrix | The unittest verbose line has two forms (3.10 and 3.11 and later) and the CONNECT line names a different HTTP version before 3.12, so a test that matches one interpreter's text fails on another. | Parse behaviour, not wording.
- 2026-10-26 | fix: the CI matrix | A watchdog that closes a connection opens a race with the reader. | Contain it on the reading side (set the flag first, treat any later exception as the time-budget error) and treat a body shorter than `Content-Length` as an error, never as a complete answer.
- 2026-10-26 | fix: the CI matrix | An empty unittest run exits 0 before Python 3.12, and a background `git maintenance` races the cleanup of a test repository's folder. | Check "no test ran" before "tests passed", and set `gc.auto=0` in test repositories.

## 2026-10-18, U10 documentation wiki

- 2026-10-18 | U10 documentation wiki | Two pages quoted a post with words it does not contain. | Put a sentence in quotation marks only after reading it on the cited page, and paraphrase without quotes when the wording is not on the page.
- 2026-10-18 | U10 documentation wiki | Guide transcripts written by hand drift from the product. | Capture guide transcripts from real runs in a scratch project, label every stand-in file as a stand-in, and generate the reference pages from the code with a test that fails on drift.
- 2026-10-18 | U10 documentation wiki | A docs test that listed private names reached a pushed branch, so the unit was rebuilt as one clean commit and the first pull request closed. | A test that checks for private names reads them from a local file, never from a literal.
- 2026-10-18 | U10 documentation wiki | A candidate finding came from the reviewer's own probe mangling backslashes and was retracted. | Reproduce a suspected bypass with the exact input before reporting it.

## 2026-10-18, fix: home boundary and test isolation

- 2026-10-18 | fix: home boundary and test isolation | Four copies of the project root search let a hook climb into the home default and write there. | Search upward through one helper that stops before the home folder, and add a test that no module keeps its own parent loop.
- 2026-10-18 | fix: home boundary and test isolation | A test run can change the real home without anyone noticing. | Guard the real home for the whole suite: snapshot it, point `HOME` and `USERPROFILE` at a temporary folder, and fail by name the test that changes it; give the guard an ignore list for the host tool's own state.
- 2026-10-18 | fix: home boundary and test isolation | On Windows the default name `python3` may be a Store stub. | Do not assume `python3` exists: resolve it, run `--version` with a short limit, and warn with the exact fix.
- 2026-10-18 | fix: home boundary and test isolation | A test fixture that holds a user path fails the public-content scan. | Use neutral paths in fixtures.

## 2026-10-16, U9b init, doctor, template, workflow and npx

- 2026-10-16 | U9b init, doctor, template, workflow and npx | A file committed with a project is untrusted input to the uninstaller, and a manifest can point a delete outside the project. | Validate every path the manifest names, including its base folders.
- 2026-10-16 | U9b init, doctor, template, workflow and npx | Python and argparse use exit code 2 for "cannot open the script" and "bad arguments", so treating 2 as a warning let a job pass with no gate run. | A CI gate step fails closed when the script it runs is missing.
- 2026-10-16 | U9b init, doctor, template, workflow and npx | The example task list failed the contract that the `spec` area itself reads. | Every file a template ships validates against its own contract in a test.
- 2026-10-16 | U9b init, doctor, template, workflow and npx | The first fix of the manifest finding closed three variants and left a variant open. | Re-check each fix from red and from green.

## 2026-10-16, U9a plugin, skills and hooks.json

- 2026-10-16 | U9a plugin, skills and hooks.json | Nine of thirteen skill front matters were not valid YAML (an unquoted colon in the description) and the project's own permissive reader accepted them. | Validate against a standard parser and the host's own strict validator.
- 2026-10-16 | U9a plugin, skills and hooks.json | One registered hook entry exited with an `AttributeError` in the launcher while the suite was green. | Run every hook entry through the launcher in a test, not only resolve its id.
- 2026-10-16 | U9a plugin, skills and hooks.json | The reviewer lacked a tool (the `claude` command here). | The main session runs it and records the version and the result.

## 2026-10-15, U4 test locks, commit grammar, history check and replay

- 2026-10-15 | U4 test locks, commit grammar, history check and replay | Code under test can detect and skip anything that only checks it: a replay worktree, then a recording runner run with `-c`, then the parent process. | Run the head check as the project's own configured test command in the real checkout and read the per-test results from that command's output.
- 2026-10-15 | U4 test locks, commit grammar, history check and replay | In-process forgery cannot be closed from outside. | Require exactly one ok line per locked test, equal result lines and the runner's own summary, scan statically for runner patches, and record the forgery as a known limit with its controls instead of adding rounds.
- 2026-10-15 | U4 test locks, commit grammar, history check and replay | A committed configuration could move the lock file or empty the marker list. | The checker reads its own settings (lock file, markers, test command) from the range's base commit.
- 2026-10-15 | U4 test locks, commit grammar, history check and replay | Parallel units share one machine, and a broad kill by pattern stopped a sibling unit's suite. | Never stop a process you did not start; match your own process by id or by your own worktree path.

## 2026-10-15, U13 dispatch lanes

- 2026-10-15 | U13 dispatch lanes | The first version recorded cost 0 for a paid run that timed out. | Charge every call that may have billed, including a crash, a timeout, a resume and each retry of an ambiguous transport error, and charge a call that ends without usage figures its full allowed budget.
- 2026-10-15 | U13 dispatch lanes | The first time-budget test used a fake connection whose close released the hang, so it passed while a trickling server held a real call for ten times the budget. | Test a time budget on real loopback sockets.
- 2026-10-15 | U13 dispatch lanes | One unredacted write is enough to leak a secret. | Redact at every write of every lane (report, patch, error text, ledger cells).
- 2026-10-15 | U13 dispatch lanes | A review that was stopped partway is not a review. | Record a price only when it is confirmed on the provider's own page and leave it unset when it is not, and replace a stopped review with a property-by-property one.

## 2026-10-15, U5 gates, evidence, thresholds, readiness, promote and Stop

- 2026-10-15 | U5 gates, evidence, thresholds, readiness, promote and Stop | The threshold ratchet and the routing check silently did nothing on a repository whose trunk had another name. | A control that depends on a base revision says so when it finds none.
- 2026-10-15 | U5 gates, evidence, thresholds, readiness, promote and Stop | A builder could weaken routing or thresholds in the same commit as the evidence. | Read the settings a gate relies on (routing, thresholds) from the base commit, never the working tree.
- 2026-10-15 | U5 gates, evidence, thresholds, readiness, promote and Stop | A rule written to refuse stale evidence refused evidence that was right after a normal spec edit, and had to be narrowed. | Test the honest lifecycle as well as the attacks.
- 2026-10-15 | U5 gates, evidence, thresholds, readiness, promote and Stop | `Ran 0 tests` with `OK (skipped=40)` was accepted as a green head. | Evidence names the commit it judges, and a run that ran no test is no evidence.

## 2026-10-14, U3 spec, size, adr, tech, approval, freeze and trace

- 2026-10-14 | U3 spec, size, adr, tech, approval, freeze and trace | The first version let an agent create an approval by three routes. | An approval has only writers a human can drive: the console device and the harness's own prompt handler, with the guards denying agents every other path.
- 2026-10-14 | U3 spec, size, adr, tech, approval, freeze and trace | A schema-valid record written by an inline interpreter looks like a captured one. | State what the controls cannot stop: waive it with the guards and human review of the committed record as controls, and list it as a residual risk.
- 2026-10-14 | U3 spec, size, adr, tech, approval, freeze and trace | A command that cannot fail, or a path outside the root, does not count as a gate. | A gate names a test that the freeze hashes.
- 2026-10-14 | U3 spec, size, adr, tech, approval, freeze and trace | A lint that rejects what its own contract accepts is wrong. | A lint never rejects a document its own contract accepts: "every component has a unit" is a warning, not a failure.

## 2026-10-14, U8 launcher, guards, guard scan and leaks scan

- 2026-10-14 | U8 launcher, guards, guard scan and leaks scan | Eleven critical bypasses came from plain one-step forms: a PowerShell assignment prefix, an unquoted nested shell, a glob, a copy into the folder, a pipeline into a delete. | Test guards with the spellings an agent writes without any wish to evade.
- 2026-10-14 | U8 launcher, guards, guard scan and leaks scan | Deleting `.batuta/` or rewriting its configuration switched off the locked-test and brief guards, and a change could disable its own CI twin. | Treat a guard's own switches as protected assets and warn on any change to the security keys inside the checked range.
- 2026-10-14 | U8 launcher, guards, guard scan and leaks scan | A lazy quantifier took 27 seconds on one prompt. | Time every regular expression on a 50,000-character run.
- 2026-10-14 | U8 launcher, guards, guard scan and leaks scan | Two interpreters left reading a broken here-document spun for 13 hours, and a reviewer was stopped by a safety classifier. | Bound every command and keep a here-document terminator alone on its line; when a reviewer is stopped, record the cases as not run, never work around the stop, and have the main session re-run the stored reproductions on an exported copy.

## 2026-10-14, U7 device and preflight

- 2026-10-14 | U7 device and preflight | A port inherits the source's bugs and can drop its guards: the backup secret scan missed any file with a NUL byte in its first 4 KB, and the check against following a junction was lost in the port. | Re-derive the guard list from the source before copying.
- 2026-10-14 | U7 device and preflight | A junction nested in an area of an existing bundle deleted files outside it, and the first fix closed only the top level. | Never follow a link or junction while walking a tree you delete from.
- 2026-10-14 | U7 device and preflight | Writing into a folder that is not your own bundle, or over a value the user set, destroys the user's work. | Never write into an existing folder that is not your own bundle and never overwrite a value the user set: report it and keep it.
- 2026-10-14 | U7 device and preflight | A timing test on warm files reported the best of CPU and wall time, not what the user sees. | Measure the first start after a fresh deploy, with no bytecode.

## 2026-10-14, U2 route, brief, report and ledger

- 2026-10-14 | U2 route, brief, report and ledger | Two concurrent `brief new` calls with one topic let the loser delete the winner's brief while the ledger kept its row. | Pick the identifier and create the file inside the same lock, and remove only what you created.
- 2026-10-14 | U2 route, brief, report and ledger | A brief whose deliverables sat only inside a code fence passed lint and then made every report check of it defective; a tilde fence was handled by one side only. | The linter and the report checker read a document the same way.
- 2026-10-14 | U2 route, brief, report and ledger | The first full run found a Windows `PermissionError` on a lock create or a replace in the concurrent ledger test. | Treat it as a pending deletion and retry.
- 2026-10-14 | U2 route, brief, report and ledger | The fixes for two majors produced four new minor findings. | Give fixes their own re-check.

## 2026-10-14, U0r5 additive contracts (C01 1.1, C16 1.1, C34)

- 2026-10-14 | U0r5 additive contracts (C01 1.1, C16 1.1, C34) | All 500 old fixtures kept their verdicts and still three documents valid under 1.0 failed at the head (a false scope overlap, a free-form key the old schema allowed, an indented fence). | Prove an additive revision on documents, not only on the shipped fixtures.
- 2026-10-14 | U0r5 additive contracts (C01 1.1, C16 1.1, C34) | A contract for an external format drifts from the vendor's page. | Write it from the vendor's reference page read on a recorded date, and let the reviewer compare the field list with the page.
- 2026-10-14 | U0r5 additive contracts (C01 1.1, C16 1.1, C34) | A change can contradict an existing assertion of another contract. | Edit the assertion minimally, say so in the decision record and have the reviewer accept the deviation; never loosen a check of another contract to pass.

## 2026-10-13, U0 data contracts C01 to C33

- 2026-10-13 | U0 data contracts C01 to C33 | The first round found two contracts describing artifacts the method had withdrawn, and two contracts that refused the very brief and report that reviewed them. | Re-derive every contract from the method as it stands at freeze and run each contract against the real artifacts in use, not only fixtures.
- 2026-10-13 | U0 data contracts C01 to C33 | The tool a contract mirrors gained a required section hours after the head and every valid fixture became defective. | Give a contract that mirrors a living reference tool a differential test against that tool and a dated record of every deliberate difference.
- 2026-10-13 | U0 data contracts C01 to C33 | Validating after expansion of an environment-variable name printed a secret value in a message. | Never expand an environment-variable name before validating, and quote values as written in every error.
- 2026-10-13 | U0 data contracts C01 to C33 | A restored red test passed by an accident of wording and proved nothing. | Give every finding a test that fails on the pre-fix tree and assert the specific cause.

## 2026-10-12, U6 context and memory

- 2026-10-12 | U6 context and memory | `memory index --apply` removed hand-written pages in the topics folder. | A generator deletes only files it marked as generated: mark generated files with a header line and test an unmarked legacy file.
- 2026-10-12 | U6 context and memory | The budget check ignored `@` imports, so a core of eight bytes with a 100 KB import passed a 7000-byte budget. | A budget check counts what loads, not what is in the file: follow imports to the host's depth limit and stop on a cycle.
- 2026-10-12 | U6 context and memory | A budget can be off by one at its edge, or miscount multi-byte characters. | Test a budget at the boundary and in bytes (7000 passes, 7001 fails), with multi-byte characters.
- 2026-10-12 | U6 context and memory | A public repository's tests that spell the private names they guard against publish them. | Never spell the private names in a test, and rewrite a commit that does before any push.

## 2026-10-11, U1 repository skeleton

- 2026-10-11 | U1 repository skeleton | Scaffold defaults that claim checks which do not exist put the front page ahead of the code. | The README lists install channels as planned and names the one area that ships.
- 2026-10-11 | U1 repository skeleton | The parallel units add areas independently, and one bad import must not take the CLI down. | A dispatcher that imports every area module treats one broken module as a warning, never a crash.
- 2026-10-11 | U1 repository skeleton | A guard script that exempts itself scans nothing of its own source. | Build fixtures from code points and string pieces so the script scans its own source and tests with the same rules as everything else.
