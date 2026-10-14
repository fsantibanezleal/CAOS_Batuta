"""Area `lessons`: every unit ends with a lesson.

Verb:
    check  every unit whose L7-build gate passed has a lesson line in LESSONS.md

A lesson line is `- <date> | <unit or feature> | <lesson> | <action taken>` (C19). A bullet that starts with a date must
satisfy C19 in full; any other bullet is ignored with a warning. The unit field names the feature (`001-widget`) or its
slug (`widget`). Exit codes: 0 ok, 1 failure, 2 warnings.
"""
import datetime
import re
from pathlib import Path

from batuta_lib import config, evidence, gate_model
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm
from batuta_lib.output import emit, item

AREA = "lessons"
HELP = "Lessons: every unit with a passed build has a dated lesson in LESSONS.md."
DATED_BULLET = re.compile(r"^- \d{4}-\d{2}-\d{2}\b")


def _units(root):
    """(features whose L7-build is passed, warnings)."""
    done, warns = [], []
    for status in sorted((root / "specs").glob("*/status.md")):
        feature = status.parent.name
        try:
            meta, _ = fm.parse(evidence.strip_comments(gate_model.read(status)))
        except (OSError, ValueError) as exc:
            warns.append(item("WARN", f"cannot read the status of {feature}: {exc}", status.relative_to(root).as_posix()))
            continue
        if isinstance(meta.get("gates"), dict) and meta["gates"].get("L7-build") == "passed":
            done.append(feature)
    return done, warns


def _visible(text):
    """The lines of a text with HTML comments and fenced code blanked (line numbers are kept): a lesson in a comment or a
    code block is not a lesson."""
    out, fence = [], None
    for line in evidence.strip_comments(text).split("\n"):
        m = re.match(r"^\s*(```|~~~)", line)
        if m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
            out.append("")
        else:
            out.append("" if fence else line)
    return out


def _lesson_lines(path, today):
    """(units named, items) of the lesson lines in a file."""
    sp = core.find_schema(config.contracts_dir(), "C19")
    schema = core.load_schema(sp)
    named, items = set(), []
    for n, line in enumerate(_visible(path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")), 1):
        if not line.startswith("- "):
            continue
        if not DATED_BULLET.match(line):
            items.append(item("WARN", f"line {n} is a bullet but not a lesson line (- date | unit | lesson | action); ignored", path.name))
            continue
        errors = core.validate(line, schema)
        date = line[2:12]
        if errors:
            items.append(item("FAIL", f"line {n} is not a valid lesson line (- date | unit | lesson | action): {errors[0]}", path.name))
        elif any(not part.strip() for part in line[2:].split(" | ")):
            items.append(item("FAIL", f"line {n}: a lesson line has no blank field (date, unit, lesson, action)", path.name))
        elif not core._is_date(date):
            items.append(item("FAIL", f"line {n}: {date} is not a calendar date", path.name))
        elif date > today:
            items.append(item("FAIL", f"line {n}: the lesson is dated {date}, after today ({today})", path.name))
        else:
            named.add(line.split(" | ")[1].strip())
    return named, items


def _check(args):
    root = Path(args.root or ".")
    today = args.today or datetime.date.today().isoformat()
    lessons = root / (args.lessons or "LESSONS.md")
    units, items = _units(root)
    named = set()
    if lessons.is_file():
        named, found = _lesson_lines(lessons, today)
        items.extend(found)
    for feature in units:
        slug = re.sub(r"^\d{3}-", "", feature)
        if feature in named or slug in named:
            items.append(item("OK", f"{feature}: has a lesson line"))
        else:
            items.append(item("FAIL", f"MISSING lesson line for {feature}: its L7-build passed and {lessons.name} has no "
                                      f"'- <date> | {feature} | <lesson> | <action>' line", lessons.name))
    if not units:
        items.append(item("OK", "no unit has a passed L7-build, so no lesson is owed yet"))
    bad = [i for i in items if i["tag"] == "FAIL"]
    return emit(AREA, "check", items, f"{len(bad)} problem(s)" if bad else "every finished unit has its lesson", bool(getattr(args, "json", False)))


def register(subparsers):
    p = subparsers.add_parser("check", help="every unit with a passed build has a lesson line")
    p.add_argument("--root", help="the project folder (default: the current folder)")
    p.add_argument("--lessons", help="the lessons file relative to the root (default LESSONS.md)")
    p.add_argument("--today", help="today's date YYYY-MM-DD (tests)")
    p.set_defaults(func=_check)
