"""Promotion only on green, for the exact head commit.

Two forms, one rule: nothing is merged unless every check is green for the head that is merged, and nothing here ever
overrides a failed or pending check.

* Pull request (`--repo` and `--pr`): the head SHA, the mergeable state and every check come from the `gh` CLI. Only a
  check that concluded SUCCESS is green. A SKIPPED or NEUTRAL check is not evidence, a pending one is never green, and a
  required check that never ran is a refusal. A head that moved from `--sha` is a refusal. When the head has no checks at
  all (a repository without CI), local evidence recorded for that exact head replaces them; evidence never replaces a
  check that exists. The merge is pinned to the head that was checked (`--match-head-commit`).
* Local branch (`--branch`, `--into`, `--local-evidence`): the same rule for a repository without CI. The branch tip must be
  the head named by the evidence and the working tree clean; the merge runs only when `--into` is the checked-out branch,
  because this command never switches branches.

Without `--apply` the merge command is printed and not run. Exit codes: 0 green, 1 refused, 2 still pending.
"""
import json
import re
import subprocess
from pathlib import Path

from batuta_lib import gate_model
from batuta_lib.output import item

FIELDS = "headRefOid,statusCheckRollup,mergeable"
PENDING_STATUSES = {"PENDING", "IN_PROGRESS", "QUEUED", "WAITING", "REQUESTED"}
PENDING_STATES = {"PENDING", "EXPECTED"}
NOT_EVIDENCE = {"SKIPPED": "a skipped check is not evidence", "NEUTRAL": "a neutral check is not evidence"}
_FAILURE_TEXT = re.compile(r"\bFAILED\b|\bERROR\b|\b[1-9]\d* (?:failed|failing|errors?|failures?)\b|(?:failures|errors)=[1-9]", re.I)
_RAN = re.compile(r"^Ran (\d+) tests?\b", re.M)
_PASSED = re.compile(r"\b(\d+) passed\b")
_SKIPPED = re.compile(r"skipped=(\d+)")


def run_gh(args):
    """Run `gh` and return (returncode, stdout or stderr)."""
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"gh could not run: {exc}"
    return proc.returncode, proc.stdout if proc.returncode == 0 else (proc.stderr or proc.stdout)


def classify(check):
    """(name, shown state, verdict, note): verdict is pass, pending or fail. Only SUCCESS passes."""
    if "context" in check and "state" in check and "conclusion" not in check:      # a commit status context
        name, state = check["context"], str(check["state"]).upper()
        if state == "SUCCESS":
            return name, state, "pass", ""
        return name, state, "pending" if state in PENDING_STATES else "fail", ""
    name = check.get("name") or check.get("workflowName") or "(unnamed check)"
    status = str(check.get("status") or "").upper()
    conclusion = str(check.get("conclusion") or "").upper()
    if status != "COMPLETED":
        return name, status or "UNKNOWN", "pending" if status in PENDING_STATUSES else "fail", ""
    if conclusion == "SUCCESS":
        return name, conclusion, "pass", ""
    return name, conclusion or "NONE", "fail", NOT_EVIDENCE.get(conclusion, "")


def evidence_ok(text, head):
    """Local test output proves a green run on this head: it names the full head SHA, reports no failure or error, and shows
    tests that ran and passed: `Ran N tests` with N above zero and `OK` (unittest), or `N passed` with N above zero (pytest).
    A run of zero tests, or one in which every test was skipped, is not evidence."""
    if not head or head.lower() not in text.lower() or _FAILURE_TEXT.search(text):
        return False
    skipped = sum(int(n) for n in _SKIPPED.findall(text))
    ran = _RAN.search(text)
    if ran and re.search(r"^OK(\s|$)", text, re.M):
        return int(ran.group(1)) > 0 and skipped < int(ran.group(1))
    passed = _PASSED.search(text)
    return bool(passed) and int(passed.group(1)) > 0


def evaluate_pr(data, *, sha=None, evidence_text=None, required=()):
    """(exit code, items, head) for the `gh pr view` JSON of a pull request."""
    items, head = [], str(data.get("headRefOid") or "")
    verdicts, names = [], set()
    for check in data.get("statusCheckRollup") or []:
        name, state, verdict, note = classify(check)
        verdicts.append(verdict)
        names.add(name)
        tail = f" ({note})" if note else ""
        items.append(item({"pass": "OK", "pending": "WARN", "fail": "REFUSED"}[verdict],
                          f"check {name}: {state}{' (pending)' if verdict == 'pending' else ''}{tail}"))
    problems, pending = [], []
    if sha is not None and not (head and head.lower().startswith(sha.lower())):
        problems.append(f"head moved: expected {sha}, found {head or 'none'}")
    if not verdicts:
        if evidence_text is not None and evidence_ok(evidence_text, head):
            items.append(item("OK", "local evidence: a green test run on this exact head (no CI checks on the repository)"))
        elif evidence_text is not None:
            problems.append("no checks on the head and the local evidence does not prove a green run on it")
        else:
            problems.append("no checks on the head (a repository without CI promotes with --local-evidence)")
    for name in required:
        if name not in names:
            problems.append(f"required check {name} never ran on this head")
    if "fail" in verdicts:
        problems.append(f"{verdicts.count('fail')} check(s) did not succeed")
    mergeable = str(data.get("mergeable") or "UNKNOWN").upper()
    if mergeable == "UNKNOWN":
        pending.append("mergeable is still UNKNOWN")
    elif mergeable != "MERGEABLE":
        problems.append(f"mergeable is {mergeable}")
    if "pending" in verdicts:
        pending.append(f"{verdicts.count('pending')} check(s) pending: wait and run again")
    items.extend(item("REFUSED", p) for p in problems)
    items.extend(item("WARN", p) for p in pending)
    code = 1 if problems else (2 if pending else 0)
    return code, items, head


def promote_pr(repo, number, *, sha=None, evidence_path=None, required=(), apply=False, gh=None):
    """Items of a pull request promotion."""
    gh = gh or run_gh
    rc, text = gh(["pr", "view", str(number), "--repo", repo, "--json", FIELDS])
    if rc != 0:
        return [item("REFUSED", f"gh pr view failed: {text.strip()}; without gh, promote a local branch with --local-evidence")]
    try:
        data = json.loads(text)
    except ValueError as exc:
        return [item("REFUSED", f"gh pr view returned invalid JSON: {exc}")]
    if not isinstance(data, dict):
        return [item("REFUSED", "gh pr view returned an unexpected JSON shape")]
    evidence_text = None
    if evidence_path:
        try:
            evidence_text = Path(evidence_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return [item("REFUSED", f"cannot read the local evidence {evidence_path}: {exc}")]
    code, items, head = evaluate_pr(data, sha=sha, evidence_text=evidence_text, required=required)
    if code != 0:
        return items
    cmd = ["pr", "merge", str(number), "--repo", repo, "--merge", "--match-head-commit", head]
    if not apply:
        items.append(item("OK", "would run: gh " + " ".join(cmd) + " (dry run; use --apply)"))
        return items
    rc, text = gh(cmd)
    if rc != 0:
        items.append(item("REFUSED", f"merge failed: {text.strip()}"))
    else:
        items.append(item("OK", f"merged {repo}#{number} at {head[:12]}"))
    return items


def promote_local(root, branch, into, evidence_path, *, sha=None, apply=False):
    """Items of a local branch promotion on a repository without CI."""
    root, git = Path(root), gate_model.GIT
    try:
        text = Path(evidence_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [item("REFUSED", f"cannot read the local evidence {evidence_path}: {exc}")]
    if git.info(root) is None:
        return [item("REFUSED", "not a git repository with a commit")]
    tip = git.rev(root, branch)
    if tip is None:
        return [item("REFUSED", f"branch {branch} does not exist")]
    if git.rev(root, into) is None:
        return [item("REFUSED", f"target branch {into} does not exist")]
    items, problems = [], []
    if sha is not None and not tip.lower().startswith(sha.lower()):
        problems.append(f"head moved: expected {sha}, found {tip}")
    if not evidence_ok(text, tip):
        problems.append(f"the local evidence does not prove a green run on the exact head {tip}")
    else:
        items.append(item("OK", f"local evidence: a green test run on {tip[:12]} (a repository without CI)"))
    if git.dirty(root):
        problems.append("the working tree has uncommitted changes; commit or discard them first")
    if problems:
        return items + [item("REFUSED", p) for p in problems]
    message = f"promote {branch} at {tip[:12]}"
    cmd = f'git merge --no-ff -m "{message}" {tip}'
    if not apply:
        return items + [item("OK", f"would run: {cmd} on {into} (dry run; use --apply)")]
    current = git.branch(root)
    if current != into:
        return items + [item("REFUSED", f"{current} is checked out, not {into}: this command never switches branches; check out {into} first")]
    rc, out = git.merge(root, tip, message)
    if rc != 0:
        return items + [item("REFUSED", f"merge failed: {out.strip()}")]
    return items + [item("OK", f"merged {branch} at {tip[:12]} into {into}")]
