"""Area `fragments`: merge per-unit fragments into shared files so parallel units never edit them.

Parallel units write `changes/<unit-id>.md` (bullet lines for the Unreleased section) and `i18n/<unit-id>.csv` (dictionary
rows); the integrator merges them here, in file-name order.

Verbs:
    changelog <repo dir>             merge `<repo dir>/changes/*.md` under `## [Unreleased]` of `CHANGELOG.md`
    i18n <csv> <fragment dir>        merge `<fragment dir>/*.csv` into the dictionary csv

Dry run by default: the lines that would be merged are listed and nothing is written or deleted. `--apply` writes the merged
file and then deletes the merged fragments. A refusal (duplicate key, a fragment that is not bullets, a missing heading)
changes nothing and exits 1.

A file named `<unit>-plugin-readme.md` in `changes/` holds a README section, not a changelog fragment, and is skipped.
A changelog fragment holds bullet lines only (`- ...`, continuation lines indented), no headings. An i18n fragment may repeat
the dictionary header line (it is dropped; a different header is refused). The dictionary header and its line ending are
kept and existing rows are never touched or reordered. When the existing keys are sorted, new rows are inserted at their
sorted position, otherwise appended in fragment order. A key present twice (dictionary or fragments) is refused with the
list of keys and files.

Exit codes: 0 ok, 1 refused or failed.
"""
import bisect
import csv
import io
import os
import re
import tempfile
from pathlib import Path

from batuta_lib.output import emit, item

AREA = "fragments"
HELP = "Fragments: merge per-unit changelog bullets and i18n rows into the shared files."

_UNRELEASED = re.compile(r"^##\s+\[Unreleased\]", re.IGNORECASE)
_H2 = re.compile(r"^##\s")
_BULLET = re.compile(r"^\s*[-*]\s")
PLUGIN_README_SUFFIX = "-plugin-readme.md"   # sections for the plugin README share the folder; they are not changelog fragments


class FragmentError(Exception):
    """A merge that must be refused; nothing is written."""


def _read(path):
    return Path(path).read_bytes().decode("utf-8")


def _eol(text):
    return "\r\n" if "\r\n" in text else "\n"


def _write(path, text):
    """Atomic write of `text` as UTF-8 exactly as given (line endings are the caller's)."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _rel(path, root):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


# ------------------------------------------------------------------ changelog


def plan_changelog(repo):
    """(new text, [(fragment name, line)], [fragment paths]) for `repo`; FragmentError when it must be refused.
    The text is None when there is nothing to merge."""
    repo = Path(repo)
    changelog = repo / "CHANGELOG.md"
    if not changelog.is_file():
        raise FragmentError(f"{changelog.as_posix()} not found")
    folder = repo / "changes"
    files = sorted((p for p in folder.glob("*.md") if not p.name.endswith(PLUGIN_README_SUFFIX)),
                   key=lambda p: p.name) if folder.is_dir() else []
    if not files:
        return None, [], []
    old = _read(changelog)
    eol = _eol(old)
    lines = old.split(eol)
    start = next((i for i, ln in enumerate(lines) if _UNRELEASED.match(ln)), None)
    if start is None:
        raise FragmentError(f"{changelog.as_posix()} has no '## [Unreleased]' heading")
    end = next((i for i in range(start + 1, len(lines)) if _H2.match(lines[i])), len(lines))
    existing = {ln.strip() for ln in lines[start + 1:end]}
    added, new_lines = [], []
    for f in files:
        for raw in _read(f).replace("\r\n", "\n").split("\n"):
            if not raw.strip():
                continue
            if not _BULLET.match(raw) and not raw.startswith((" ", "\t")):
                raise FragmentError(f"{f.name}: not a bullet line: {raw!r}")
            if _BULLET.match(raw) and raw.strip() in existing:
                continue
            new_lines.append(raw.rstrip())
            added.append((f.name, raw.rstrip()))
            if _BULLET.match(raw):
                existing.add(raw.strip())
    # insert after the last non-blank line of the section so the blank line before the next heading stays
    ins = end
    while ins > start + 1 and not lines[ins - 1].strip():
        ins -= 1
    if ins == start + 1 and new_lines:
        lines[ins:ins] = [""] + new_lines
    else:
        lines[ins:ins] = new_lines
    return eol.join(lines), added, files


def merge_changelog(repo, apply):
    items = []
    try:
        text, added, files = plan_changelog(repo)
    except FragmentError as exc:
        return [item("REFUSED", str(exc))], "fragments changelog: refused, nothing changed"
    if text is None:
        return [item("SKIP", "no fragments in changes/")], "fragments changelog: nothing to merge"
    items.extend(item("MERGED", f"{name}: {line}") for name, line in added)
    if apply:
        _write(Path(repo) / "CHANGELOG.md", text)
        for f in files:
            f.unlink()
            items.append(item("REMOVED", _rel(f, repo)))
        return items, f"fragments changelog: merged {len(added)} line(s) from {len(files)} fragment(s) (applied)"
    items.append(item("SKIP", "dry run: nothing written (use --apply)"))
    return items, f"fragments changelog: {len(added)} line(s) from {len(files)} fragment(s) (dry run)"


# ------------------------------------------------------------------ i18n


def _records(text, eol):
    """Split csv text into (raw chunk, parsed fields), one per record (a quoted field may span lines)."""
    raw_lines = text.split(eol)
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()
    reader = csv.reader(io.StringIO(eol.join(raw_lines), newline=""))
    out, consumed = [], 0
    for fields in reader:
        upto = reader.line_num
        out.append((eol.join(raw_lines[consumed:upto]), fields))
        consumed = upto
    return out


def plan_i18n(csv_path, frag_dir):
    """(new text, [(fragment name, row)], [fragment paths]); the text is None when there is nothing to merge."""
    csv_path, frag_dir = Path(csv_path), Path(frag_dir)
    if not csv_path.is_file():
        raise FragmentError(f"{csv_path.as_posix()} not found")
    files = sorted(frag_dir.glob("*.csv"), key=lambda p: p.name) if frag_dir.is_dir() else []
    if not files:
        return None, [], []
    old = _read(csv_path)
    eol = _eol(old)
    trailing = old.endswith(eol)
    recs = _records(old, eol)
    if not recs:
        raise FragmentError(f"{csv_path.as_posix()} is empty (no header)")
    header_raw, header = recs[0]
    chunks = [raw for raw, _ in recs[1:]]
    keys = [f[0] if f else "" for _, f in recs[1:]]
    owner = {k: csv_path.name for k in keys}
    dupes, new_rows = {}, []
    for f in files:
        text = _read(f)
        for raw, fields in _records(text, _eol(text)):
            if not fields:
                continue
            if raw == header_raw or fields == header:
                continue
            if fields[0] == header[0]:
                raise FragmentError(f"{f.name}: header {fields} differs from the dictionary header {header}")
            key = fields[0]
            if key in owner:
                dupes.setdefault(key, [owner[key]]).append(f.name)
            else:
                owner[key] = f.name
                new_rows.append((key, raw, f.name))
    if dupes:
        listing = "\n".join(f"  {k}: {', '.join(v)}" for k, v in sorted(dupes.items()))
        raise FragmentError(f"duplicate keys refused ({len(dupes)}):\n{listing}")
    is_sorted = keys == sorted(keys)
    for key, raw, _ in new_rows:
        pos = bisect.bisect_left(keys, key) if is_sorted else len(keys)
        keys.insert(pos, key)
        chunks.insert(pos, raw)
    new = eol.join([header_raw, *chunks]) + (eol if trailing else "")
    return new, [(name, raw) for _, raw, name in new_rows], files


def merge_i18n(csv_path, frag_dir, apply):
    try:
        text, added, files = plan_i18n(csv_path, frag_dir)
    except FragmentError as exc:
        return [item("REFUSED", str(exc))], "fragments i18n: refused, nothing changed"
    if text is None:
        return [item("SKIP", f"no fragments in {Path(frag_dir).as_posix()}")], "fragments i18n: nothing to merge"
    items = [item("MERGED", f"{name}: {row}") for name, row in added]
    if apply:
        _write(csv_path, text)
        for f in files:
            f.unlink()
            items.append(item("REMOVED", f.name))
        return items, f"fragments i18n: merged {len(added)} row(s) from {len(files)} fragment(s) (applied)"
    items.append(item("SKIP", "dry run: nothing written (use --apply)"))
    return items, f"fragments i18n: {len(added)} row(s) from {len(files)} fragment(s) (dry run)"


# ------------------------------------------------------------------ CLI


def _changelog(args):
    items, summary = merge_changelog(args.repo_dir, args.apply)
    return emit(AREA, "changelog", items, summary, bool(getattr(args, "json", False)))


def _i18n(args):
    items, summary = merge_i18n(args.csv, args.fragment_dir, args.apply)
    return emit(AREA, "i18n", items, summary, bool(getattr(args, "json", False)))


def register(subparsers):
    p = subparsers.add_parser("changelog", help="merge changes/*.md bullets under [Unreleased] of CHANGELOG.md")
    p.add_argument("repo_dir", help="the repository folder holding CHANGELOG.md and changes/")
    p.add_argument("--apply", action="store_true", help="write and delete the fragments (default: dry run)")
    p.set_defaults(func=_changelog)
    p = subparsers.add_parser("i18n", help="merge *.csv fragments into the dictionary csv")
    p.add_argument("csv", help="the dictionary csv")
    p.add_argument("fragment_dir", help="the folder of i18n fragments")
    p.add_argument("--apply", action="store_true", help="write and delete the fragments (default: dry run)")
    p.set_defaults(func=_i18n)
