"""The install manifest: what `init` wrote, so `update` and `uninstall` act on exactly that and nothing else.

The manifest is internal state of the `init` area (no other unit reads it, so it has no catalog contract). It lives in
`<deploy root>/installed.json` for `init user` and in `<project>/.batuta/installed.json` for `init project`, and holds:

- `kind`: `user` or `project`
- `bases`: the folders the entries are relative to (`deploy` and `claude` for a user install, absolute; `project` and
  `anchor`, the nearest folder that already existed, for a project, relative to the project root so that a manifest
  committed with the project carries no machine path)
- `variables`: the values the templates were rendered with (`update` renders again with them)
- `files`: for each file init wrote, its `base`, relative `path`, the `sha256` of its text with LF line endings (so a
  checkout that converts line endings is not an edit), the `backup` file name of what init replaced (restored by
  `uninstall`; null when the file did not exist) and the `previous` backups later updates made of changed files
  (kept, never restored: they hold the user's own edits)
- `dirs`: the folders init created, removed again when empty

A path is relative, POSIX, without a `..` or `.` segment, a drive or an empty segment; anything else is refused when it is
recorded and when a manifest is read, so a hand-edited manifest cannot point an uninstall outside its base.
"""
import hashlib
import json
import os
import re
from pathlib import Path

from batuta_lib import render

FILE_NAME = "installed.json"
VERSION = 1
KINDS = ("user", "project")
_REL = re.compile(r"^(?![\s\S]*(^|/)\.\.?(/|$))(?![\s\S]*//)[^/\\:\x00-\x1f][^\\:\x00-\x1f]*$")


class ManifestError(ValueError):
    """The manifest or a path in it cannot be used; the message says why."""


def sha256_bytes(data):
    """The sha256 of `data` with CRLF and CR line endings read as LF."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def check_rel(rel, allow_dot=False):
    """`rel` when it is a safe relative POSIX path (or `.` when `allow_dot`), else ManifestError."""
    if allow_dot and rel == ".":
        return rel
    if not isinstance(rel, str) or not rel or not _REL.match(rel):
        raise ManifestError(f"{rel!r} is not a relative path inside its base (no '..', drive, leading slash or empty segment)")
    return rel


class Manifest:
    def __init__(self, path, kind, bases=None, variables=None):
        if kind not in KINDS:
            raise ManifestError(f"kind must be one of {', '.join(KINDS)}, not {kind!r}")
        self.path = Path(path)
        self.kind = kind
        self.bases = dict(bases or {})
        self.variables = dict(variables or {})
        self.files = []
        self.dirs = []

    # ------------------------------------------------------------------ reading and writing

    @classmethod
    def load(cls, path, expect=None):
        """The manifest at `path`, or None when there is none. ManifestError when it is unreadable or unsound, or when a base
        leaves the folder it was installed into. A project manifest may name only the project (`.`) and an `anchor` that is
        `.` or an ancestor of the project (`..`, `../..`); a user manifest only the `deploy` folder it sits in and the
        `claude` folder, which must equal `expect["claude"]` (and `expect["deploy"]`) when the caller passes them."""
        path = Path(path)
        if not path.is_file():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise ManifestError(f"{path.as_posix()} cannot be read ({exc}); remove it only after checking what init wrote") from exc
        if not isinstance(doc, dict) or doc.get("manifest_version") != VERSION:
            raise ManifestError(f"{path.as_posix()} is not an install manifest of version {VERSION}")
        kind = doc.get("kind")
        manifest = cls(path, kind, doc.get("bases") if isinstance(doc.get("bases"), dict) else {},
                       doc.get("variables") if isinstance(doc.get("variables"), dict) else {})
        manifest.check_bases(expect)
        for entry in doc.get("files", []):
            if not isinstance(entry, dict) or entry.get("base") not in manifest.bases:
                raise ManifestError(f"{path.as_posix()} has a file entry with an unknown base: {entry!r}")
            check_rel(entry.get("path"))
            if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))):
                raise ManifestError(f"{path.as_posix()}: the hash of {entry['path']} is not a sha256")
            for name in [entry.get("backup"), *entry.get("previous", [])]:
                if name is not None and (not isinstance(name, str) or "/" in name or "\\" in name or name in ("", ".", "..")):
                    raise ManifestError(f"{path.as_posix()}: the backup name {name!r} of {entry['path']} is not a file name")
            manifest.files.append({"base": entry["base"], "path": entry["path"], "sha256": entry["sha256"],
                                   "backup": entry.get("backup"), "previous": list(entry.get("previous", [])),
                                   "seed": bool(entry.get("seed", False))})
        for entry in doc.get("dirs", []):
            if not isinstance(entry, dict) or entry.get("base") not in manifest.bases:
                raise ManifestError(f"{path.as_posix()} has a folder entry with an unknown base: {entry!r}")
            check_rel(entry.get("path"), allow_dot=True)
            manifest.dirs.append({"base": entry["base"], "path": entry["path"]})
        manifest.check_anchor_entries()
        return manifest

    def check_bases(self, expect=None):
        """ManifestError unless every base stays where this kind of install put it (see `load`)."""
        name = self.path.as_posix()
        bases = self.bases
        if self.kind == "project":
            if set(bases) - {"project", "anchor"} or bases.get("project") != ".":
                raise ManifestError(f"{name}: a project manifest names only the project ('.') and its anchor, not {bases!r}")
            anchor = bases.get("anchor", ".")
            if not isinstance(anchor, str) or not re.fullmatch(r"\.|\.\.(/\.\.)*", anchor):
                raise ManifestError(f"{name}: the anchor {anchor!r} is not the project or one of its ancestors ('..', '../..')")
            return
        if set(bases) - {"deploy", "claude"} or not set(bases) >= {"deploy", "claude"}:
            raise ManifestError(f"{name}: a user manifest names only the deploy and claude folders, not {bases!r}")
        same = lambda a, b: os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))   # noqa: E731
        for key, value in bases.items():
            if not isinstance(value, str) or not (Path(value).is_absolute() or re.match(r"^[A-Za-z]:", value)):
                raise ManifestError(f"{name}: the {key} base {value!r} is not an absolute folder")
        if not same(bases["deploy"], self.path.parent):
            raise ManifestError(f"{name}: the deploy base {bases['deploy']!r} is not the folder this manifest sits in")
        for key, folder in (expect or {}).items():
            if key in bases and not same(bases[key], folder):
                raise ManifestError(f"{name}: the {key} base {bases[key]!r} is not {Path(folder).as_posix()!r}, "
                                    "the folder this command works on")

    def check_anchor_entries(self):
        """The `anchor` base (the nearest folder that existed when a nested project was created, an ancestor of the project)
        holds folders only, and only folders on the project's own path or inside the project: a file entry on it, or a folder
        beside the project, is refused."""
        if self.kind != "project" or "anchor" not in self.bases:
            return
        name = self.path.as_posix()
        project = os.path.normcase(os.path.normpath(self.path.parent.parent))
        anchor = self.base_dir("anchor")
        for entry in self.files:
            if entry["base"] == "anchor":
                raise ManifestError(f"{name}: a file entry on the anchor ({entry['path']}); the anchor holds folders only")
        for entry in self.dirs:
            if entry["base"] != "anchor":
                continue
            rel = "" if entry["path"] == "." else entry["path"]
            folder = os.path.normcase(os.path.normpath(anchor / rel))
            on_path = project == folder or project.startswith(folder + os.sep)
            inside = folder.startswith(project + os.sep)
            if not (on_path or inside):
                raise ManifestError(f"{name}: the anchor folder {entry['path']!r} is neither on the project's own path nor "
                                    "inside the project")

    def link_problems(self):
        """Entries whose real path (links followed) leaves the folder of their base, as text; empty when sound."""
        problems = []
        for entry in [*self.files, *self.dirs]:
            base = os.path.realpath(self.base_dir(entry["base"]))
            rel = "" if entry["path"] == "." else entry["path"]
            real = os.path.realpath(os.path.join(base, rel))
            if os.path.normcase(real) != os.path.normcase(base) and not os.path.normcase(real).startswith(os.path.normcase(base) + os.sep):
                problems.append(f"{entry['path']} resolves to {Path(real).as_posix()}, outside its base")
        return problems

    def text(self):
        doc = {"manifest_version": VERSION, "kind": self.kind, "bases": self.bases, "variables": self.variables,
               "files": sorted(self.files, key=lambda e: (e["base"], e["path"])), "dirs": self.dirs}
        return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"

    def save(self):
        """Write the manifest atomically (LF, UTF-8, stable: the same content gives the same bytes)."""
        render.write_atomic(self.path, self.text())

    def delete(self):
        self.path.unlink()

    # ------------------------------------------------------------------ entries

    def base_dir(self, base):
        """The folder of a base: an absolute path as written, or a path relative to the project root (the folder that holds
        the `.batuta` folder of this manifest), so a manifest committed with a project holds no machine path."""
        value = self.bases[base]
        if Path(value).is_absolute() or re.match(r"^[A-Za-z]:", value):
            return Path(value)
        return Path(os.path.normpath(self.path.parent.parent / value))

    def entry(self, base, rel):
        for e in self.files:
            if e["base"] == base and e["path"] == rel:
                return e
        return None

    def record(self, base, rel, data, backup=None, seed=False):
        """Record that init wrote `rel` with content `data` (bytes). `backup` is the name of the file that holds what it
        replaced. On a file already recorded the hash is replaced; the first backup stays what `uninstall` restores and a
        later one is kept as a `previous` copy. `seed` marks a file the user owns after the first install."""
        if base not in self.bases:
            raise ManifestError(f"unknown base {base!r}")
        check_rel(rel)
        digest = sha256_bytes(data)
        existing = self.entry(base, rel)
        if existing is None:
            self.files.append({"base": base, "path": rel, "sha256": digest, "backup": backup, "previous": [],
                               "seed": bool(seed)})
            return
        existing["sha256"] = digest
        if backup:
            existing["previous"].append(backup)

    def forget(self, base, rel):
        self.files = [e for e in self.files if not (e["base"] == base and e["path"] == rel)]

    def record_dir(self, base, rel):
        check_rel(rel, allow_dot=True)
        item = {"base": base, "path": rel}
        if item not in self.dirs:
            self.dirs.append(item)

    def forget_dir(self, base, rel):
        self.dirs = [d for d in self.dirs if not (d["base"] == base and d["path"] == rel)]

    def state(self, base_dir, rel):
        """SAME when the file holds what init recorded, DIFFERENT when it changed (or is not a file), MISSING when gone."""
        target = Path(base_dir) / rel
        same_path = [e for e in self.files if e["path"] == rel]
        here = [e for e in same_path if os.path.normcase(os.path.abspath(self.base_dir(e["base"])))
                == os.path.normcase(os.path.abspath(base_dir))]
        entry = (here or same_path or [None])[0]
        if not target.exists() and not target.is_symlink():
            return "MISSING"
        if not target.is_file() or entry is None:
            return "DIFFERENT"
        return "SAME" if sha256_bytes(target.read_bytes()) == entry["sha256"] else "DIFFERENT"
