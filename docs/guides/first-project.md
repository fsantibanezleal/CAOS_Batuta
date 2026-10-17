# First project walkthrough

This guide builds a one-function project end to end: initialize, write a spec, approve it, write the failing test, lock it,
make it pass, run the checks and prepare the promotion. Every block of output is real: it was captured with
`python plugins/batuta/scripts/batuta.py` run in a scratch git repository created under a temporary folder. Two edits were made
to the captured text and nothing else: the scratch folder's absolute path is shown as `<project>` and the operating-system
account name as `<user>`. In the transcripts `batuta` stands for `python <plugin folder>/scripts/batuta.py`, and every command
runs from the project root.

The walkthrough follows the lifecycle of [the lifecycle page](../concepts/lifecycle.md) in the order the tools enforce, but a
small change like this one passes only the gates that apply; the point is the mechanics, not the ceremony.

Before you start: a git repository with a first commit identity configured, Python 3.10 or newer, and the plugin installed
([install guide](install.md)) or a checkout of this repository.

```
git init -b main
git config core.autocrlf false
```

## 1. Initialize the project

A dry run first. Nothing is written until `--apply`:

```
batuta init project --target . --var project_name=greeter
NEW .batuta/batuta.json (.batuta/batuta.json)
NEW .claude/settings.json (.claude/settings.json)
NEW .github/workflows/batuta-gates.yml (.github/workflows/batuta-gates.yml)
NEW AGENTS.md (AGENTS.md)
NEW CLAUDE.md (CLAUDE.md)
NEW specs/000-foundation/constitution.md (specs/000-foundation/constitution.md)
NEW specs/000-foundation/thresholds.json (specs/000-foundation/thresholds.json)
NEW specs/001-example-feature/plan.md (specs/001-example-feature/plan.md)
NEW specs/001-example-feature/spec.md (specs/001-example-feature/spec.md)
NEW specs/001-example-feature/status.md (specs/001-example-feature/status.md)
NEW specs/001-example-feature/tasks.md (specs/001-example-feature/tasks.md)
NEW tests/__init__.py (tests/__init__.py)
NEW tests/test_foundation.py (tests/test_foundation.py)
SKIP dry run: nothing written (use --apply)
init project: 13 of 13 file(s) to write (dry run)
```

Then `batuta init project --target . --var project_name=greeter --apply` writes the 13 files and an install manifest
(`.batuta/installed.json`) and ends with `init project: 13 of 13 file(s) written in <project>`. The files that matter:

- `.batuta/batuta.json` holds the project configuration (contract C01 1.1): the role table, caps, gates, budgets and the
  `tdd.test_command` that CI and the replay both run, `python -m unittest discover -s tests -t . -v`. Roots are `$BATUTA_TEMP`,
  `$BATUTA_DATA` and `$BATUTA_WORKTREES`, never a path.
- `.claude/settings.json` adds three deny rules: `Edit(/specs/**/approvals/**)`,
  `Edit(/specs/**/test-change-requests.md)` and `Edit(/.batuta/test-locks.json)`.
- `AGENTS.md` and a short `CLAUDE.md` carry the workflow and the rules for agents; `CLAUDE.md` is 1587 bytes against the
  7000-byte budget (`context check`).
- `specs/000-foundation/` has the constitution and `thresholds.json` (a line coverage threshold of 80 and an empty history).
- `specs/001-example-feature/` is a valid example; `tests/test_foundation.py` gives CI real tests from the first commit.

Commit it, then branch (the rules of the project forbid work directly on `main`):

```
git add -A && git commit -m "chore: adopt Batuta"
git checkout -b task/greeting
```

## 2. Create the spec

```
batuta spec new --title "Greeting" --tier S
NEW 002-greeting/spec.md (specs/002-greeting/spec.md)
NEW 002-greeting/tasks.md (specs/002-greeting/tasks.md)
NEW 002-greeting/approvals/ (specs/002-greeting/approvals/.gitkeep)
NEW 002-greeting/evidence/ (specs/002-greeting/evidence/.gitkeep)
SKIP dry run: nothing written; pass --apply to create the files
spec new: 0 ok, 0 warning(s), 0 failure(s)
```

Run it again with `--apply`. Tier S needs only a spec and tasks (see [spec-driven development](../concepts/spec-driven-development.md)).
Fill `specs/002-greeting/spec.md`: the problem, the scope, two EARS requirements each with a gate, no interfaces, the edge
cases. The requirements table:

```
| Id | Kind | EARS text | Gate | Verification | Status |
|---|---|---|---|---|---|
| REQ-GREET-001 | event | When `greet` is called with a non-blank name, the system shall return `Hello, <name>!`. | `python -m unittest tests/test_greeter.py` | unit test | active |
| REQ-GREET-002 | unwanted | If `greet` is called with a blank name, then the system shall raise `ValueError`. | `python -m unittest tests/test_greeter.py` | unit test | active |
```

and `tasks.md`:

```
| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |
|---|---|---|---|---|---|---|---|
| T-001 | Greet by name | REQ-GREET-001, REQ-GREET-002 | - | - | | implementer | - |
```

Set `status: Review` in the front matter. The lint passes only when a gate names a test that exists, so the first run warns:

```
batuta spec lint --spec 002-greeting
WARN specs/002-greeting/spec.md: the Gate of REQ-GREET-001 names tests/test_greeter.py, which does not exist (the freeze hashes every named test) (specs/002-greeting/spec.md)
WARN specs/002-greeting/spec.md: the Gate of REQ-GREET-002 names tests/test_greeter.py, which does not exist (the freeze hashes every named test) (specs/002-greeting/spec.md)
spec lint: 0 ok, 2 warning(s), 0 failure(s)
```

(exit code 2: a warning is never silent and never a pass).

## 3. Write the failing test

The test file carries one `# REQ:` marker line that ties it to the requirements (the same convention `tdd lock` and
`spec trace` read), and it imports `greeter`, which does not exist yet:

```python
import unittest

from greeter import greet


# REQ: REQ-GREET-001, REQ-GREET-002
class GreetTests(unittest.TestCase):
    def test_greets_by_name(self):
        self.assertEqual(greet("Ada"), "Hello, Ada!")

    def test_trims_the_name(self):
        self.assertEqual(greet("  Ada "), "Hello, Ada!")

    def test_blank_name_is_refused(self):
        with self.assertRaises(ValueError):
            greet("   ")
```

Running the project's test command fails, as a red test should (the tail of the real output):

```
ModuleNotFoundError: No module named 'greeter'

Ran 4 tests in 0.001s

FAILED (errors=1)
```

A red test should fail for the missing behavior, not for a typo; here the whole module fails to import because the code
under test does not exist, which `tdd check --replay` accepts below as a test of its own that errored.

Now the lint passes and the trace is `ok`:

```
batuta spec lint --spec 002-greeting
OK 002-greeting satisfies C05 and the spec rules (Review, tier S) (specs/002-greeting/spec.md)
spec lint: 1 ok, 0 warning(s), 0 failure(s)

batuta spec trace 002-greeting
NEW trace.json for 002-greeting: 2 requirement(s), ok=true (dry run; --apply writes it) (specs/002-greeting/trace.json)
```

## 4. Approve the spec (a person types the phrase)

`spec show` prints what the approval hashes and the phrase to type:

```
batuta spec show 002-greeting
OK hashes specs/002-greeting/spec.md (6b4ab454260c) (specs/002-greeting/spec.md)
OK hashes tests/test_greeter.py (fd508c2222be) (tests/test_greeter.py)
OK approval phrase to type: approve 002-greeting 6b4ab454260c
spec show: 3 ok, 0 warning(s), 0 failure(s)
```

In a Claude Code session with the plugin the person types `approve 002-greeting 6b4ab454260c` as a prompt, and the
UserPromptSubmit hook records it. An agent never types it and cannot write it: the approvals guard denies every route. To
show the same mechanism outside a session, this transcript feeds the handler the payload Claude Code would send (a person
at a terminal uses `batuta spec approve 002-greeting` instead, which reads the phrase from the console). The dry run first:

```
batuta spec hook-approval < payload.json
OK would record the approval of 002-greeting at 6b4ab454260c (dry run: nothing written)
OK would hash specs/002-greeting/spec.md (specs/002-greeting/spec.md)
OK would hash tests/test_greeter.py (tests/test_greeter.py)
SKIP dry run: nothing written; the approval is recorded only by the hook handler run by the harness
spec hook-approval (dry run): 3 ok, 0 warning(s), 0 failure(s)
```

where `payload.json` is `{"session_id":"s1","cwd":".","hook_event_name":"UserPromptSubmit","prompt":"approve 002-greeting
6b4ab454260c"}`. The handler, run by the harness, records the approval and answers Claude Code:

```
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "NEW approval recorded for 002-greeting at 6b4ab454260c; OK hashed specs/002-greeting/spec.md; OK hashed tests/test_greeter.py"}, "systemMessage": "NEW approval recorded for 002-greeting at 6b4ab454260c; OK hashed specs/002-greeting/spec.md; OK hashed tests/test_greeter.py"}
```

The record is `specs/002-greeting/approvals/<stamp>.json` (shown in full in
[spec-driven development](../concepts/spec-driven-development.md)). The freeze is now checkable at any time:

```
batuta spec freeze --check 002-greeting
OK VALID 002-greeting: specs/002-greeting/approvals/20261017T022038112820Z.json matches the 2 hashed file(s) (specs/002-greeting/approvals/20261017T022038112820Z.json)
spec freeze --check: 1 ok, 0 warning(s), 0 failure(s)
```

Commit the spec, the tasks and the approval (not the test yet: the red commit adds it). The scratch repository also has a
`.gitignore` holding `__pycache__/`:

```
git add .gitignore specs/002-greeting
git commit -m "docs(spec): 002-greeting spec, tasks and typed approval"
```

## 5. Lock the test and commit red

```
batuta tdd lock --task T-001 tests/test_greeter.py --apply
NEW locked tests/test_greeter.py for T-001 (fd508c2222be) (tests/test_greeter.py)
OK wrote 1 entry to .batuta/test-locks.json
tdd lock: done

batuta tdd commit --red T-001 -m "Greet by name" tests/test_greeter.py --apply
OK staging tests/test_greeter.py (tests/test_greeter.py)
OK staging .batuta/test-locks.json (.batuta/test-locks.json)
OK committing: [red] T-001 Greet by name
OK committed 0aa4235: [red] T-001 Greet by name
tdd commit: done

batuta tdd check
OK 1 of 1 locked test file(s) match the lock at 0aa4235
OK 3 commit(s) checked against the red and green rules
tdd check: ok
```

From here the guard `guard-locked-tests` denies any edit of `tests/test_greeter.py`. Shown by running the guard on the payload
of an Edit tool call (what Claude Code would send before the edit; the message is shortened here, the guard prints it in full):

```
batuta guard locked-tests --payload edit.json
REFUSED BLOCKED by guard-locked-tests: tests/test_greeter.py is a locked test (task T-001). A locked test changes only through an approved change request: file one with `tdd change-request new` (it appends an `open` row ... to specs/<feature>/test-change-requests.md (C33)); never edit that table by hand. The human decides the request with `tdd change-request decide`; after approval the tdd area re-locks the test.
guard locked-tests: deny
```

## 6. Make it pass and commit green

`greeter.py`:

```python
def greet(name: str) -> str:
    """Return the greeting for a name; a blank name is refused."""
    name = name.strip()
    if not name:
        raise ValueError("name must not be blank")
    return f"Hello, {name}!"
```

The test run is green (6 tests: the 3 of the greeter and the 3 of the foundation). Commit the step and prove the history:

```
batuta tdd commit --green T-001 -m "Greet by name" greeter.py --apply
OK committing: [green] T-001 Greet by name
OK committed 5f79a9d: [green] T-001 Greet by name
tdd commit: done

BATUTA_TEMP=<a folder outside the repository> batuta tdd check --replay
OK 1 of 1 locked test file(s) match the lock at 5f79a9d
OK red commit 0aa4235 (T-001): tests/test_greeter.py fails at the red commit (exit 1) (tests/test_greeter.py)
OK 4 commit(s) checked against the red and green rules
tdd check: ok
```

`--replay` checked the red commit out in a temporary worktree under the temp root and confirmed the test fails there, then ran
the project's real test command at the head ([test-driven development](../concepts/test-driven-development.md)). Update the
trace: `batuta spec trace 002-greeting --apply` writes `specs/002-greeting/trace.json` with both requirements, their gate,
test and task, and `ok: true`.

## 7. Gates and evidence

The status file of the feature records each gate as pending. `spec new` does not create it (the example feature has one), so
copy `specs/001-example-feature/status.md`, set `feature: 002-greeting`, and:

```
batuta gate status 002-greeting --set L7-build=passed
REFUSED L7-build: the earlier gate L0-understand is pending; gates pass in order
nothing changed
```

Gates pass in order and only with evidence from an agent that did not build the result. For L0 the independent check is the
adversary on the routine model: the `verify` skill launches it on a brief and it writes `specs/002-greeting/evidence/L0-understand.md`
(contract C09). In this walkthrough the evidence file was written by hand in the template's format, as a stand-in for that
agent, to show the checker; it is not an independent check and a real project must not do it:

```
batuta gate evidence-lint specs/002-greeting/evidence/L0-understand.md
OK valid evidence: gate L0-understand, verdict PASS, adversary on sonnet (specs/002-greeting/evidence/L0-understand.md)
evidence is valid

batuta gate status 002-greeting --set L0-understand=passed --apply
CHANGED L0-understand: pending -> passed (specs/002-greeting/status.md)
CHANGED phase is now L1-size (specs/002-greeting/status.md)
002-greeting phase L1-size

batuta gate check 002-greeting
OK specs/000-foundation/thresholds.json: 1 threshold(s), 0 history entries, ratchet holds (specs/000-foundation/thresholds.json)
OK gate L0-understand passed with adversary evidence (sonnet, verdict PASS) (specs/002-greeting/evidence/L0-understand.md)
SKIP no readiness document yet (before L6-skeleton)
002-greeting: every gate rule holds
```

Repeat for each gate that applies; a gate that does not apply (a spec with no interfaces has no L3 work) is waived by a dated
line a human writes in the status file, never by an agent. The remaining gates, L1 to L10, are checked the same way
(see [the lifecycle](../concepts/lifecycle.md)).

## 8. Checks and promotion

The other CI twins, run locally:

```
batuta guard scan --diff main..HEAD
OK no unattended-automation or destructive command in 337 added line(s)
guard scan: clean

batuta gate thresholds --check
OK specs/000-foundation/thresholds.json: 1 threshold(s), 0 history entries, ratchet holds (specs/000-foundation/thresholds.json)
thresholds hold
```

For a repository without CI, promotion takes local test output that names the full head SHA. `gate promote` prints the merge
command and never runs it without `--apply`, and refuses a dirty tree:

```
batuta gate promote --branch task/greeting --into main --local-evidence local-evidence.txt
REFUSED the working tree has uncommitted changes; commit or discard them first
promotion refused

(after committing)
OK local evidence: a green test run on 6c75ceec4890 (a repository without CI)
OK would run: git merge --no-ff -m "promote task/greeting at 6c75ceec4890" 6c75ceec48901f5d6ad544dfc647ac8b6bccf8a8 on main (dry run; use --apply)
promotion green
```

In a repository with CI, the `batuta-gates` workflow written by `init project` runs the project's test command, `tdd check
--replay`, `spec trace`, `gate check`, `gate thresholds`, `guard scan`, `context check` and `leaks scan` against the base
commit of the pull request, and promotion waits for it: `gate promote --repo OWNER/REPO --pr N --require batuta-gates`.

One thing to know before you commit the delegation folder of a public repository: `brief new` writes absolute paths into the
brief (contract C02 requires an absolute report and working directory), so `leaks scan` reports them as user paths. Keep
`.batuta/delegation/` out of a public repository, and see [delegating a unit](delegating-a-unit.md) for the loop that creates
those files.

## Sources

- The plugin README fragments of the `init`, `spec`, `tdd`, `gate`, `guard` and `leaks` areas, summarized in the
  [command reference](../reference/cli.md); the contracts C05, C06, C07, C08, C09, C10, C21, C32.
- All output on this page was produced by `plugins/batuta/scripts/batuta.py` at the commit this documentation was written
  against, in a scratch repository under the temporary folder; the scratch repository was deleted afterwards.
- https://code.claude.com/docs/en/hooks for the UserPromptSubmit payload and the `additionalContext` output.
