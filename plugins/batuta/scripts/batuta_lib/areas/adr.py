"""Area `adr`: architecture decision records with a lifecycle (C24).

`adr new --title T [--apply]` writes `docs/decisions/ADR-NNNN-<slug>.md` from the ADR template, the next free number, status
Proposed. `adr lint` validates every ADR against C24 and checks the lifecycle: ids are unique and carried by the file name,
supersession links resolve, are reciprocal and never point at the ADR itself (FAIL), a `review-by: YYYY-MM-DD` trigger in the
past is overdue (WARN; a condition-style trigger is not machine-checkable), and an Accepted ADR that lists technology
evaluations needs their C25 files to exist and be decided. A project without the folder gets SKIP. A change goes through a
new ADR that supersedes the old one, never an edit in place. Exit codes: 0 ok, 1 failure, 2 warnings.
"""
import argparse
import re
from datetime import date, timedelta
from pathlib import Path

from batuta_lib import config
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm
from batuta_lib import render
from batuta_lib import spec_model as sm
from batuta_lib.output import emit, item

AREA = "adr"
HELP = "Architecture decisions: new ADR from the template, lint the lifecycle."

_REVIEW_BY = re.compile(r"review-by:\s*(\d{4}-\d{2}-\d{2})")
_FILE = re.compile(r"(ADR-\d{4})(?:-.*)?\.md\Z")
TEMPLATE = Path(__file__).resolve().parents[2].parent / "templates" / "spec" / "adr.md"


def _files(folder):
    return sorted(f for f in folder.glob("ADR-*.md")) if folder.is_dir() else []


def next_number(folder):
    nums = [int(m.group(1)[4:]) for f in _files(folder) if (m := _FILE.match(f.name))]
    return max(nums, default=0) + 1


def new(root, title, apply=False, decider=None, today=None):
    folder = Path(root) / sm.ADR_DIR
    today = today or date.today()
    adr_id = f"ADR-{next_number(folder):04d}"
    values = {"id": adr_id, "title": title, "date": today.isoformat(), "decider": decider or _user(),
              "review_by": (today + timedelta(days=183)).isoformat()}
    text = render.render_file(TEMPLATE, values)
    path = folder / f"{adr_id}-{sm.slugify(title)}.md"
    status = render.status(path, text)
    if apply and status == "NEW":
        render.write_atomic(path, text)
    return [item(status, f"{adr_id} {title}" + ("" if apply else " (dry run; --apply writes it)"), sm.rel(path, root))]


def _user():
    from batuta_lib import approval
    return approval.current_user()


def _decided(root, tech_id, c25):
    """None when the technology decision file exists, satisfies C25 and names a chosen candidate, else the reason."""
    f = Path(root) / sm.TECH_DIR / f"{tech_id}.json"
    if not f.is_file():
        return f"{sm.TECH_DIR}/{tech_id}.json does not exist"
    errors = core.validate_file(f, c25, "C25")
    if errors:
        return f"{sm.TECH_DIR}/{tech_id}.json: {errors[0]}"
    doc = core.loads_strict(f.read_text(encoding="utf-8-sig"))
    if not doc.get("evaluation", {}).get("chosen"):
        return f"{sm.TECH_DIR}/{tech_id}.json has no evaluation with a chosen candidate (not decided)"
    return None


def lint(root=".", today=None):
    root = Path(root)
    today = today or date.today()
    folder = root / sm.ADR_DIR
    files = _files(folder)
    if not files:
        return [item("SKIP", f"no ADRs under {sm.ADR_DIR}/", sm.ADR_DIR)]
    _, _, sp = sm.schema_and_sections("C24")
    c25 = core.find_schema(config.contracts_dir(), "C25")
    items, docs = [], {}
    for f in files:
        label = sm.rel(f, root)
        errors = core.validate_file(f, sp, "C24")
        if errors:
            items.extend(item("FAIL", f"{label}: {e}", label) for e in errors)
        try:
            meta = fm.parse(f.read_text(encoding="utf-8-sig"))[0]
        except ValueError:
            continue
        adr_id = meta.get("id")
        m = _FILE.match(f.name)
        if adr_id and (not m or m.group(1) != adr_id):
            items.append(item("FAIL", f"{label}: the file name must start with the ADR id {adr_id}", label))
        if adr_id in docs:
            items.append(item("FAIL", f"{label}: the id {adr_id} is already used by {docs[adr_id][0]}", label))
        elif adr_id:
            docs[adr_id] = (label, meta, not errors)
    for adr_id, (label, meta, ok) in sorted(docs.items()):
        status = meta.get("status")
        for target in ([meta["superseded_by"]] if isinstance(meta.get("superseded_by"), str) else []):
            if target == adr_id:
                items.append(item("FAIL", f"{label}: {adr_id} supersedes itself (superseded_by names itself)", label))
            elif target not in docs:
                items.append(item("FAIL", f"{label}: superseded_by {target} is not an ADR of this project", label))
            elif adr_id not in (docs[target][1].get("supersedes") or []):
                items.append(item("FAIL", f"{label}: {target} must list {adr_id} under supersedes (the link is not reciprocal)", label))
        for target in meta.get("supersedes") or []:
            if target == adr_id:
                items.append(item("FAIL", f"{label}: {adr_id} supersedes itself", label))
            elif target not in docs:
                items.append(item("FAIL", f"{label}: supersedes {target}, which is not an ADR of this project", label))
            elif docs[target][1].get("superseded_by") != adr_id:
                items.append(item("FAIL", f"{label}: {target} must say superseded_by: {adr_id} (the link is not reciprocal)", label))
        if isinstance(meta.get("superseded_by"), str) and status in ("Proposed", "Accepted"):
            items.append(item("FAIL", f"{label}: {adr_id} is {status} but names superseded_by {meta['superseded_by']}; "
                                      "a superseded ADR has the status Superseded", label))
        trig = _REVIEW_BY.search(str(meta.get("review_trigger", "")))
        if trig and status in ("Proposed", "Accepted"):
            try:
                due = date.fromisoformat(trig.group(1))
            except ValueError:
                items.append(item("FAIL", f"{label}: review-by date {trig.group(1)} is not on the calendar", label))
            else:
                if due < today:
                    items.append(item("WARN", f"{label}: the review is overdue (review-by {due.isoformat()}); revisit {adr_id} or supersede it", label))
        if status == "Accepted":
            for tech_id in meta.get("tech_evaluations") or []:
                why = _decided(root, tech_id, c25)
                if why:
                    items.append(item("FAIL", f"{label}: Accepted but its technology evaluation '{tech_id}' is not decided: {why}", label))
    seen_cycles = set()
    for start in sorted(docs):
        chain, cur = [start], docs[start][1].get("superseded_by")
        while isinstance(cur, str) and cur in docs and cur != chain[-1]:
            if cur in chain:
                loop = chain[chain.index(cur):]
                if frozenset(loop) not in seen_cycles:
                    seen_cycles.add(frozenset(loop))
                    items.append(item("FAIL", "supersession cycle: " + " to ".join(loop + [cur]), docs[loop[0]][0]))
                break
            chain.append(cur)
            cur = docs[cur][1].get("superseded_by")
    if not any(i["tag"] in ("FAIL", "WARN") for i in items):
        items.append(item("OK", f"{len(files)} ADR(s) satisfy C24 and the lifecycle rules", sm.ADR_DIR))
    return items


def _flag(args):
    return bool(getattr(args, "json", False))


def _cmd_new(args):
    items = new(args.root, args.title, args.apply, args.decider)
    return emit(AREA, "new", items, "adr new: " + ("written" if args.apply else "dry run"), _flag(args))


def _cmd_lint(args):
    today = date.fromisoformat(args.today) if args.today else None
    items = lint(args.root, today)
    n = {t: sum(1 for i in items if i["tag"] == t) for t in ("OK", "WARN", "FAIL", "SKIP")}
    return emit(AREA, "lint", items, f"adr lint: {n['OK']} ok, {n['SKIP']} skipped, {n['WARN']} warning(s), {n['FAIL']} failure(s)", _flag(args))


def register(subparsers):
    p = subparsers.add_parser("new", help="create the next ADR from the template (dry run unless --apply)")
    p.add_argument("--root", default=".", help="project root (default: the current folder)")
    p.add_argument("--title", required=True)
    p.add_argument("--decider", help="the decider's name (default: the current user)")
    p.add_argument("--apply", action="store_true", help="write the file")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the C20 JSON object")
    p.set_defaults(func=_cmd_new)
    p = subparsers.add_parser("lint", help="lint the ADRs: C24, supersession links, overdue reviews, technology evaluations")
    p.add_argument("--root", default=".", help="project root (default: the current folder)")
    p.add_argument("--today", help="YYYY-MM-DD to measure review dates from (default: today)")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the C20 JSON object")
    p.set_defaults(func=_cmd_lint)
