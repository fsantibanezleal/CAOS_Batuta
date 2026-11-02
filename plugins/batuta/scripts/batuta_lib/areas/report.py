"""Area `report`: check that an agent's report accounts for every deliverable of its brief, keep the ledger status in step,
and hold a briefed agent once until its report passes (the SubagentStop decision).

Verbs:
    check                 apply the checker (one Completeness row per deliverable, status DONE, PARTIAL or BLOCKED,
                          evidence, no placeholders, Sources for research and docs, Red run before Green run for
                          implement briefs, Production path when the brief asks for one) and the C03 contract;
                          exit 0 complete, 1 defective, 2 honest PARTIAL or BLOCKED
    ledger-status         recompute the Status column of `ledger.md` from the reports (`--write` to change the file)
    hook-subagent-stop    the command-line twin of the hook handler: reads the C16 payload on stdin, prints the decision

The decision (`HOOKS["subagent-stop"]`, C31 handler result): a briefed agent whose final message lacks the BRIEF and
REPORT lines, or whose report is missing, defective or has open rows, is blocked once (`decision: block`, exit code 0);
an agent that was not briefed, or that names `BRIEF: none`, is allowed; when the stop hook is already active (the agent
was held once) the stop is allowed and, if the report would still have blocked, a dated UNVERIFIED line is appended to
`<coordination_root>/delegation/unverified.log`, so the hook never loops. Any internal error allows the stop and says why.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from batuta_lib import config, delegation
from batuta_lib import contract as core
from batuta_lib.output import emit, item

AREA = "report"
HELP = "Reports: check a report against its brief, update the ledger status, hold an agent until its report passes."

STATUSES = ("DONE", "PARTIAL", "BLOCKED")
LOG_NAME = "unverified.log"
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")
_URL = re.compile(r"https?://\S+")
# Placeholders a finished report must not carry in its own prose. "XXX" is deliberately absent. Code fences and inline
# code are not scanned: a report may quote source that contains these words.
_PLACEHOLDERS = (
    re.compile(r"\bTODO\b"),
    re.compile(r"\bTBD\b"),
    re.compile(r"\bFIXME\b"),
    re.compile(r"\blorem ipsum\b", re.IGNORECASE),
    re.compile(r"<(?:what|fill|describe|insert|path|slug|topic|evidence)[^<>\n]{0,60}>", re.IGNORECASE),
)
_FENCE_BLOCK = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[^\n]*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_EXIT_CODE = re.compile(r"\b(?:exit(?:ed)?(?:\s+(?:code|status))?|rc|returncode)\s*[:=]?\s*(-?\d+)", re.IGNORECASE)
_NONE_BODY = re.compile(r"^\W*(?:none|n/a|not applicable)\b", re.IGNORECASE)
_LINE = re.compile(r"^\W*(BRIEF|REPORT)\W*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_BRIEFED = re.compile(r"^\W*BRIEF\W*:|^#{1,6}\s+Deliverables\b", re.MULTILINE | re.IGNORECASE)


def _wants_json(args):
    return bool(getattr(args, "json", False))


# ------------------------------------------------------------------ the checker


@dataclass
class Result:
    status: str = "complete"   # complete | incomplete | defective
    exit_code: int = 0
    deliverables: list = field(default_factory=list)
    rows: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    open_items: list = field(default_factory=list)

    @property
    def done(self):
        return sum(1 for d in self.deliverables if self.rows.get(d, {}).get("status") == "DONE")


def _prose(text):
    return _INLINE_CODE.sub("", _FENCE_BLOCK.sub("", text))


def parse_completeness(lines):
    """The Completeness table as {ID: {"status": ..., "evidence": ...}}."""
    rows = {}
    for line in lines:
        match = _TABLE_ROW.match(line)
        if not match:
            continue
        cells = [c.strip() for c in match.group(1).split("|")]
        if all(_SEPARATOR_CELL.match(c) for c in cells if c):
            continue
        ident = cells[0].strip("*` ")
        if not re.fullmatch(r"D\d+", ident):
            continue
        rows[ident] = {"status": cells[1].strip("*` ").upper() if len(cells) > 1 else "",
                       "evidence": " | ".join(cells[2:]).strip() if len(cells) > 2 else ""}
    return rows


def _finish(result):
    if result.problems:
        result.status, result.exit_code = "defective", 1
    elif result.open_items:
        result.status, result.exit_code = "incomplete", 2
    else:
        result.status, result.exit_code = "complete", 0
    return result


def _check_tdd_evidence(brief_text, report_text, kind, result):
    """Red and green runs for kind implement; the production-path section when the brief asks for one."""
    if kind == "implement":
        runs = delegation.sections(report_text, keep_fences=True)
        order = list(runs)
        found = {}
        for name in ("red run", "green run"):
            found[name] = delegation.find_section(runs, name)
            label = name.capitalize()
            if found[name] is None or not "".join(found[name]).strip():
                result.problems.append(f"implement report has no '## {label}' section with the command and its exit code")
                continue
            body = "\n".join(found[name])
            codes = [int(c) for c in _EXIT_CODE.findall(body)]
            if "`" not in body:
                result.problems.append(f"'{label}' names no command (put it in backticks or a code fence)")
            if not codes:
                result.problems.append(f"'{label}' states no exit code (write 'exit code N')")
            elif name == "red run" and not any(codes):
                result.problems.append("'Red run' has no non-zero exit code: the tests must fail before the code exists")
            elif name == "green run" and 0 not in codes:
                result.problems.append("'Green run' has no exit code 0: the checks must pass after the code")
        if found["red run"] and found["green run"]:
            titles = [t for t in order if t.startswith(("red run", "green run"))]
            if len(titles) >= 2 and not titles[0].startswith("red run"):
                result.problems.append("the 'Green run' section comes before the 'Red run' (red first)")
    wanted = "\n".join(delegation.find_section(delegation.sections(brief_text), "production-path check") or []).strip()
    if wanted and not _NONE_BODY.match(wanted):
        body = delegation.find_section(delegation.sections(report_text, keep_fences=True), "production path")
        if body is None or not "".join(body).strip():
            result.problems.append("the brief has a Production-path check but the report has no '## Production path' "
                                   "section with the command run on the real path and its output")


def check_report(brief_text, report_text):
    """The checker alone (no contract): may the parent accept this report as complete, and if not, what is missing."""
    result = Result()
    try:
        result.deliverables = delegation.deliverable_ids(brief_text)
    except delegation.DelegationError as exc:
        result.problems.append(f"brief: {exc}")
        return _finish(result)
    kind = delegation.header_fields(brief_text).get("kind", "").lower()
    if not report_text.strip():
        result.problems.append("report is empty")
        return _finish(result)
    found = delegation.sections(report_text)
    table = delegation.find_section(found, "completeness")
    if table is None:
        result.problems.append("report has no '## Completeness' section")
        return _finish(result)
    result.rows = parse_completeness(table)
    for ident in result.deliverables:
        row = result.rows.get(ident)
        if row is None:
            result.problems.append(f"{ident}: no row in the Completeness table")
            continue
        if row["status"] not in STATUSES:
            result.problems.append(f"{ident}: status '{row['status']}' is not one of {', '.join(STATUSES)}")
            continue
        if not row["evidence"] or row["evidence"] in {"-", "n/a", "N/A"}:
            result.problems.append(f"{ident}: {row['status']} without evidence or reason")
        if row["status"] != "DONE":
            result.open_items.append(f"{ident}: {row['status']}: {row['evidence']}")
    for ident in sorted(set(result.rows) - set(result.deliverables), key=lambda s: int(s[1:])):
        result.problems.append(f"{ident}: row in the report but not a deliverable of the brief")
    prose = _prose(report_text)
    for pattern in _PLACEHOLDERS:
        hit = pattern.search(prose)
        if hit:
            result.problems.append(f"placeholder left in the report: '{hit.group(0)}'")
    sources = delegation.find_section(found, "sources")
    if kind == "research" and (sources is None or not _URL.search("\n".join(sources))):
        result.problems.append("research report has no '## Sources' section with at least one URL")
    if kind == "docs" and (sources is None or not "".join(sources).strip()):
        result.problems.append("docs report has no '## Sources' section naming the files or URLs transcribed")
    _check_tdd_evidence(brief_text, report_text, kind, result)
    return _finish(result)


def c03_problems(report_text):
    """The C03 problems of a report text (empty when it satisfies the contract)."""
    schema_path = core.find_schema(config.contracts_dir(), "C03")
    return core.validate_markdown(report_text.lstrip("﻿"), core.load_schema(schema_path), core.load_sections_spec(schema_path))


def check(brief_text, report_text):
    """The checker and the C03 contract together; the C03 problems are added to the problems with a `C03:` prefix."""
    result = check_report(brief_text, report_text)
    if report_text.strip():
        result.problems.extend(f"C03: {p}" for p in c03_problems(report_text))
    return _finish(result)


def _result_items(result, path):
    items = [item("FAIL", p, path) for p in result.problems] + [item("WARN", o, path) for o in result.open_items]
    if not items:
        items.append(item("OK", f"complete: every deliverable is DONE with evidence", path))
    return items


def _summary(result, path):
    return (f"{result.status.upper()}: {result.done}/{len(result.deliverables)} deliverables DONE "
            f"({len(result.problems)} problems, {len(result.open_items)} open) [{path}]")


def _check(args):
    brief = Path(args.brief)
    try:
        brief_text = delegation.read_text(brief)
    except OSError as exc:
        return emit(AREA, "check", [item("FAIL", f"brief not found or unreadable: {exc}", brief.as_posix())],
                    "report check failed", _wants_json(args))
    if args.report:
        report = Path(args.report)
    else:
        target = delegation.header_fields(brief_text).get("report")
        if not target:
            return emit(AREA, "check", [item("FAIL", "no report given and the brief has no 'report:' field", brief.as_posix())],
                        "report check failed", _wants_json(args))
        report = Path(target)
    try:
        report_text = delegation.read_text(report)
    except OSError as exc:
        result = _finish(Result(problems=[f"report not found or unreadable: {report.as_posix()} ({exc.__class__.__name__})"]))
        try:
            result.deliverables = delegation.deliverable_ids(brief_text)
        except delegation.DelegationError:
            pass
    else:
        result = check(brief_text, report_text)
    return emit(AREA, "check", _result_items(result, report.as_posix()), _summary(result, report.as_posix()), _wants_json(args))


# ------------------------------------------------------------------ ledger-status

KEEP_STATUSES = ("superseded", "timeout", "error", "over-budget")   # outcomes owned by someone else: never recomputed
SEEN_BEFORE = ("complete", "incomplete", "defective", "accepted")   # a report existed when the row got one of these


def _resolve(root, value):
    path = Path(value.replace("\\", "/"))
    return path if path.is_absolute() else Path(root) / path


def row_status(root, row):
    """(new status, detail, output tag) for one ledger row."""
    current = row.get("Status", "")
    if current in KEEP_STATUSES:
        return current, "kept (not recomputed)", "SKIP"
    try:
        brief_text = delegation.read_text(_resolve(root, row["Brief"]))
    except OSError:
        if current in ("accepted", "lost"):   # the parent's decision is not undone because a file was archived
            return current, f"brief missing: {row['Brief']} (status kept)", "WARN"
        return "defective", f"brief missing: {row['Brief']}", "FAIL"
    report = _resolve(root, row["Report"])
    if not report.is_file():
        if current in SEEN_BEFORE:
            return "lost", f"the report was deleted: {row['Report']}", "WARN"
        return ("launched" if current == "launched" else "pending"), "report not written yet", "WARN"
    result = check(brief_text, delegation.read_text(report))
    detail = f"{result.done}/{len(result.deliverables)} DONE"
    detail += "; " + "; ".join((result.problems or result.open_items)[:3]) if (result.problems or result.open_items) else ""
    if current == "accepted":
        return "accepted", detail + " (accepted by the parent, kept)", "OK"
    return result.status, detail, {"complete": "OK", "incomplete": "WARN", "defective": "FAIL"}[result.status]


def _ledger_path(args, root, cfg):
    if getattr(args, "ledger", None):
        return Path(args.ledger)
    return delegation.delegation_dir(root, cfg) / "ledger.md"


def _ledger_status(args):
    try:
        root, resolved, warnings = delegation.project_config(args)
    except config.ConfigError as exc:
        return emit(AREA, "ledger-status", [item("FAIL", f"configuration: {exc}")], "report ledger-status failed", _wants_json(args))
    for line in warnings:
        print(line, file=sys.stderr)
    ledger = _ledger_path(args, root, resolved.config)
    try:
        text = delegation.read_text(ledger)
    except OSError as exc:
        return emit(AREA, "ledger-status", [item("FAIL", f"ledger unreadable: {exc}", ledger.as_posix())],
                    "report ledger-status failed", _wants_json(args))
    columns, rows = delegation.ledger_rows(text)
    if columns and not rows:
        return emit(AREA, "ledger-status", [item("OK", "no rows in the ledger", ledger.as_posix())], "no rows", _wants_json(args))
    problems = delegation.ledger_problems(text)
    if problems:
        return emit(AREA, "ledger-status", [item("FAIL", p, ledger.as_posix()) for p in problems],
                    "the ledger does not satisfy C04; nothing changed", _wants_json(args))
    items, changes = [], {}
    for row in rows:
        status, detail, tag = row_status(root, row)
        note = f"{row['ID']} {status}: {detail}"
        if status != row["Status"]:
            changes[row["ID"]] = status
            note = f"{row['ID']} {row['Status']} -> {status}: {detail}".replace("->", "to")
        items.append(item(tag, note))
    if getattr(args, "write", False) and changes:
        def apply(current):
            for ident, status in changes.items():
                try:
                    current = delegation.ledger_set_status(current, ident, status)
                except KeyError:
                    pass   # a concurrent writer removed the row: nothing to update
            return current
        try:
            delegation.update_ledger(ledger, apply)
        except (delegation.LedgerError, OSError) as exc:
            return emit(AREA, "ledger-status", items + [item("REFUSED", f"ledger not written: {exc}", ledger.as_posix())],
                        "report ledger-status refused", _wants_json(args))
        items.append(item("CHANGED", f"{len(changes)} status value(s) written", ledger.as_posix()))
    for name in delegation.unlisted_briefs(ledger.parent):
        items.append(item("WARN", f"{name} has no row in the ledger (never deleted; add the row or remove the file)", ledger.as_posix()))
    not_accepted = [r["ID"] for r in rows if delegation.accepted_value(r.get("Accepted", "")) != "yes"]
    if not_accepted:
        items.append(item("OK", "not yet accepted by the parent: " + ", ".join(not_accepted)))
    return emit(AREA, "ledger-status", items, f"{len(rows)} row(s)", _wants_json(args))


# ------------------------------------------------------------------ the SubagentStop decision


def _paths(message):
    found = {}
    for key, value in _LINE.findall(message or ""):
        found[key.upper()] = value.strip().strip("`*\"' ")
    return found


def _first_prompt(transcript):
    """Text of the first user message of a subagent transcript (JSONL). OSError when it cannot be read."""
    with Path(transcript).expanduser().open(encoding="utf-8") as fh:
        for _n, line in zip(range(200), fh):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("type") != "user":
                continue
            content = (record.get("message") or {}).get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _result(output=None, message=None):
    out = {"contract_version": "1.0", "exit_code": 0, "output": output}
    if message:
        out["message"] = message
    return out


def _block(reason):
    return {"decision": "block", "reason": reason}


def _at(path, cwd):
    path = Path(path)
    return path if path.is_absolute() else Path(cwd) / path


def _verdict(payload, cwd):
    """(reason to block or None, message for stderr or None, brief path text or None)."""
    lines = _paths(payload.get("last_assistant_message", ""))
    if "BRIEF" not in lines:
        transcript = payload.get("agent_transcript_path")
        if not transcript:
            return None, None, None   # not briefed as far as anyone can tell: the parent owns the check
        try:
            prompt = _first_prompt(_at(transcript, cwd))
        except OSError as exc:
            return None, f"the transcript {transcript} cannot be read ({exc.__class__.__name__}); the stop is allowed", None
        if not _BRIEFED.search(prompt):
            return None, None, None
    if "BRIEF" not in lines or ("REPORT" not in lines and lines.get("BRIEF", "").lower() != "none"):
        return ("End your final message with two lines: 'BRIEF: <absolute path of your brief, or none>' and "
                "'REPORT: <absolute path of the report you wrote>'. Then finish."), None, lines.get("BRIEF")
    if lines["BRIEF"].lower() == "none":
        return None, None, None
    brief_path, report_path = _at(lines["BRIEF"], cwd), _at(lines.get("REPORT", ""), cwd)
    try:
        brief_text = delegation.read_text(brief_path)
    except OSError:
        return f"The BRIEF line names {brief_path.as_posix()}, which cannot be read. Correct the path, then finish.", None, lines["BRIEF"]
    try:
        report_text = delegation.read_text(report_path)
    except OSError:
        return (f"Your report {report_path.as_posix()} does not exist or cannot be read. Write it with the Write tool "
                "(including the '## Completeness' table), then finish."), None, lines["BRIEF"]
    result = check(brief_text, report_text)
    if result.exit_code == 1:
        return (f"Your report fails `batuta report check`: {'; '.join(result.problems)}. Fix the report so every deliverable "
                "of the brief has a Completeness row with a status and evidence, then finish."), None, lines["BRIEF"]
    if result.exit_code == 2:
        return (f"These deliverables are not DONE: {'; '.join(result.open_items)}. Complete any that your brief's scope still "
                "allows. For the rest, make each row say exactly what is missing and why, then finish."), None, lines["BRIEF"]
    return None, None, lines["BRIEF"]


STATE_NAME = "subagent-stop.state"


def _agent_key(payload):
    """What identifies one agent run across its stop attempts: its transcript, else its agent id; None when neither is sent."""
    for field_name in ("agent_transcript_path", "agent_id"):
        value = payload.get(field_name)
        if isinstance(value, str) and value:
            return value
    return None


def _state_path(root, cfg):
    return delegation.delegation_dir(root, cfg) / STATE_NAME


MAX_KEY_CHARS = 512
MAX_STATE_ENTRIES = 1000


def _stored(key):
    """A key as one state line: line boundaries become spaces, a key over MAX_KEY_CHARS is stored as its SHA-256."""
    flat = delegation.LINE_BOUNDARY.sub(" ", key)
    return hashlib.sha256(flat.encode("utf-8")).hexdigest() if len(flat) > MAX_KEY_CHARS else flat


def _held_before(root, cfg, key):
    try:
        return _stored(key) in delegation.read_text(_state_path(root, cfg)).split("\n")
    except OSError:
        return False


def _remember(root, cfg, key):
    """Record that this agent was held once (the hook's own once-per-agent state, independent of `stop_hook_active`).

    At most MAX_STATE_ENTRIES keys are kept (the oldest dropped first) and the file is replaced atomically."""
    try:
        path = _state_path(root, cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        with delegation._Lock(path):
            try:
                lines = [x for x in delegation.read_text(path).split("\n") if x]
            except OSError:
                lines = []
            entry = _stored(key)
            if entry in lines:
                return
            lines = (lines + [entry])[-MAX_STATE_ENTRIES:]
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                    fh.write("\n".join(lines) + "\n")
                delegation._replace(tmp, path)
                tmp = None
            finally:
                if tmp is not None:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
    except OSError:
        pass   # the block still stands; only the extra loop guard is lost


def _report_digest(payload, cwd):
    """SHA-256 of the report file the final message names ("none" when it names none or the file cannot be read)."""
    named = _paths(payload.get("last_assistant_message", "")).get("REPORT")
    if not named:
        return "none"
    try:
        return hashlib.sha256(_at(named, cwd).read_bytes()).hexdigest()
    except OSError:
        return "none"


def _log_unverified(cwd, cfg, payload, brief, reason):
    folder = delegation.delegation_dir(cwd, cfg)
    folder.mkdir(parents=True, exist_ok=True)
    flat = re.sub(r"\s+", " ", reason).strip()[:1000]
    line = (f"{dt.date.today().isoformat()} UNVERIFIED agent={payload.get('agent_type') or 'unknown'} "
            f"brief={brief or 'none'} the agent stopped again after one block: {flat}")
    with open(folder / LOG_NAME, "a", encoding="utf-8", newline="") as fh:
        fh.write(line + "\n")
    return folder / LOG_NAME


def _decide(payload):
    if not isinstance(payload, dict):
        return _result(message="subagent-stop: the payload is not a JSON object; the stop is allowed")
    cwd = Path(payload.get("cwd") or ".")
    root = delegation.find_project_root(cwd)   # the project's configuration decides where the log goes, not the cwd alone
    try:
        cfg = config.load(None, project_root=root).config
    except config.ConfigError as exc:
        return _result(message=f"subagent-stop: the configuration cannot be used ({exc}); the stop is allowed")
    reason, message, brief = _verdict(payload, cwd)
    if reason is None:
        return _result(message=message)
    agent = _agent_key(payload)
    key = None if agent is None else f"{agent}|{_report_digest(payload, cwd)}"   # a new report is held once again
    if payload.get("stop_hook_active") or (key is not None and _held_before(root, cfg, key)):
        log = _log_unverified(root, cfg, payload, brief, reason)
        return _result(message=f"subagent-stop: the agent was already held once; the stop is allowed and UNVERIFIED is logged in {log.as_posix()}")
    if key is not None:
        _remember(root, cfg, key)
    return _result(_block(reason))


def handler(payload):
    """C31 handler for SubagentStop: block a briefed agent once until its report passes; on any internal error allow."""
    try:
        return _decide(payload)
    except Exception as exc:  # noqa: BLE001 (a broken hook must never trap an agent)
        return _result(message=f"subagent-stop: allowed the stop after an internal error: {exc!r}")


HOOKS = {"subagent-stop": handler}


def _hook_cli(_args):
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        print(f"subagent-stop: the payload on stdin is not JSON ({exc}); the stop is allowed", file=sys.stderr)
        return 0
    result = handler(payload)
    if result.get("message"):
        print(result["message"], file=sys.stderr)
    if result["output"] is not None:
        print(json.dumps(result["output"]))
    return result["exit_code"]


def register(subparsers):
    check_p = subparsers.add_parser("check", help="check a report against its brief (and C03)")
    check_p.add_argument("report", nargs="?", help="the report (default: the brief's report line)")
    check_p.add_argument("--brief", required=True, help="the brief the agent was given")
    check_p.add_argument("--root", default=".", help="project root (default: the current folder)")
    check_p.set_defaults(func=_check)
    status = subparsers.add_parser("ledger-status", help="recompute the Status column of the ledger from the reports")
    status.add_argument("--ledger", help="the ledger file (default: <coordination_root>/delegation/ledger.md)")
    status.add_argument("--root", default=".", help="project root the ledger paths are relative to (default: the current folder)")
    status.add_argument("--write", action="store_true", help="write the computed statuses into the ledger (default: dry run)")
    status.set_defaults(func=_ledger_status)
    hook = subparsers.add_parser("hook-subagent-stop", help="the SubagentStop decision: payload on stdin, decision on stdout")
    hook.set_defaults(func=_hook_cli)
