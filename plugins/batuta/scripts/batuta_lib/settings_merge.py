"""Append-only merge of settings presets (C17) into a Claude Code `settings.json`, verified after the write.

A running Claude session rewrites `settings.json` whenever a permission is accepted and can undo a write (field
evidence: the hooks block dropped two minutes after a restore; anthropics/claude-code issue 82167 reports the file
reset to `{}` with many parallel sessions). So `write_verified` writes, re-reads the file as it is now, and merges
again only what is missing into that fresh copy (never into an earlier in-memory copy, so the other session's new
entries survive), at most 3 attempts 0.5 s apart; what is still missing after the last attempt is an error naming the
items and the cause.

Merge rules (never remove, replace or reorder what the user has):
- `env`: a missing key is added; an existing key with another value is kept and reported (WARN), not overwritten.
- `permissions.deny` / `permissions.ask`: missing entries are appended in preset order.
- `hooks`: a preset hook whose identity is not present for its event is appended in a new group at the end. Identity
  of a Batuta launcher hook is its handler id (and the launcher file must exist); any other hook is its command and args.
A value of the wrong type (`permissions.deny` not a list, ...) refuses the whole merge and touches nothing.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import tempfile
import time
from pathlib import Path

from batuta_lib import config, contract, render

ATTEMPTS = 3
DELAY = 0.5
LAUNCHER = "/scripts/hook.py"
_SHELL_FORM = re.compile(r'"([^"]*' + re.escape(LAUNCHER) + r')" +([a-z][a-z0-9-]*)\s*$')


class SettingsError(Exception):
    """settings.json (or a preset) cannot be merged; nothing was written."""


class VerifyError(SettingsError):
    """Items still missing after the last attempt; `gaps` lists them."""

    def __init__(self, message, gaps):
        super().__init__(message)
        self.gaps = gaps


def load_preset(path):
    """The preset at `path`, validated as C17 (SettingsError otherwise)."""
    try:
        doc = contract.loads_strict(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise SettingsError(f"cannot read the preset {Path(path).as_posix()}: {exc}") from exc
    sp = contract.find_schema(config.contracts_dir(), "C17")
    problems = contract.validate_instance("C17", doc, contract.load_schema(sp))
    if problems:
        raise SettingsError(f"{Path(path).as_posix()} does not satisfy C17: " + "; ".join(problems))
    return doc


def _render_tree(node, values):
    if isinstance(node, str):
        return render.render(node, values) if "{{" in node else node
    if isinstance(node, list):
        return [_render_tree(x, values) for x in node]
    if isinstance(node, dict):
        return {k: _render_tree(v, values) for k, v in node.items()}
    return node


def render_preset(preset, values):
    """The preset with its `{{name}}` placeholders filled (render.RenderError when a value is missing)."""
    return _render_tree(copy.deepcopy(preset), values)


def combine(presets):
    """One preset from several: env merged (a key given twice with two values is an error), lists unioned in order,
    hook groups concatenated."""
    out = {"env": {}, "permissions": {"deny": [], "ask": []}, "hooks": {}}
    for p in presets:
        for k, v in p.get("env", {}).items():
            if k in out["env"] and out["env"][k] != v:
                raise SettingsError(f"two presets set env.{k} to different values")
            out["env"][k] = v
        for lst in ("deny", "ask"):
            for entry in p.get("permissions", {}).get(lst, []):
                if entry not in out["permissions"][lst]:
                    out["permissions"][lst].append(entry)
        for event, groups in p.get("hooks", {}).items():
            out["hooks"].setdefault(event, []).extend(copy.deepcopy(groups))
    return out


def parse(raw, path="settings.json"):
    """The settings object of `raw` bytes (a BOM is tolerated); None when `raw` is None (no file)."""
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError as exc:
        raise SettingsError(f"{Path(path).as_posix()} is not valid JSON ({exc}); not touched") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{Path(path).as_posix()} is not a JSON object; not touched")
    return data


def check_shapes(settings, preset, path="settings.json"):
    """SettingsError when a key the merge must extend holds a value of the wrong type (it would be replaced)."""
    if settings is None:
        return
    where = Path(path).as_posix()
    for key in ("env", "permissions", "hooks"):
        if key in settings and not isinstance(settings[key], dict):
            raise SettingsError(f"{where}: '{key}' is not an object; not touched")
    perms = settings.get("permissions") or {}
    for lst in ("deny", "ask"):
        if lst in perms and not isinstance(perms[lst], list):
            raise SettingsError(f"{where}: permissions.{lst} is not a list; not touched")
    hooks = settings.get("hooks") or {}
    for event in preset.get("hooks", {}):
        if event in hooks and not isinstance(hooks[event], list):
            raise SettingsError(f"{where}: hooks.{event} is not a list; not touched")


def _hook_key(hook):
    """Identity of a hook entry: ('launcher', id, launcher path) for a Batuta launcher hook, else ('command', ...)."""
    command, args = str(hook.get("command", "")), hook.get("args")
    if isinstance(args, list):
        strs = [str(a) for a in args]
        for i, a in enumerate(strs[:-1]):
            if a.endswith(LAUNCHER):
                return ("launcher", strs[i + 1], a)
        return ("command", command, tuple(strs))
    m = _SHELL_FORM.search(command)
    if m:
        return ("launcher", m.group(2), m.group(1))
    return ("command", command, ())


def _present(key, existing):
    """True when an existing hook has the identity `key` (a launcher hook also needs its launcher file to exist)."""
    for group in existing if isinstance(existing, list) else []:
        for hook in group.get("hooks", []) if isinstance(group, dict) and isinstance(group.get("hooks"), list) else []:
            if not isinstance(hook, dict):
                continue
            k = _hook_key(hook)
            if key[0] == "launcher":
                if k[0] == "launcher" and k[1] == key[1] and Path(k[2]).is_file():
                    return True
            elif k == key:
                return True
    return False


def _hook_label(event, key):
    return f"hooks.{event} {key[1]}" if key[0] == "launcher" else f"hooks.{event} {key[1]}"


def plan(settings, preset):
    """The merge as a list of (tag, label): NEW (missing, will be added), SAME (present), WARN (kept, differs)."""
    settings = settings or {}
    rows = []
    env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    for k, v in preset.get("env", {}).items():
        if k not in env:
            rows.append(("NEW", f"env.{k} = {v}"))
        elif env[k] == v:
            rows.append(("SAME", f"env.{k}"))
        else:
            rows.append(("WARN", f"env.{k} is {env[k]!r}, the preset wants {v!r}; kept (never overwritten)"))
    perms = settings.get("permissions") if isinstance(settings.get("permissions"), dict) else {}
    for lst in ("deny", "ask"):
        have = perms.get(lst) if isinstance(perms.get(lst), list) else []
        for entry in preset.get("permissions", {}).get(lst, []):
            rows.append(("SAME" if entry in have else "NEW", f'permissions.{lst} "{entry}"'))
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    for event, groups in preset.get("hooks", {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                key = _hook_key(h)
                rows.append(("SAME" if _present(key, hooks.get(event)) else "NEW", _hook_label(event, key)))
    return rows


def gaps(settings, preset):
    """Labels of what the preset needs and the settings lack (a differing env value is not a gap)."""
    return [label for tag, label in plan(settings, preset) if tag == "NEW"]


def merge(settings, preset):
    """A copy of `settings` plus what is missing of `preset`; the argument is not changed."""
    data = copy.deepcopy(settings) if settings else {}
    env = data.get("env") if isinstance(data.get("env"), dict) else None
    for k, v in preset.get("env", {}).items():
        if env is None:
            env = data["env"] = {}
        env.setdefault(k, v)
    for lst in ("deny", "ask"):
        entries = preset.get("permissions", {}).get(lst, [])
        have = (data.get("permissions") or {}).get(lst) or []
        missing = [e for e in entries if e not in have]
        if missing:
            perms = data.setdefault("permissions", {})
            perms[lst] = list(have) + missing
    for event, groups in preset.get("hooks", {}).items():
        existing = (data.get("hooks") or {}).get(event) or []
        for g in groups:
            missing = [copy.deepcopy(h) for h in g.get("hooks", []) if not _present(_hook_key(h), existing)]
            if missing:
                new = {k: v for k, v in g.items() if k != "hooks"}
                new["hooks"] = missing
                existing = list(existing) + [new]
                data.setdefault("hooks", {})[event] = existing
    return data


def _read(path):
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return None


def _dump(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


class _Changed(Exception):
    pass


def _write_atomic(path, data, expected, read):
    """Write through a temp file in the same folder and os.replace, unless the file changed since it was read."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_dump(data))
        if read(path) != expected:
            raise _Changed()
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def stamp():
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _backup(path, make_stamp):
    base = Path(path)
    target = base.with_name(f"{base.name}.bak-{make_stamp()}")
    n = 1
    while target.exists():
        n += 1
        target = base.with_name(f"{base.name}.bak-{make_stamp()}-{n}")
    target.write_bytes(base.read_bytes())
    return target


def write_verified(path, preset, read=_read, sleep=time.sleep, make_stamp=stamp, attempts=ATTEMPTS, delay=DELAY,
                   notes=None):
    """Merge `preset` into the settings file at `path`, then re-read and repeat until nothing is missing.

    Returns {"attempts": n, "backup": path or None, "wrote": bool}; nothing is written (and no backup made) when
    nothing is missing. `read(path) -> bytes or None` and `sleep(seconds)` are injectable for tests. Raises
    SettingsError for an unusable file and VerifyError after the last attempt."""
    path = Path(path)
    backup, wrote, left = None, False, []
    for attempt in range(1, attempts + 1):
        raw = read(path)
        current = parse(raw, path)
        check_shapes(current, preset, path)
        if not gaps(current, preset):
            return {"attempts": attempt - 1 if wrote else 0, "backup": backup, "wrote": wrote}
        if attempt > 1:
            if notes is not None:
                notes.append(f"settings.json was rewritten meanwhile (missing: {', '.join(left)}); merging again, "
                             f"attempt {attempt} of {attempts}")
            sleep(delay)
            raw = read(path)
            current = parse(raw, path)
            check_shapes(current, preset, path)
        if backup is None and raw is not None:
            backup = _backup(path, make_stamp)
        try:
            _write_atomic(path, merge(current, preset), raw, read)
            wrote = True
        except _Changed:
            left = ["a write that lost a race with another session"]
            continue
        after = parse(read(path), path)
        left = gaps(after, preset)
        if not left:
            return {"attempts": attempt, "backup": backup, "wrote": True}
    raise VerifyError(f"{path.as_posix()} still lacks {', '.join(left)} after {attempts} attempts: another Claude "
                      f"session keeps rewriting settings.json; close other sessions or re-run restore --apply", left)
