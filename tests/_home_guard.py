"""The real-home guard of the suite: no test creates or changes anything directly in the real home.

`install()` (idempotent; every shared support module and the home-boundary tests import this module) does three things:
1. snapshots the real home (its top-level entries and, for `.batuta`, the whole tree) before the first test;
2. points `HOME`, `USERPROFILE` and `Path.home` at one temporary home for the whole run, so a default that resolves under
   the home (`~/.batuta/temp`) lands there and never in the real home;
3. wraps `unittest.TestCase.run`: after every test, a change of the real home or an entry left in the temporary home
   fails that test by name (the offender is the test that relied on a home default), and the temporary home is emptied.

A test that needs a home of its own patches `HOME`/`USERPROFILE` itself; the guard compares against the temporary home
that is current when the test starts.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_STATE: dict = {}
# The Claude Code CLI keeps its own state in the home (`.claude/`, `.claude.json`, their lock and temporary files) and
# rewrites it while a suite runs inside a session; it is not a test's write, so it is not compared.
IGNORED_PREFIXES = (".claude",)


def real_home() -> Path:
    """The real home, as the process saw it before the guard (USERPROFILE on Windows, HOME elsewhere)."""
    if "real" in _STATE:
        return _STATE["real"]
    return Path(os.path.expanduser("~"))


def snapshot(home) -> dict:
    """{relative path: (size, mtime_ns)} of the top-level entries of `home` and of everything below `.batuta`."""
    home = Path(home)
    out = {}
    try:
        entries = list(os.scandir(home))
    except OSError:
        return out
    for entry in entries:
        if entry.name.startswith(IGNORED_PREFIXES):
            continue
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        out[entry.name] = (st.st_size, st.st_mtime_ns) if not entry.is_dir(follow_symlinks=False) else (-1, 0)
    batuta = home / ".batuta"
    if batuta.is_dir():
        for sub in batuta.rglob("*"):
            try:
                st = sub.stat()
            except OSError:
                continue
            out[sub.relative_to(home).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


def changed(before: dict, after: dict) -> list:
    names = sorted(set(before) | set(after))
    return [n for n in names if before.get(n) != after.get(n)]


def _entries(folder) -> list:
    try:
        return sorted(p.name for p in Path(folder).iterdir())
    except OSError:
        return []


def _empty(folder) -> None:
    for p in Path(folder).iterdir():
        try:
            shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
        except OSError:
            pass


def install() -> Path:
    """Enable the guard (once per process); returns the temporary home."""
    if "temp" in _STATE:
        return _STATE["temp"]
    real = real_home()
    temp = Path(tempfile.mkdtemp(prefix="batuta-testhome-")).resolve()
    _STATE.update(real=real, temp=temp, snap=snapshot(real))
    os.environ["USERPROFILE"] = str(temp)
    os.environ["HOME"] = str(temp)
    Path.home = classmethod(lambda cls: Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(temp)))
    original = unittest.TestCase.run

    def run(self, result=None):
        home_before = Path(os.environ.get("USERPROFILE") or temp)
        listed = _entries(home_before) if home_before == temp else None
        real_before = snapshot(real)
        outcome = original(self, result)
        problems = []
        moved = changed(real_before, snapshot(real))
        if moved:
            problems.append(f"the real home changed: {', '.join(moved[:8])}")
        if listed is not None and home_before == temp and _entries(temp) != listed:
            problems.append(f"the test wrote into the home default: {', '.join(_entries(temp))}")
            _empty(temp)
        if problems and result is not None:
            result.addFailure(self, (AssertionError, AssertionError("home guard: " + "; ".join(problems)), None))
        return outcome

    unittest.TestCase.run = run
    atexit.register(shutil.rmtree, str(temp), True)
    return temp


def final_check() -> list:
    """The real-home entries that differ from the snapshot taken at install time (empty when the guard is not on)."""
    if "snap" not in _STATE:
        return []
    return changed(_STATE["snap"], snapshot(_STATE["real"]))


install()
