"""Area `spec`: feature specs (C05) with EARS requirements and runnable gates, their trace (C08) and the hash-bound freeze (C06).

Verbs:
    new            create `specs/<NNN-slug>/` from the templates (dry run unless --apply)
    lint           C05 and the spec rules: runnable gates, interfaces resolved against the catalog, ids never reused
    trace          the requirement to test to task matrix (C08), written to `trace.json` with --apply
    show           the files the freeze hashes and the approval phrase to type
    approve        the manual fallback for devices where hooks do not run: the phrase is typed at the console device
                   (`CONIN$`, `/dev/tty`), never read from piped input; refused without a terminal
    hook-approval  a dry run of the `spec-approval` handler: reads a UserPromptSubmit payload on stdin, writes nothing
    freeze         `--check`: recompute every hash and report VALID or VOID with the files that changed

The approval is only ever created from the human's typed text, `approve <spec id> <first 12 hex of the spec's sha256>`,
by the UserPromptSubmit handler (HOOKS below, run by the harness) or by a human at `spec approve`; both go through one
function, and a prefix that is not the current spec's is refused with nothing written. Residual risk: a schema-valid record
written by another process is indistinguishable from a captured one; the approvals write guard, the guard on the approve
commands and the permission preset are the controls, with human review of the committed record. Comments (the templates' examples) are stripped before anything is read.
Exit codes: 0 ok, 1 failure or refusal, 2 warnings.
"""
import argparse
import json
import os
import re
import sys
import threading
from datetime import date
from pathlib import Path

from batuta_lib import approval
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm
from batuta_lib import render
from batuta_lib import spec_model as sm
from batuta_lib import trace as tr
from batuta_lib.output import emit, item

AREA = "spec"
HELP = "Specs: new, lint, trace, show, approve (typed, hash-bound), freeze --check."

TEMPLATES = Path(__file__).resolve().parents[2].parent / "templates" / "spec"
TIERS = ("S", "M", "L")
FROZEN_STATES = ("Review", "Frozen")
NO_PLAN = "S"
_NONE_REASON = "no spec"


# ------------------------------------------------------------------ new


def _next_number(root):
    base = Path(root) / sm.SPECS_DIR
    nums = [int(m.group(0)[:3]) for d in (base.iterdir() if base.is_dir() else []) if d.is_dir() and (m := re.match(r"\d{3}-", d.name))]
    nums = [n for n in nums if n > 0]
    return max(nums, default=0) + 1


def new(root, title, tier="M", owner=None, apply=False, today=None):
    root = Path(root)
    if tier not in TIERS:
        return [item("FAIL", f"tier must be one of {', '.join(TIERS)}, not '{tier}'")]
    spec_id = f"{_next_number(root):03d}-{sm.slugify(title)}"
    values = {"id": spec_id, "title": title, "tier": tier, "owner": owner or approval.current_user(),
              "created": (today or date.today()).isoformat()}
    folder = root / sm.SPECS_DIR / spec_id
    plan = [("spec.md", "spec.md"), ("tasks.md", "tasks.md")]
    if tier != NO_PLAN:
        plan.append(("plan.md", "plan.md"))
    out = []
    for name, template in plan:
        text = render.render_file(TEMPLATES / template, values)
        path = folder / name
        status = render.status(path, text)
        if apply and status == "NEW":
            render.write_atomic(path, text)
        out.append(item(status, f"{spec_id}/{name}", sm.rel(path, root)))
    for sub in ("approvals", "evidence"):
        keep = folder / sub / ".gitkeep"
        status = "SAME" if keep.exists() else "NEW"
        if apply and status == "NEW":
            render.write_atomic(keep, "")
        out.append(item(status, f"{spec_id}/{sub}/", sm.rel(keep, root)))
    constitution = root / sm.SPECS_DIR / sm.FOUNDATION / "constitution.md"
    if not constitution.exists():
        if apply:
            render.write_atomic(constitution, render.render_file(TEMPLATES / "constitution.md", {}))
        out.append(item("NEW", f"{sm.FOUNDATION}/constitution.md", sm.rel(constitution, root)))
    if not apply:
        out.append(item("SKIP", "dry run: nothing written; pass --apply to create the files"))
    return out


# ------------------------------------------------------------------ lint


def _plan_items(root, d, spec, items, label):
    plan = d / "plan.md"
    needs = spec.status in FROZEN_STATES and spec.tier in ("M", "L")
    if not plan.is_file():
        if needs:
            items.append(item("FAIL", f"{label}: tier {spec.tier} needs plan.md with a constitution check", sm.rel(plan, root)))
        return
    if not needs:
        return
    plabel = sm.rel(plan, root)
    stripped = sm.strip_comments(plan.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
    titles = [t.lower() for t in fm.sections(stripped)]
    if not any(t.startswith("constitution check") for t in titles):
        items.append(item("FAIL", f"{plabel}: no 'Constitution check' section", plabel))
        return
    tables = [(h, rows) for title, h, rows in fm.section_tables(stripped) if (title or "").lower().startswith("constitution check")]
    col = None
    for headers, rows in tables:
        low = [h.lower() for h in headers]
        if "simpler alternative rejected" in low:
            col = (low.index("simpler alternative rejected"), rows)
            break
    if col is None:
        items.append(item("FAIL", f"{plabel}: the Constitution check table needs a 'Simpler alternative rejected' column", plabel))
        return
    idx, rows = col
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        items.append(item("FAIL", f"{plabel}: the Constitution check has no rows; each decision names the simpler alternative rejected", plabel))
    for r in rows:
        if not r[idx].strip():
            items.append(item("FAIL", f"{plabel}: '{r[0]}' leaves 'Simpler alternative rejected' empty", plabel))


def _tasks_items(root, d, spec, ids, items, label):
    path = d / "tasks.md"
    draft = spec.status == "Draft"
    tlabel = sm.rel(path, root)
    if not path.is_file():
        items.append(item("SKIP" if draft else "FAIL", f"{label}: no tasks.md", tlabel))
        return None
    stripped = sm.strip_comments(path.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
    rows = sm.read_rows("C21", "Tasks", stripped)
    if rows is None:
        items.append(item("FAIL", f"{tlabel}: no Tasks table with the C21 columns", tlabel))
        return None
    if not rows:
        items.append(item("SKIP" if draft else "FAIL", f"{tlabel}: no tasks yet" + ("" if draft else " (a spec in Review or Frozen has tasks)"), tlabel))
        return rows
    if not draft:
        items.extend(item("FAIL", f"{tlabel}: {e}", tlabel) for e in sm.validate_text("C21", stripped))
    known = {r["Id"] for r in spec.rows}
    for t in rows:
        for r in t["Requirements"]:
            if r not in known:
                items.append(item("FAIL", f"{tlabel}: task {t['Task']} names unknown requirement {r}", tlabel))
        for c in t["Contracts"]:
            if c not in ids:
                items.append(item("FAIL", f"{tlabel}: task {t['Task']} uses contract '{c}' that the spec's Interfaces section does not list", tlabel))
    return rows


def lint_spec(root, d, catalog=None, ids_map=None):
    """Lint one feature folder; returns items."""
    root, d = Path(root), Path(d)
    items = []
    path = d / "spec.md"
    label = sm.rel(path, root)
    if not path.is_file():
        return [item("FAIL", f"{d.name}: spec.md is missing", label)]
    spec = sm.read_spec(path)
    items.extend(item("FAIL", f"{label}: {e}", label) for e in spec.errors)
    if spec.id and spec.id != d.name:
        items.append(item("FAIL", f"{label}: the folder {d.name} must carry the spec id {spec.id}", label))
    if not spec.meta:
        return items
    for row in spec.active_rows():
        why = sm.check_gate(row.get("Gate", ""), root)
        if why:
            items.append(item("FAIL", f"{row['Id']}: gate: {why}: '{row.get('Gate', '')}'", label))
    ids_map = ids_map if ids_map is not None else sm.requirement_ids_by_spec(root)
    for row in spec.rows:
        others = [s for s in ids_map.get(row.get("Id", ""), []) if s != d.name]
        if others:
            items.append(item("FAIL", f"{row['Id']}: the id is also defined in {', '.join(others)}; requirement ids are never reused", label))
    ids = sm.interface_ids(spec)
    if ids:
        rows, cat_items = sm.read_catalog_rows(root, catalog)
        cat_label = sm.rel(sm.catalog_file(root, catalog), root)
        if rows is None:
            why = "; ".join(i["message"] for i in cat_items) or f"no catalog at {cat_label}"
            items.extend(item("FAIL", f"interface '{i}' is unresolved ({why})", cat_label) for i in ids)
        else:
            known = {r["id"] for r in rows}
            items.extend(item("FAIL", f"{label}: interface '{i}' is not a row of the catalog", cat_label) for i in ids if i not in known)
    _tasks_items(root, d, spec, ids, items, label)
    _plan_items(root, d, spec, items, label)
    gated = spec.status in FROZEN_STATES
    if gated:
        adrs = sm.adr_references(spec)
        for aid in adrs:
            if sm.find_adr(root, aid) is None:
                items.append(item("WARN", f"{label}: {aid} is referenced but not found under {sm.ADR_DIR}/ (it is not hashed at the freeze)", label))
        if spec.tier == "L" and not adrs:
            items.append(item("FAIL", f"{label}: tier L references at least one ADR (ADR-NNNN) so the freeze hashes it", label))
        for rid, kind, detail in sm.gate_findings(root, spec):
            if kind == "escape":
                items.append(item("FAIL", f"{rid}: the Gate names {detail}, outside the repository", label))
            elif kind == "outside":
                items.append(item("FAIL", f"{rid}: the Gate names {detail}, which resolves outside the repository", label))
            elif kind == "none":
                items.append(item("FAIL", f"{rid}: the Gate names no test file or folder of tests the freeze can hash (configuration and documentation files never count)", label))
            else:
                items.append(item("FAIL" if spec.status == "Frozen" else "WARN",
                                  f"{label}: the Gate of {rid} names {detail}, which does not exist (the freeze hashes every named test)", label))
        if not (root / sm.SPECS_DIR / sm.FOUNDATION / "constitution.md").is_file():
            items.append(item("WARN", f"{sm.SPECS_DIR}/{sm.FOUNDATION}/constitution.md is missing; the plans' constitution check has nothing to check against"))
        tcr = d / "test-change-requests.md"
        if tcr.is_file():
            tlabel = sm.rel(tcr, root)
            stripped = sm.strip_comments(tcr.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
            rows = sm.read_rows("C33", "Change requests", stripped, False)
            if rows is None:
                items.append(item("FAIL", f"{tlabel}: no table with the C33 columns", tlabel))
            elif rows:
                items.extend(item("FAIL", f"{tlabel}: {e}", tlabel) for e in sm.validate_text("C33", stripped))
    if not any(i["tag"] in ("FAIL", "WARN") for i in items):
        items.append(item("OK", f"{d.name} satisfies C05 and the spec rules ({spec.status}, tier {spec.tier})", label))
    return items


def lint(root=".", spec=None, catalog=None):
    root = Path(root)
    dirs = sm.spec_dirs(root)
    if spec:
        want = Path(spec).parent.name if str(spec).endswith(".md") else str(spec)
        dirs = [d for d in dirs if d.name == want]
        if not dirs:
            return [item("FAIL", f"no spec {want} under {sm.SPECS_DIR}/")]
    if not dirs:
        return [item("SKIP", f"no specs under {sm.SPECS_DIR}/")]
    ids_map = sm.requirement_ids_by_spec(root)
    items = []
    for d in dirs:
        items.extend(lint_spec(root, d, catalog, ids_map))
    return items


# ------------------------------------------------------------------ trace


def trace(root, spec_id, apply=False, extra=(), catalog=None):
    root = Path(root)
    path = sm.spec_path(root, spec_id)
    if not path.is_file():
        return [item("FAIL", f"no spec {spec_id}: {sm.rel(path, root)} does not exist")]
    spec = sm.read_spec(path)
    label = sm.rel(path, root)
    if spec.errors:
        return [item("FAIL", f"{label}: {e}", label) for e in spec.errors]
    items = []
    tasks_path = path.parent / "tasks.md"
    rows = []
    if tasks_path.is_file():
        stripped = sm.strip_comments(tasks_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
        rows = sm.read_rows("C21", "Tasks", stripped) or []
        if rows:
            items.extend(item("FAIL", f"{sm.rel(tasks_path, root)}: {e}", sm.rel(tasks_path, root)) for e in sm.validate_text("C21", stripped))
    matrix, findings = tr.build(root, spec, rows, extra)
    draft = spec.status == "Draft"
    orphans = [f for f in findings if f["kind"] == "orphan"]
    for f in findings:
        kind = f["kind"]
        if kind == "unknown":
            items.append(item("FAIL", f"unknown requirement id {f['id']} ({f['where']})", label))
        elif kind == "retired":
            items.append(item("FAIL", f"{f['id']} is retired but is tagged in {f['where']}", label))
        elif kind == "untagged":
            items.append(item("FAIL", f"test file {f['path']} has no REQ marker line", f["path"]))
        elif kind == "no-task":
            items.append(item("WARN", f"{f['id']} is covered by no task", sm.rel(tasks_path, root)))
        elif kind == "orphan" and not draft:
            items.append(item("FAIL", f"orphan requirement {f['id']}: no test carries its REQ marker", label))
    if orphans and draft:
        items.append(item("SKIP", f"Draft spec: {len(orphans)} orphan requirement(s) are not enforced ({', '.join(f['id'] for f in orphans)})"))
    schema = core.load_schema(core.find_schema(sm.config.contracts_dir(), "C08"))
    errors = core.validate_instance("C08", matrix, schema)
    if errors:
        return items + [item("FAIL", f"the matrix does not satisfy C08: {e}") for e in errors]
    out = path.parent / "trace.json"
    text = tr.dumps(matrix)
    status = render.status(out, text)
    if apply and status != "SAME":
        render.write_atomic(out, text)
    suffix = "" if apply or status == "SAME" else " (dry run; --apply writes it)"
    items.append(item(status, f"trace.json for {spec_id}: {len(matrix['requirements'])} requirement(s), ok={str(matrix['ok']).lower()}{suffix}", sm.rel(out, root)))
    return items


# ------------------------------------------------------------------ show, approve, hook, freeze


def _files_items(g, root):
    out = [item("OK", f"hashes {p} ({sha[:12]})", p) for p, sha in sorted(g.hashed().items())]
    out.extend(item("WARN", w) for w in g.warnings)
    return out


def show(root, spec_id, catalog=None):
    g = approval.gather(root, spec_id, catalog)
    if g.spec is None:
        return [item("FAIL", g.problems[0])]
    items = _files_items(g, root)
    items.extend(item("WARN", f"the freeze would be refused: {r}") for r in g.refusals())
    items.append(item("OK", f"approval phrase to type: {approval.phrase(spec_id, g.spec_sha)}"))
    return items


def approve_typed(root, typed, spec_id=None, catalog=None, approved_by=None, write=True):
    """The one function that writes an approval. `typed` is the human's text; `spec_id` pins the spec when the caller knows it.
    Returns (items, record path or None). Refusals write nothing; with `write=False` (a dry run) nothing is ever written."""
    root = Path(root)
    parsed = approval.parse_attempt(typed)
    if parsed is None:
        hint = f" for {spec_id}" if spec_id else ""
        return [item("REFUSED", f"the typed text must start with `approve <spec id> <first 12 hex of the spec sha256>`{hint}")], None
    typed_id, typed_prefix, extra = parsed
    if extra:
        return [item("REFUSED", f"the first line must be exactly `approve <spec id> <first 12 hex of the spec sha256>` and nothing "
                                f"else; remove the other text ({_clip(extra, 60)}) and type it again")], None
    if len(typed_id) > 80:
        return [item("REFUSED", f"the typed spec id {_clip(typed_id, 80)} is not a spec id")], None
    if spec_id and typed_id != spec_id:
        return [item("REFUSED", f"the typed phrase names spec {typed_id}, not {spec_id}")], None
    typed_prefix_shown = _clip(typed_prefix, 40)
    spec_id = typed_id
    d = root / sm.SPECS_DIR / spec_id
    if not (d / "spec.md").is_file():
        return [item("REFUSED", f"no spec {spec_id}: {sm.rel(d / 'spec.md', root)} does not exist")], None
    g = approval.gather(root, spec_id, catalog)
    shown = f"; the current prefix is {g.prefix}, type: {approval.phrase(spec_id, g.spec_sha)}"
    if not approval.valid_prefix(typed_prefix):
        return [item("REFUSED", f"the prefix '{typed_prefix_shown}' is not exactly 12 hex characters{shown}")], None
    if g.spec.status not in FROZEN_STATES:
        return [item("REFUSED", f"spec {spec_id} is {g.spec.status or 'of unknown status'}; only a spec in Review or Frozen is approved")], None
    fails = [i for i in lint_spec(root, d, catalog) if i["tag"] == "FAIL"]
    if fails:
        return [item("REFUSED", f"spec {spec_id} fails `spec lint`, fix it first: {i['message']}") for i in fails[:5]], None
    if g.refusals():
        return [item("REFUSED", f"the freeze of {spec_id} is refused: {r}") for r in g.refusals()], None
    if typed_prefix != g.prefix:
        return [item("REFUSED", f"the prefix {typed_prefix_shown} is not the current spec's: the spec changed since you read it{shown}")], None
    if not write:
        out = [item("OK", f"would record the approval of {spec_id} at {g.prefix} (dry run: nothing written)")]
        out.extend(item("OK", f"would hash {p}", p) for p in sorted(g.hashed()))
        return out, None
    try:
        path = approval.write_record(root, g, typed, approved_by or approval.current_user(), approval.tool_version())
    except (ValueError, OSError) as exc:
        return [item("REFUSED", f"the approval of {spec_id} could not be recorded: {exc}")], None
    out = [item("NEW", f"approval recorded for {spec_id} at {g.prefix}", sm.rel(path, root))]
    out.extend(item("OK", f"hashed {p}", p) for p in sorted(g.hashed()))
    return out, path


class ConsoleError(Exception):
    """There is no human at a console to type the approval phrase."""


CONSOLE_TIMEOUT_SECONDS = 300
ECHO_LIMIT = 200
CONTEXT_LIMIT = 10000


def _console_mode_ok():
    """Windows: the standard input handle is a real console (`GetConsoleMode` succeeds). A stdin of NUL passes `isatty()`
    but fails this call."""
    try:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.GetStdHandle.restype = wintypes.HANDLE
        handle = kernel.GetStdHandle(-10)
        mode = wintypes.DWORD()
        return bool(kernel.GetConsoleMode(handle, ctypes.byref(mode)))
    except Exception:  # noqa: BLE001 (no ctypes, no kernel32: not a console)
        return False


def _stdin_is_console():
    try:
        if not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    return _console_mode_ok() if sys.platform == "win32" else True


def _read_console():
    """One line typed at the console device (`CONIN$` on Windows, `/dev/tty` elsewhere), never the piped standard input: a
    process that pipes its own text into `spec approve` is not a human typing. Raises ConsoleError when stdin is not a
    console (on Windows a console handle, on POSIX a tty), the device cannot be opened, or nobody types within
    CONSOLE_TIMEOUT_SECONDS, so a launch with nobody at the keyboard never hangs. Keystrokes injected into the console by
    another local process are the waived residual risk (F-02): the guards deny the direct paths."""
    if not _stdin_is_console():
        raise ConsoleError("standard input is not a console: `spec approve` reads the phrase from the console device, "
                           "so a human must run it in an interactive terminal (where hooks run, type the phrase in the prompt)")
    device = "CONIN$" if sys.platform == "win32" else "/dev/tty"
    result = {}

    def work():
        try:
            with open(device, "r", encoding="utf-8", errors="replace") as console:
                result["line"] = console.readline()
        except OSError as exc:
            result["error"] = exc

    reader = threading.Thread(target=work, daemon=True)
    reader.start()
    reader.join(CONSOLE_TIMEOUT_SECONDS)
    if reader.is_alive():
        raise ConsoleError(f"timed out after {CONSOLE_TIMEOUT_SECONDS:g} seconds waiting for the typed phrase; nothing was written")
    if "error" in result:
        raise ConsoleError(f"the console device {device} cannot be opened ({result['error']})")
    return result.get("line", "")


def _clip(text, limit=ECHO_LIMIT):
    """A piece of the typed prompt echoed back, cut at `limit` characters with an ellipsis."""
    text = str(text)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _cmd_approve(args):
    g = approval.gather(args.root, args.spec_id, args.catalog)
    items = []
    if g.spec is None:
        return emit(AREA, "approve", [item("FAIL", g.problems[0])], "spec approve: no such spec", _json(args))
    items.extend(_files_items(g, args.root))
    items.append(item("OK", "this is the manual path for devices where hooks do not run; where hooks run, type the phrase in the prompt instead"))
    print(f"Type exactly: {approval.phrase(args.spec_id, g.spec_sha)}", file=sys.stderr)
    try:
        typed = _read_console()
    except ConsoleError as exc:
        items.append(item("REFUSED", f"no human at a console: {exc}"))
        return emit(AREA, "approve", items, "spec approve: refused, nothing written", _json(args))
    res, _ = approve_typed(args.root, typed, args.spec_id, args.catalog)
    items.extend(res)
    return emit(AREA, "approve", items, "spec approve: " + ("approved" if all(i["tag"] != "REFUSED" for i in res) else "refused, nothing written"), _json(args))


def approval_hook(payload):
    """UserPromptSubmit handler (C31): records an approval when the human's prompt starts with the typed phrase. It never
    blocks the prompt: the result is exit code 0 with a null output, or with additional context saying what happened."""
    quiet = {"contract_version": "1.0", "exit_code": 0, "output": None}
    try:
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        if not isinstance(prompt, str) or approval.parse_attempt(prompt) is None:
            return quiet
        root = payload.get("cwd") or os.getcwd()
        items, _ = approve_typed(root, prompt)
        text = _clip("; ".join(f"{i['tag']} {_clip(i['message'])}" for i in items[:6]), CONTEXT_LIMIT)
    except Exception as exc:  # noqa: BLE001 (the capture must never block a prompt)
        text = _clip(f"REFUSED approval capture failed: {exc}", CONTEXT_LIMIT)
    return {"contract_version": "1.0", "exit_code": 0,
            "output": {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text},
                       "systemMessage": text}}


HOOKS = {"spec-approval": approval_hook}


def _cmd_hook(args):
    """A dry run of the handler: what it would record for this payload. It never writes; only the harness-run handler does."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        print(f"spec hook-approval: the stdin payload is not JSON ({exc})", file=sys.stderr)
        return 1
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or approval.parse_attempt(prompt) is None:
        items = [item("SKIP", "dry run: the prompt does not start with the approval phrase; the handler would ignore it")]
    else:
        items, _ = approve_typed(payload.get("cwd") or os.getcwd(), prompt, write=False)
        items.append(item("SKIP", "dry run: nothing written; the approval is recorded only by the hook handler run by the harness"))
    return emit(AREA, "hook-approval", items, _summary("spec hook-approval (dry run)", items), _json(args))


def freeze(root, spec_id, catalog=None):
    state, reasons, path, records = approval.check(root, spec_id, catalog)
    items = []
    for p, rec, errors in records:
        if rec is None:
            items.append(item("WARN", f"approval record ignored: {'; '.join(errors)}", sm.rel(p, root)))
    if state == "VALID":
        g = approval.gather(root, spec_id, catalog)
        items.append(item("OK", f"VALID {spec_id}: {sm.rel(path, root)} matches the {len(g.hashed())} hashed file(s)", sm.rel(path, root)))
    elif state == "NONE":
        items.append(item("FAIL", f"VOID {spec_id}: {reasons[0]}"))
    else:
        items.extend(item("FAIL", f"VOID {spec_id}: {r}", sm.rel(path, root)) for r in reasons)
    return items


# ------------------------------------------------------------------ CLI


def _json(args):
    return bool(getattr(args, "json", False))


def _summary(label, items):
    n = {t: sum(1 for i in items if i["tag"] == t) for t in ("OK", "WARN", "FAIL", "REFUSED")}
    return f"{label}: {n['OK']} ok, {n['WARN']} warning(s), {n['FAIL'] + n['REFUSED']} failure(s)"


def _cmd_new(args):
    items = new(args.root, args.title, args.tier, args.owner, args.apply)
    return emit(AREA, "new", items, _summary("spec new", items), _json(args))


def _cmd_lint(args):
    items = lint(args.root, args.spec, args.catalog)
    return emit(AREA, "lint", items, _summary("spec lint", items), _json(args))


def _cmd_trace(args):
    items = trace(args.root, args.spec_id, args.apply, args.tests or (), args.catalog)
    return emit(AREA, "trace", items, _summary("spec trace", items), _json(args))


def _cmd_show(args):
    items = show(args.root, args.spec_id, args.catalog)
    return emit(AREA, "show", items, _summary("spec show", items), _json(args))


def _cmd_freeze(args):
    items = freeze(args.root, args.spec_id, args.catalog)
    return emit(AREA, "freeze", items, _summary("spec freeze --check", items), _json(args))


def _common(p, spec_id=True):
    if spec_id:
        p.add_argument("spec_id", help="the spec id, for example 001-alerts")
    p.add_argument("--root", default=".", help="project root (default: the current folder)")
    p.add_argument("--catalog", help=f"the contract catalog (default: {sm.CATALOG_PATH} under --root)")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the C20 JSON object")


def register(subparsers):
    p = subparsers.add_parser("new", help="create a feature folder from the templates (dry run unless --apply)")
    p.add_argument("--root", default=".", help="project root (default: the current folder)")
    p.add_argument("--title", required=True)
    p.add_argument("--tier", default="M", help="S, M or L (default M): the artifacts the spec needs")
    p.add_argument("--owner", help="the spec owner (default: the current user)")
    p.add_argument("--apply", action="store_true", help="write the files")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the C20 JSON object")
    p.set_defaults(func=_cmd_new)

    p = subparsers.add_parser("lint", help="lint specs: C05, runnable gates, interfaces, never-reused ids, plans")
    p.add_argument("--spec", help="one spec id (default: every spec under specs/)")
    _common(p, spec_id=False)
    p.set_defaults(func=_cmd_lint)

    p = subparsers.add_parser("trace", help="build the C08 trace matrix of a spec (written with --apply)")
    _common(p)
    p.add_argument("--tests", action="append", help="an extra test file or folder in the feature's scope (repeatable)")
    p.add_argument("--apply", action="store_true", help="write specs/<id>/trace.json")
    p.set_defaults(func=_cmd_trace)

    p = subparsers.add_parser("show", help="print the files the freeze hashes and the approval phrase to type")
    _common(p)
    p.set_defaults(func=_cmd_show)

    p = subparsers.add_parser("approve", help="manual approval for devices where hooks do not run: type the phrase on stdin")
    _common(p)
    p.set_defaults(func=_cmd_approve)

    p = subparsers.add_parser("hook-approval", help="dry run of the spec-approval hook handler: the payload JSON on stdin; never writes")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the C20 JSON object")
    p.set_defaults(func=_cmd_hook)

    p = subparsers.add_parser("freeze", help="check that the approval still matches every hashed file (VALID or VOID)")
    _common(p)
    p.add_argument("--check", action="store_true", help="recompute and report; this is the only mode (approval is typed, never written here)")
    p.set_defaults(func=_cmd_freeze)
