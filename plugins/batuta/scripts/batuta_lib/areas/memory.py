"""Area `memory`: regenerate a project's auto-memory index as topic pages (`memory index`).

Claude Code loads only the first 200 lines or 25 KB of a project's MEMORY.md at session start. `memory index`
rewrites MEMORY.md as pinned memories plus one line per topic, and writes one page per topic, using the topics
file (C13) and the memory budget of C01 (or a C14 file). Dry run by default; `--apply` writes. Exit codes: 0 ok,
1 failure or an index over budget (nothing written), 2 the project is not opted in, or a dangling entry or a
missing pin was reported.
"""
import re
from pathlib import Path

from batuta_lib import config
from batuta_lib import contract as core
from batuta_lib import memory_index as mi
from batuta_lib import render
from batuta_lib.output import emit, item

AREA = "memory"
HELP = "Auto-memory: regenerate a project's MEMORY.md as a short index plus topic pages."
TOPICS_FILE = "memory_topics.json"


def _load_json(path, cid):
    """The parsed JSON file validated against contract `cid`. Raises ValueError with the reason."""
    try:
        doc = core.loads_strict(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ValueError(f"cannot read {Path(path).as_posix()}: {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"{Path(path).as_posix()}: invalid JSON ({exc})") from exc
    sp = core.find_schema(config.contracts_dir(), cid)
    errors = core.validate_instance(cid, doc, core.load_schema(sp))
    if errors:
        raise ValueError(f"{Path(path).as_posix()} does not satisfy {cid}: " + "; ".join(errors[:3]))
    return doc


def _budget(args):
    """(max bytes, max lines) of the memory index: a C14 file when given, else the C01 budgets."""
    if getattr(args, "budget", None):
        doc = _load_json(args.budget, "C14")
    else:
        try:
            doc = config.load(getattr(args, "config", None)).config["budgets"]
        except config.ConfigError as exc:
            raise ValueError(str(exc)) from exc
    return doc["memory_index_bytes"], doc["memory_index_lines"]


def _index(args):
    as_json = getattr(args, "json", False)
    items = []

    def done(summary):
        return emit(AREA, "index", items, summary, as_json)

    topics_path = Path(args.topics) if args.topics else config.home_dir() / TOPICS_FILE
    if not topics_path.is_file():
        items.append(item("WARN", f"project {args.project!r} is not opted in: no topics file at "
                                  f"{topics_path.as_posix()}; nothing written"))
        return done("memory index: not opted in")
    try:
        cfg = _load_json(topics_path, "C13")
        max_bytes, max_lines = _budget(args)
    except ValueError as exc:
        items.append(item("FAIL", str(exc)))
        return done("memory index: failed")
    project_cfg = cfg.get("projects", {}).get(args.project)
    if project_cfg is None:
        items.append(item("WARN", f"project {args.project!r} is not opted in ({topics_path.as_posix()}); nothing written"))
        return done("memory index: not opted in")
    memory_dir = Path(args.memory_dir)
    if not memory_dir.is_dir():
        items.append(item("FAIL", f"memory folder not found: {memory_dir.as_posix()}"))
        return done("memory index: failed")

    try:
        index_text, pages, report = mi.build(memory_dir, project_cfg, cfg, getattr(args, "adopt_legacy", False))
    except re.error as exc:
        items.append(item("FAIL", f"C13 match pattern is not a valid regular expression: {exc}"))
        return done("memory index: failed")
    except (OSError, RuntimeError, UnicodeDecodeError) as exc:
        items.append(item("FAIL", f"cannot build the index: {exc}"))
        return done("memory index: failed")
    items.append(item("OK", f"{report['files']} memories in {len(pages)} topic page(s); index "
                            f"{report['index_bytes']} bytes, {report['index_lines']} lines "
                            f"(budget {max_bytes} bytes, {max_lines} lines)"))
    for stem in report["dangling"]:
        items.append(item("WARN", f"DANGLING (old entry, no file, dropped): {stem}"))
    for stem in report["missing_pins"]:
        items.append(item("WARN", f"MISSING PIN (pinned, no file): {stem}"))
    if report["index_bytes"] > max_bytes or report["index_lines"] > max_lines:
        items.append(item("REFUSED", f"index over budget ({report['index_bytes']} bytes, {report['index_lines']} lines; "
                                     f"max {max_bytes} bytes, {max_lines} lines); nothing written; add a topic or "
                                     f"narrow a topic's match so a page absorbs the entries"))
        return done("memory index: refused")

    targets = {memory_dir / "MEMORY.md": index_text}
    targets.update({memory_dir / "topics" / f"{tid}.md": text for tid, text in pages.items()})
    topics_dir = memory_dir / "topics"
    adopt = getattr(args, "adopt_legacy", False)
    topic_ids = {t["id"] for t in project_cfg.get("topics", [])} | {"other"}

    def generated(p):
        # A page this tool wrote carries the mark. With --adopt-legacy, a page named like a topic id is also taken
        # as generated (pages written before the mark existed); without it, an unmarked file is the owner's.
        return mi.PAGE_MARK in p.read_text(encoding="utf-8", errors="replace") or (adopt and p.stem in topic_ids)

    collisions = [p for p in targets if p.parent == topics_dir and p.is_file() and not generated(p)]
    if collisions:
        for p in collisions:
            items.append(item("FAIL", f"{p.relative_to(memory_dir).as_posix()} exists without the generation mark; "
                                      f"refusing to overwrite a hand-written file; move it, or pass --adopt-legacy "
                                      f"if it is a page written by an older version of this tool"))
        return done("memory index: failed, nothing written")
    stale = []
    if topics_dir.is_dir():
        stale = [p for p in sorted(topics_dir.glob("*.md")) if p.is_file() and p not in targets and generated(p)]
    for path, text in targets.items():
        items.append(item(render.status(path, text), path.relative_to(memory_dir).as_posix()))
    for path in stale:
        items.append(item("REMOVED", path.relative_to(memory_dir).as_posix()))
    if not args.apply:
        return done("memory index: dry run, nothing written (use --apply)")
    for path, text in targets.items():
        if render.status(path, text) != "SAME":
            render.write_atomic(path, text)
    for path in stale:
        path.unlink()
    return done("memory index: written")


def register(subparsers):
    p = subparsers.add_parser("index", help="regenerate MEMORY.md as pinned lines plus topic pages")
    p.add_argument("--memory-dir", required=True, help="the project's memory folder (holds MEMORY.md and the memories)")
    p.add_argument("--project", required=True, help="project name as listed in the topics file")
    p.add_argument("--topics", help=f"topics file (C13; default: <BATUTA_HOME>/{TOPICS_FILE})")
    p.add_argument("--budget", help="a C14 budget file; default: the budgets of the resolved batuta.json (C01)")
    p.add_argument("--apply", action="store_true", help="write the files (default: dry run)")
    p.add_argument("--adopt-legacy", action="store_true",
                   help="treat unmarked topic pages named like a topic id as generated (migrates pages written "
                        "before the generation mark); without it such a file is never overwritten or removed")
    p.set_defaults(func=_index)
