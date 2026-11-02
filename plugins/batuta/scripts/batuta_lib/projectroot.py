"""The one upward search for a project root, with the home boundary.

A project root is never the user's home directory nor any ancestor of it, so a search that starts below the home stops
before reaching it: a folder `~/.batuta` (the default Batuta home, whatever `BATUTA_HOME` says), a `.git` or a `specs`
folder of the home itself can never be taken for a project marker. The home is whatever `Path.home()`, `USERPROFILE`
and `HOME` name (each one is a boundary). A start at the home or above it yields nothing, and the caller falls back to
its documented default (the working directory).

Every module that looks for a project root above a folder uses `ascend` or `find`; none keeps a loop over `.parents`.
"""
from __future__ import annotations

import os
from pathlib import Path


def _resolved(path):
    path = Path(path)
    try:
        return path.resolve()
    except OSError:
        return Path(os.path.abspath(path))


def homes() -> list:
    """The resolved home folders the process names: `Path.home()`, `USERPROFILE` and `HOME` (those that are set)."""
    found = []
    candidates = []
    try:
        candidates.append(Path.home())
    except (RuntimeError, KeyError, OSError):
        pass
    candidates += [Path(v) for v in (os.environ.get("USERPROFILE"), os.environ.get("HOME")) if v]
    for candidate in candidates:
        folder = _resolved(candidate)
        if folder not in found:
            found.append(folder)
    return found


def _key(path):
    return tuple(os.path.normcase(part) for part in Path(path).parts)


def _is_boundary(folder, boundaries) -> bool:
    """True for a home or an ancestor of a home."""
    mine = _key(folder)
    return any(_key(home)[:len(mine)] == mine for home in boundaries)


def ascend(start):
    """The resolved folders from `start` upward, stopping before the first home or ancestor of a home."""
    boundaries = homes()
    base = _resolved(start)
    for folder in (base, *base.parents):
        if _is_boundary(folder, boundaries):
            return
        yield folder


def find(start, accept, limit=None):
    """The nearest folder at or above `start` (below the home boundary) for which `accept(folder)` is true, else None.
    `limit` caps how many folders are looked at (None: no cap)."""
    for count, folder in enumerate(ascend(start)):
        if limit is not None and count >= limit:
            return None
        try:
            if accept(folder):
                return folder
        except OSError:
            continue
    return None
