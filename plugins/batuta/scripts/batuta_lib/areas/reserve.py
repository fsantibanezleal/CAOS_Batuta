"""Area `reserve`: reserve sequence numbers (a migration revision, a numbered document) before a parallel launch.

Parallel units that each need "the next number" of a shared sequence collide. The integrator reserves the numbers first;
every reservation is one row of `<coordination root>/delegation/reservations.md`:

    | Repo | Kind | N | Reserved |

`n` is one more than the highest number recorded for the `<repo>:<kind>` pair, or `--from` when that is higher (or when
nothing is recorded yet), or 1. The read-modify-write runs under an exclusive lock file next to the table, so two concurrent
reservations never get the same number. Dry run by default; `--apply` records the row.

Verbs:
    next <repo> <kind> [--from N] [--root DIR]    the next number (reserved with --apply)
    list [--root DIR]                             the recorded reservations

The coordination root is `coordination_root` of `batuta.json` under `--root` (default `.batuta`).
Exit codes: 0 ok, 1 refused (bad input, lock timeout), 2 never.
"""
import datetime as dt
import os
import re
import sys
import time
from pathlib import Path

from batuta_lib import config
from batuta_lib.output import emit, item

AREA = "reserve"
HELP = "Reservations: sequence numbers reserved under a lock before parallel units start."

HEADER = "# Reservations\n\n| Repo | Kind | N | Reserved |\n|---|---|---|---|\n"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ROW = re.compile(r"^\|\s*([^|\s]+)\s*\|\s*([^|\s]+)\s*\|\s*(\d+)\s*\|")
LOCK_TIMEOUT_S = 30.0


class ReserveError(Exception):
    """A reservation that must not be made or recorded."""


def table_path(root, env=None):
    """`<root>/<coordination_root>/delegation/reservations.md` (ConfigError when the configuration is unusable)."""
    resolved = config.load(None, project_root=root, env=env)
    return Path(root) / resolved.config.get("coordination_root", config.PROJECT_DIR) / "delegation" / "reservations.md"


def recorded(path):
    """All (repo, kind, n) rows of the reservations file; empty when it does not exist."""
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if m:
            rows.append((m.group(1), m.group(2), int(m.group(3))))
    return rows


def next_number(path, repo, kind, start):
    highest = max((n for r, k, n in recorded(path) if (r, k) == (repo, kind)), default=0)
    return max(highest + 1, start or 1)


def add(path, repo, kind, n):
    """Append one row; refuse a pair that is already recorded. The caller holds the lock."""
    path = Path(path)
    if any(row == (repo, kind, n) for row in recorded(path)):
        raise ReserveError(f"{repo}:{kind}:{n} is already reserved in {path.as_posix()}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else HEADER
    if not text.endswith("\n"):
        text += "\n"
    text += f"| {repo} | {kind} | {n} | {dt.date.today().isoformat()} |\n"
    path.write_text(text, encoding="utf-8", newline="\n")


class _Lock:
    """Exclusive lock through O_EXCL creation of a sibling file; bounded wait."""

    def __init__(self, path):
        path = Path(path)
        self.path = path.with_name(path.name + ".lock")

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise ReserveError(f"lock {self.path.as_posix()} held for over {LOCK_TIMEOUT_S:g}s; remove it if stale")
                time.sleep(0.01)
            except PermissionError as exc:
                # Windows denies the create while the previous holder's lock file is still pending deletion: wait for it
                # as for a held lock. Elsewhere a denied create is a folder that is not writable, which no wait clears.
                if not sys.platform.startswith("win"):
                    raise ReserveError(f"cannot create the lock {self.path.as_posix()}: access denied ({exc.strerror})") from exc
                if time.monotonic() > deadline:
                    raise ReserveError(f"lock {self.path.as_posix()} could not be created for over {LOCK_TIMEOUT_S:g}s "
                                       f"(access denied); check the folder's permissions") from exc
                time.sleep(0.01)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def reserve(path, repo, kind, start, apply):
    """The number for `repo:kind` in the table at `path`; recorded under the lock when `apply`."""
    for label, value in (("repo", repo), ("kind", kind)):
        if not _NAME.match(value):
            raise ReserveError(f"bad {label} {value!r}: letters, digits, '.', '_' and '-' only")
    if start is not None and start < 1:
        raise ReserveError("--from must be 1 or more")
    if not apply:
        return next_number(path, repo, kind, start)
    with _Lock(path):
        n = next_number(path, repo, kind, start)
        add(path, repo, kind, n)
        return n


# ------------------------------------------------------------------ CLI


def _flag_json(args):
    return bool(getattr(args, "json", False))


def _next(args):
    try:
        path = table_path(args.root)
        n = reserve(path, args.repo, args.kind, args.start, args.apply)
    except (ReserveError, config.ConfigError) as exc:
        return emit(AREA, "next", [item("REFUSED", str(exc))], "reserve next: refused, nothing recorded", _flag_json(args))
    pair = f"{args.repo}:{args.kind}"
    rel = path.relative_to(Path(args.root)).as_posix() if path.is_relative_to(Path(args.root)) else path.as_posix()
    if args.apply:
        items = [{**item("NEW", f"reserved {pair} number {n}", rel), "n": n}]
        summary = f"reserve next: {pair} = {n} (recorded)"
    else:
        items = [{**item("OK", f"next number for {pair} is {n}", rel), "n": n},
                 item("SKIP", "dry run: nothing recorded (use --apply)")]
        summary = f"reserve next: {pair} = {n} (dry run)"
    return emit(AREA, "next", items, summary, _flag_json(args))


def _list(args):
    try:
        path = table_path(args.root)
    except config.ConfigError as exc:
        return emit(AREA, "list", [item("FAIL", str(exc))], "reserve list: failed", _flag_json(args))
    rows = recorded(path)
    if not rows:
        return emit(AREA, "list", [item("SKIP", f"no reservations in {path.as_posix()}")], "reserve list: none", _flag_json(args))
    items = [item("OK", f"{r} {k} {n}") for r, k, n in rows]
    return emit(AREA, "list", items, f"reserve list: {len(rows)} reservation(s)", _flag_json(args))


def register(subparsers):
    p = subparsers.add_parser("next", help="the next number of a repo:kind sequence (recorded with --apply)")
    p.add_argument("repo")
    p.add_argument("kind")
    p.add_argument("--from", dest="start", type=int, default=None, help="first number when none is recorded")
    p.add_argument("--root", default=".", help="project root holding the coordination folder (default: the current folder)")
    p.add_argument("--apply", action="store_true", help="record the reservation (default: dry run)")
    p.set_defaults(func=_next)
    p = subparsers.add_parser("list", help="the recorded reservations")
    p.add_argument("--root", default=".", help="project root holding the coordination folder (default: the current folder)")
    p.set_defaults(func=_list)
