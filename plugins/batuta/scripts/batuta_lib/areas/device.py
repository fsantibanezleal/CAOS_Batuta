"""Area `device`: install, verify, restore and back up the Batuta setup on this device.

Verbs:
    deploy   copy the plugin's scripts, contracts and templates into the device copy and write its profile (C15)
    restore  merge the settings presets append-only into `~/.claude/settings.json` (verified after the write), render
             the user core from its template, install the path-scoped rule stubs with working links
    check    read-only, under two seconds: device copy, presets in settings, agents, user core; `--hook` prints the
             SessionStart object (C16) and always exits 0
    backup   collect the device's learned state into a bundle folder, refusing on any secret pattern

The device copy lives in `<deploy root>/` (`--deploy-root`, else `BATUTA_HOME`, else `~/.batuta`) and mirrors the
plugin layout: `scripts/`, `contracts/`, `.claude-plugin/plugin.json`, `templates/` and `reference/` (the on-demand files
of the user core). No shipped file holds a machine path: the device values live in `<deploy root>/device.json`.

The user core is configured in `batuta.json` (an extra key C01 allows):
    "user_core": {"template": "templates/user/CLAUDE.template.md", "values": {"user_name": "...", ...}}
A relative template path resolves from the deploy root; the device values (`python`, `deploy_root`, `temp_root`,
`data_root`, `models_root`, `worktrees_root`) fill the placeholders and win over `values`.

Every write is a dry run unless `--apply`. Exit codes: 0 ok, 1 failure or refusal, 2 warnings.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

from batuta_lib import config, contract, render
from batuta_lib import device_profile as dp
from batuta_lib import settings_merge as sm
from batuta_lib.areas import version as version_area
from batuta_lib.areas.context import STUB_MARK
from batuta_lib.output import emit, item

AREA = "device"
HELP = "Device: deploy the device copy, restore settings with verification, check at session start, back up learned state."

PLUGIN_ROOT = Path(__file__).resolve().parents[3]          # plugins/batuta, or the device copy itself
MIRRORED = ("scripts", "contracts", "templates", "reference", ".claude-plugin")
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
BACKUP_COPY = re.compile(r"\.bak-\d{8}-\d{6}(?:-\d+)?$")
SETTINGS_KEYS = ("env", "model", "modelSettings", "hooks", "autoUpdatesChannel")   # the agentic part of settings.json
LAUNCHER_SUFFIX = "/scripts/hook.py"
HOOK_CAP = 10000

# injectable by tests: the drive probe, the settings re-read and the wait between two verified-write attempts
_drive_exists = os.path.exists
_settings_read = sm._read
_settings_sleep = time.sleep

SECRET_PATTERNS = [
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{50,}")),
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("Slack token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("GitLab token", re.compile(r"glpat-[A-Za-z0-9_-]{20,}")),
    ("npm token", re.compile(r"npm_[A-Za-z0-9]{36}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")),
    ("git access token in URL", re.compile(r"x-access-token:(?![${%<])[^@\s]+@")),
    ("credentials in URL", re.compile(r"https?://[^/\s:@]+:(?![${%<])[^@\s/]{16,}@")),
    ("bearer token", re.compile(r"(?i:bearer) (?![${%<])[A-Za-z0-9._-]{20,}")),
    ("secret-named value", re.compile(r'(?i)"[A-Za-z0-9_]*(?:token|secret|key|password)[A-Za-z0-9_]*"\s*:\s*'
                                      r'"(?![${%<])[^"\s]{16,}"')),
]


# ------------------------------------------------------------------ small helpers


def _flag_json(args):
    return bool(getattr(args, "json", False))


def _home(args):
    return Path(args.home) if getattr(args, "home", None) else Path.home()


def _write_bytes(path, data):
    """Atomic binary write through the shared writer: a temp file in the same folder, then `os.replace`, retried on a
    transient access error."""
    render.write_atomic_bytes(path, data)
    return Path(path)


def _tree(folder):
    """{posix relative path: bytes} of every file under `folder`, without caches and `.bak-<stamp>` copies."""
    out = {}
    folder = Path(folder)
    if not folder.is_dir():
        return out
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder)
        if p.is_file() and not (set(rel.parts) & SKIP_DIRS) and p.suffix != ".pyc" and not BACKUP_COPY.search(p.name):
            out[rel.as_posix()] = p.read_bytes()
    return out


def _templates_dirs():
    """The template folders a deploy mirrors: the plugin's own `templates/` (presets, user core, knowledge, the project
    template and the areas' templates) in a checkout, in a marketplace copy and in a device copy alike. A folder above
    the plugin is never read, so a copy of `plugins/<name>/` alone deploys everything."""
    return [PLUGIN_ROOT / "templates"] if (PLUGIN_ROOT / "templates").is_dir() else []


def _load_config(args, items):
    try:
        return config.load(getattr(args, "config", None))
    except config.ConfigError as exc:
        items.append(item("FAIL", str(exc)))
        return None


def _is_link(path):
    """True for a symlink and, on Windows, for any reparse point (a junction is one, and `islink` does not see it)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0)
                                            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _managed_walk(base, area):
    """(files, links) under `base/area` as posix paths relative to `base`: the files a mirror may remove and the links
    found. A link or junction is reported and never descended into, so nothing behind it is listed or deleted."""
    base, files, links = Path(base), [], []
    root = base / area
    if _is_link(root):
        return files, [area]
    if not root.is_dir():
        return files, links
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in list(dirnames):
            path = Path(dirpath) / name
            if _is_link(path):
                links.append(path.relative_to(base).as_posix())
                dirnames.remove(name)
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(base)
            if _is_link(path):
                links.append(rel.as_posix())
            elif not (set(rel.parts[1:]) & SKIP_DIRS) and path.suffix != ".pyc" and not BACKUP_COPY.search(name):
                files.append(rel.as_posix())
    return files, links


def _link_ancestors(base, rels):
    """The first link or junction met while walking each relative path down from `base` (a managed file or folder
    that is a link), as posix paths."""
    base, found = Path(base), []
    for rel in rels:
        current = base
        for part in rel.split("/"):
            current = current / part
            if not os.path.lexists(current):
                break
            if _is_link(current):
                found.append(current.relative_to(base).as_posix())
                break
    return found


def _refuse_escape(base, rels, items):
    """True (with a REFUSED item) when a relative path resolves outside `base` once links, junctions and symlinks are
    resolved: a write or a removal there would leave the folder the caller owns."""
    base = Path(base)
    root = Path(os.path.realpath(base))
    for rel in rels:
        if not dp._inside(Path(os.path.realpath(base / rel)), root):
            items.append(item("REFUSED", f"{rel} resolves outside {base.as_posix()} (a link or junction inside it); "
                                         f"nothing written or removed"))
            return True
    return False


def _precheck(base, desired, areas, items):
    """The files a mirror may remove, {area: files}, or None (REFUSED items, nothing touched) when a managed path or
    area resolves outside `base`, or a link or junction sits where a managed file or folder belongs or below an area."""
    base = Path(base)
    if _refuse_escape(base, [*desired, *areas], items):
        return None
    walked = {area: _managed_walk(base, area) for area in areas}
    links = sorted(set(_link_ancestors(base, desired)) | {link for _, ls in walked.values() for link in ls})
    for link in links:
        items.append(item("REFUSED", f"{link} is a link or junction where a managed file or folder belongs; it is never "
                                     f"followed or deleted through; remove the link yourself, then run again"))
    if links:
        return None
    stale = [full for files, _ in walked.values() for full in files if full not in desired]
    if _refuse_escape(base, stale, items):
        return None
    return {area: files for area, (files, _) in walked.items()}


def _sync(base, desired, areas, apply, items):
    """Mirror `desired` into `base`; files outside `areas` are never removed. Returns (new, changed, removed, same), or
    None (REFUSED items, nothing written or removed) when `_precheck` finds a path that leaves `base` or a link."""
    base = Path(base)
    walked = _precheck(base, desired, areas, items)
    if walked is None:
        return None
    new, changed, removed, same = {}, 0, 0, 0
    for rel, data in sorted(desired.items()):
        target = base / rel
        if not target.exists():
            new.setdefault(rel.split("/")[0], []).append(rel)
        elif target.read_bytes() != data:
            changed += 1
            items.append(item("CHANGED", rel))
        else:
            same += 1
            continue
        if apply:
            _write_bytes(target, data)
    for area, files in new.items():
        items.append(item("NEW", f"{area}: {len(files)} file(s)" if len(files) > 1 or "/" in files[0] else files[0]))
    root = Path(os.path.realpath(base))
    for area in areas:
        for full in sorted(f for f in walked[area] if f not in desired):
            removed += 1
            items.append(item("REMOVED", full))
            if apply:
                path = base / full
                # last guard, right before the removal: still a plain file that lies inside the folder
                if _is_link(path) or not dp._inside(Path(os.path.realpath(path)), root):
                    items.append(item("REFUSED", f"{full} became a link or left {base.as_posix()}; not removed"))
                    return None
                path.unlink()
        if apply and (base / area).is_dir() and not _is_link(base / area):
            for dirpath, _, _ in os.walk(base / area, topdown=False, followlinks=False):
                folder = Path(dirpath)
                if folder != base / area and not _is_link(folder) and not any(folder.iterdir()):
                    folder.rmdir()
    return sum(len(v) for v in new.values()), changed, removed, same


def _mode(apply):
    return "applied" if apply else "dry run, nothing written (use --apply)"


# ------------------------------------------------------------------ deploy


def _source_tree():
    """What a deploy copies: {relative path: bytes}. Raises FileNotFoundError when the plugin has no scripts."""
    desired = {}
    for area in ("scripts", "contracts"):
        for rel, data in _tree(PLUGIN_ROOT / area).items():
            if area == "contracts" and rel.startswith("fixtures/"):
                continue   # test data of the contracts, never read at run time
            desired[f"{area}/{rel}"] = data
    manifest = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    if manifest.is_file():
        desired[".claude-plugin/plugin.json"] = manifest.read_bytes()
    for templates in _templates_dirs():
        for rel, data in _tree(templates).items():
            desired[f"templates/{rel}"] = data
        for rel, data in _tree(templates / "user" / "reference").items():
            desired[f"reference/{rel}"] = data
    return desired


def _deploy(args):
    items, as_json, home = [], _flag_json(args), _home(args)

    def done(summary):
        return emit(AREA, "deploy", items, summary, as_json)

    cfg = _load_config(args, items)
    if cfg is None:
        return done("device deploy: failed")
    try:
        deploy = dp.validate_root(dp.deploy_root(args.deploy_root), "deploy root", home, _drive_exists)
        roots = dp.resolve_roots(cfg.config, None, home, _drive_exists)
    except dp.ProfileError as exc:
        items.append(item("FAIL", str(exc)))
        return done("device deploy: failed")
    source = Path(os.path.abspath(PLUGIN_ROOT))
    if deploy == source or dp._inside(deploy, source) or dp._inside(source, deploy):
        items.append(item("FAIL", f"deploy root {deploy.as_posix()} overlaps the folder this copy runs from"))
        return done("device deploy: failed")
    if not (deploy / dp.PROFILE_FILE).is_file() and any((deploy / a).exists() for a in MIRRORED):
        items.append(item("REFUSED", f"{deploy.as_posix()} holds {', '.join(a for a in MIRRORED if (deploy / a).exists())} "
                                     f"but no {dp.PROFILE_FILE} from an earlier deploy; refusing to mirror into it"))
        return done("device deploy: refused, nothing written")
    desired = _source_tree()
    if "scripts/batuta.py" not in desired:
        items.append(item("FAIL", f"no scripts/batuta.py under {source.as_posix()}; nothing to deploy"))
        return done("device deploy: failed")
    try:
        profile = dp.build_profile(deploy, roots, args.python or sys.executable, version_area.read_version(),
                                   deployed_from=source)
    except (dp.ProfileError, RuntimeError) as exc:
        items.append(item("FAIL", str(exc)))
        return done("device deploy: failed")
    if _precheck(deploy, {**desired, dp.PROFILE_FILE: b""}, MIRRORED, items) is None:
        return done("device deploy: refused, nothing written")
    profile_bytes = dp.profile_text(profile).encode("utf-8")
    # the profile goes first so an interrupted deploy is recognised and can be repeated
    target = deploy / dp.PROFILE_FILE
    if not target.exists():
        items.append(item("NEW", dp.PROFILE_FILE))
    elif target.read_bytes() != profile_bytes:
        items.append(item("CHANGED", dp.PROFILE_FILE))
    if args.apply and (not target.exists() or target.read_bytes() != profile_bytes):
        _write_bytes(target, profile_bytes)
    counts = _sync(deploy, desired, MIRRORED, args.apply, items)
    if counts is None:
        return done("device deploy: refused, nothing written")
    n_new, n_changed, n_removed, same = counts
    return done(f"device deploy: {n_new} new, {n_changed} changed, {n_removed} removed, {same} unchanged files "
                f"in {deploy.as_posix()} ({_mode(args.apply)})")


# ------------------------------------------------------------------ presets, user core, stubs


def _launcher_problem(preset):
    """The first launcher file a rendered preset names that does not exist, else None."""
    for groups in preset.get("hooks", {}).values():
        for g in groups:
            for h in g.get("hooks", []):
                for arg in h.get("args", []) if isinstance(h.get("args"), list) else []:
                    if str(arg).endswith(LAUNCHER_SUFFIX) and not Path(arg).is_file():
                        return arg
    return None


def _presets(cfg, profile, deploy, items):
    """The combined, rendered presets of the device copy; problems go to `items`. Returns None on a refusal."""
    values = {**dp.render_values(profile), "spawn_depth": str(cfg["caps"]["spawn_depth"]),
              "max_concurrent_agents": str(cfg["caps"]["max_concurrent_agents"])}
    folder = Path(deploy) / "templates" / "presets"
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    if not files:
        items.append(item("FAIL", f"no presets in {folder.as_posix()}; run `device deploy --apply`"))
        return None
    rendered = []
    for f in files:
        try:
            preset = sm.render_preset(sm.load_preset(f), values)
        except (sm.SettingsError, render.RenderError) as exc:
            items.append(item("FAIL", f"preset {f.name}: {exc}"))
            return None
        missing = _launcher_problem(preset)
        if missing:
            items.append(item("WARN", f"preset {f.name} skipped: the launcher {missing} does not exist in the device copy "
                                      f"(it ships with the hooks unit); `device check --hook` is its CLI twin"))
            continue
        rendered.append(preset)
    try:
        return sm.combine(rendered)
    except sm.SettingsError as exc:
        items.append(item("FAIL", str(exc)))
        return None


def _user_core(cfg, profile, deploy, items):
    """The rendered user core text, or None (WARN when not configured, REFUSED when it cannot be rendered)."""
    uc = cfg.get("user_core")
    if not isinstance(uc, dict) or not uc.get("template"):
        items.append(item("WARN", "user core skipped: set user_core.template (and user_core.values) in batuta.json"))
        return None
    # the shape the frozen C01 `user_core` allows, enforced here too so a configuration that was not validated cannot
    # render an arbitrary file into the user's always-loaded core
    raw = uc["template"]
    parts = re.split(r"[\\/]", raw) if isinstance(raw, str) else []
    if (not isinstance(raw, str) or Path(raw).is_absolute() or re.match(r"^([A-Za-z]:|[\\/])", raw)
            or ".." in parts or "." in parts):
        items.append(item("REFUSED", "user_core.template must be a relative path inside the device copy (no drive, no "
                                     "leading slash, no '.' or '..' segment)"))
        return None
    values = uc.get("values", {})
    if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
        items.append(item("REFUSED", "user_core.values must be an object of text values"))
        return None
    template = Path(deploy) / raw
    if not dp._inside(Path(os.path.realpath(template)), Path(os.path.realpath(deploy))):
        items.append(item("REFUSED", "user_core.template resolves outside the device copy (a link inside it)"))
        return None
    values = {**values, **dp.render_values(profile)}
    try:
        return render.render_file(template, values)
    except (OSError, render.RenderError) as exc:
        items.append(item("REFUSED", f"user core not rendered from {template.as_posix()}: {exc}"))
        return None


_STUB_LINK_LINE = re.compile(r"^(Full text:|Also read:)", re.M)
_BACKTICK_MD = re.compile(r"`([^`\n]+\.md)`")


def rewrite_stub_links(text, source_dir, dest_dir):
    """The stub `text` (rendered next to `source_dir`) with every link to a knowledge unit rewritten so it resolves
    from `dest_dir`. Returns (text, problems); a link that does not resolve from the source is a problem and stays."""
    problems = []

    def fix(match):
        token = match.group(1)
        target = Path(os.path.normpath(Path(source_dir) / token))
        if not target.is_file():
            problems.append(f"link {token} does not resolve from {Path(source_dir).as_posix()}")
            return match.group(0)
        try:
            new = Path(os.path.relpath(target, dest_dir)).as_posix()
        except ValueError:   # another drive: no relative path exists
            new = target.as_posix()
        return f"`{new}`"

    out = []
    for line in text.split("\n"):
        out.append(_BACKTICK_MD.sub(fix, line) if _STUB_LINK_LINE.match(line) else line)
    return "\n".join(out), problems


def _install_stubs(source, claude, apply, force, items):
    source = Path(source)
    if not source.is_dir():
        items.append(item("FAIL", f"--stubs {source.as_posix()} is not a folder (the rules/ folder of a `context build`)"))
        return
    dest_dir = claude / "rules"
    for stub in sorted(source.glob("*.md")):
        text = stub.read_text(encoding="utf-8-sig")
        if STUB_MARK not in text:
            items.append(item("WARN", f"{stub.name} skipped: not a generated stub (no generated-by marker)"))
            continue
        new, problems = rewrite_stub_links(text, source, dest_dir)
        if problems:
            items.extend(item("FAIL", f"{stub.name}: {p}") for p in problems)
            continue
        dest = dest_dir / stub.name
        status = render.status(dest, new)
        label = f"rules/{stub.name}"
        if status == "SAME":
            items.append(item("SAME", label))
            continue
        if status == "CHANGED" and STUB_MARK not in dest.read_text(encoding="utf-8", errors="replace"):
            if not force:
                items.append(item("DIFFERENT", f"{label} is not a generated stub; left alone (--force backs it up and replaces it)"))
                continue
            backup = dest.with_name(f"{dest.name}.bak-{sm.stamp()}")
            items.append(item("OK", f"backup of {label} at {backup.name}"))
            if apply:
                shutil.copy2(dest, backup)
        items.append(item(status, label))
        if apply:
            render.write_atomic(dest, new)


# ------------------------------------------------------------------ restore


def _load_device(args, items):
    """(configuration, deploy root, profile, home) or None after a FAIL item."""
    cfg = _load_config(args, items)
    if cfg is None:
        return None
    try:
        deploy = dp.validate_root(dp.deploy_root(args.deploy_root), "deploy root", _home(args), _drive_exists)
        profile = dp.read_profile(deploy)
    except dp.ProfileError as exc:
        items.append(item("FAIL", f"{exc}; run `device deploy --apply` first"))
        return None
    return cfg.config, deploy, profile, _home(args)


def _restore(args):
    items, as_json = [], _flag_json(args)

    def done(summary):
        return emit(AREA, "restore", items, summary, as_json)

    loaded = _load_device(args, items)
    if loaded is None:
        return done("device restore: failed")
    cfg, deploy, profile, home = loaded
    claude = home / ".claude"
    preset = _presets(cfg, profile, deploy, items)
    if preset is None:
        return done("device restore: failed")

    path = claude / "settings.json"
    settings_items = []
    try:
        current = sm.parse(_settings_read(path), path)
        sm.check_shapes(current, preset, path)
    except sm.SettingsError as exc:
        items.append(item("FAIL", str(exc)))
        return done("device restore: refused, nothing written")
    except OSError as exc:
        items.append(item("FAIL", f"{path.as_posix()} cannot be read ({type(exc).__name__}: {exc}); nothing written"))
        return done("device restore: failed, nothing written")
    rows = sm.plan(current, preset)
    settings_items = [item(tag, f"settings.json {label}") for tag, label in rows]
    if args.apply and any(tag == "NEW" for tag, _ in rows):
        notes = []
        try:
            result = sm.write_verified(path, preset, read=_settings_read, sleep=_settings_sleep, notes=notes)
        except (sm.SettingsError, OSError) as exc:
            items.extend(item("WARN", n) for n in notes)
            items.append(item("FAIL", str(exc) if isinstance(exc, sm.SettingsError) else
                              f"{path.as_posix()} could not be written ({type(exc).__name__}: {exc})"))
            settings_items = []
        else:
            items.extend(item("WARN", n) for n in notes)
            if result["backup"]:
                items.append(item("OK", f"backup of settings.json at {Path(result['backup']).name}"))
    items.extend(settings_items)

    text = _user_core(cfg, profile, deploy, items)
    if text is not None:
        dest = claude / "CLAUDE.md"
        status = render.status(dest, text)
        if status == "CHANGED":
            backup = dest.with_name(f"{dest.name}.bak-{sm.stamp()}")
            items.append(item("OK", f"backup of CLAUDE.md at {backup.name}"))
            if args.apply:
                shutil.copy2(dest, backup)
        items.append(item(status, "CLAUDE.md (user core, rendered for this device)"))
        if args.apply and status != "SAME":
            render.write_atomic(dest, text)

    if args.stubs:
        _install_stubs(args.stubs, claude, args.apply, args.force, items)
    return done(f"device restore: {_mode(args.apply)}")


# ------------------------------------------------------------------ check and the session-start hook


def _restore_fix(profile_python, deploy):
    return f'"{profile_python}" "{(Path(deploy) / "scripts" / "batuta.py").as_posix()}" device restore --apply' + _root_flag(deploy)


def _same_folder(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _deploy_source(deploy):
    """The folder a `device deploy` can run from to repair the copy at `deploy`: the plugin this code runs from when it
    is not the copy itself, else the source the copy was deployed from (`deployed_from` of its profile, read leniently
    because the profile may be what is broken). None when neither exists: a deploy never copies a copy into itself."""
    candidates = [PLUGIN_ROOT]
    try:
        doc = json.loads((Path(deploy) / dp.PROFILE_FILE).read_text(encoding="utf-8-sig"))
        if isinstance(doc, dict) and isinstance(doc.get("deployed_from"), str):
            candidates.append(Path(doc["deployed_from"]))
    except (OSError, ValueError):
        pass
    for folder in candidates:
        if (Path(folder) / "scripts" / "batuta.py").is_file() and not _same_folder(folder, deploy):
            return Path(folder)
    return None


def _deploy_fix(deploy):
    source = _deploy_source(deploy)
    if source is None:
        return ("reinstall the Batuta plugin from its plugin channel (the copy cannot repair itself), "
                "then run `device deploy --apply` from the reinstalled plugin" + _root_flag(deploy))
    return (f'"{Path(sys.executable).as_posix()}" "{(source / "scripts" / "batuta.py").as_posix()}" '
            f'device deploy --apply' + _root_flag(deploy))


def _root_flag(deploy):
    return "" if Path(deploy) == dp.deploy_root(None) else f' --deploy-root "{Path(deploy).as_posix()}"'


def _bad(message, fix=None):
    it = item("FAIL", message)
    if fix:
        it["fix"] = fix
    return it


def _check_items(home, deploy, config_arg=None, env=None):
    """The check as C20 items (FAIL, WARN, OK, SKIP); never writes, never runs a subprocess or the network."""
    items = []
    deploy, claude = Path(deploy), Path(home) / ".claude"
    try:
        profile = dp.read_profile(deploy)
    except dp.ProfileError as exc:
        return [_bad(f"device copy: {exc}", _deploy_fix(deploy))]
    missing = [rel for rel in ("scripts/batuta.py", "contracts") if not (deploy / rel).exists()]
    if missing:
        return [_bad(f"device copy at {deploy.as_posix()} lacks {', '.join(missing)}", _deploy_fix(deploy))]
    items.append(item("OK", f"device copy {deploy.as_posix()} (version {profile['batuta_version']})"))
    fix = _restore_fix(profile["python"], deploy)

    try:
        cfg = config.load(config_arg, env=env).config
    except config.ConfigError as exc:
        items.append(_bad(f"configuration: {exc}"))
        cfg = config.default_config(env)

    scratch = []
    preset = _presets(cfg, profile, deploy, scratch)
    items.extend(i for i in scratch if i["tag"] == "WARN")
    for i in scratch:
        if i["tag"] != "WARN":
            items.append(_bad(f"presets: {i['message']}", _deploy_fix(deploy)))
    if preset is not None:
        path = claude / "settings.json"
        try:
            current = sm.parse(sm._read(path), path)
            sm.check_shapes(current, preset, path)
        except sm.SettingsError as exc:
            items.append(_bad(f"settings: {exc}"))
        else:
            if current is None:
                items.append(_bad(f"settings: {path.as_posix()} does not exist", fix))
            else:
                missing_items = sm.gaps(current, preset)
                if missing_items:
                    items.append(_bad("settings.json lacks " + ", ".join(missing_items), fix))
                else:
                    items.append(item("OK", "settings.json holds every preset item"))
                items.extend(item("WARN", label) for tag, label in sm.plan(current, preset) if tag == "WARN")

    roles = sorted(cfg.get("roles", {}))
    absent = [r for r in roles if not (claude / "agents" / f"{r}.md").is_file() and not (deploy / "agents" / f"{r}.md").is_file()]
    if absent:
        items.append(_bad(f"agents not available: {', '.join(absent)} (not in {(claude / 'agents').as_posix()} "
                          f"or the device copy); install the plugin or add the agent files"))
    else:
        items.append(item("OK", f"agents available: {len(roles)} role(s)"))

    scratch = []
    text = _user_core(cfg, profile, deploy, scratch)
    if text is not None:
        dest = claude / "CLAUDE.md"
        status = render.status(dest, text)
        if status == "SAME":
            items.append(item("OK", "user core current"))
        else:
            word = "does not exist" if status == "NEW" else "differs from the rendering of its template"
            items.append(_bad(f"user core {dest.as_posix()} {word}", fix))
    else:
        items.extend(item("SKIP", "user core not checked: " + i["message"]) if i["tag"] == "WARN"
                     else _bad(f"user core: {i['message']}") for i in scratch)
    return items


def _hook_text(items):
    """OK, or INCOMPLETE with the exact fix. A WARN (a user value kept on purpose, a preset skipped because the
    launcher of the hooks unit is not installed) is a note: it is shown but never makes the line INCOMPLETE."""
    bad = [i for i in items if i["tag"] in ("FAIL", "REFUSED", "DIFFERENT", "MISSING")]
    notes = [i for i in items if i["tag"] == "WARN"]
    fixes = []
    for i in bad:
        if i.get("fix") and i["fix"] not in fixes:
            fixes.append(i["fix"])
    if bad:
        head = f"Batuta device check: INCOMPLETE ({len(bad)} of {len(items)} items)"
    else:
        head = f"Batuta device check: OK ({len(items)} items" + (f", {len(notes)} note(s))" if notes else ")")
    tail = ("\nFix: " + "; then ".join(fixes)) if fixes else ""
    room = HOOK_CAP - len(head) - len(tail) - 60
    shown = [(i["tag"], i["message"]) for i in bad] + [("NOTE", i["message"]) for i in notes]
    lines, used = [], 0
    for n, (tag, message) in enumerate(shown):
        line = f"\n- {tag} {message}"
        if used + len(line) > room:
            lines.append(f"\n- ... and {len(shown) - n} more")
            break
        lines.append(line)
        used += len(line)
    return (head + "".join(lines) + tail)[:HOOK_CAP]


def session_check(payload, home=None, deploy_root=None, env=None, config_arg=None):
    """The SessionStart check as a C31 handler result carrying the C16 SessionStart output; never raises."""
    try:
        deploy = Path(deploy_root) if deploy_root else dp.deploy_root(None, env)
        items = _check_items(home or Path.home(), deploy, config_arg, env)
    except Exception as exc:   # noqa: BLE001 (a check must never break the session start)
        items = [_bad(f"the device check failed internally: {exc}")]
    return {"contract_version": "1.0", "exit_code": 0,
            "output": {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": _hook_text(items)}}}


def handler(payload):
    """Hook handler `session-check` (C31): OK or INCOMPLETE with the exact fix command."""
    return session_check(payload)


HOOKS = {"session-check": handler}


def _check(args):
    items, as_json = [], _flag_json(args)
    cfg = _load_config(args, items)
    if args.hook:
        res = session_check({}, _home(args), args.deploy_root, config_arg=getattr(args, "config", None))
        print(json.dumps(res["output"]))
        return 0
    if cfg is None:
        return emit(AREA, "check", items, "device check: failed", as_json)
    try:
        deploy = dp.validate_root(dp.deploy_root(args.deploy_root), "deploy root", _home(args), _drive_exists)
    except dp.ProfileError as exc:
        items.append(item("FAIL", str(exc)))
        return emit(AREA, "check", items, "device check: failed", as_json)
    items = _check_items(_home(args), deploy, getattr(args, "config", None))
    failing = any(i["tag"] in ("FAIL", "REFUSED") for i in items)
    return emit(AREA, "check", items, "device check: " + ("incomplete" if failing else "complete"), as_json)


# ------------------------------------------------------------------ backup


def decode_views(data):
    """Every plausible text of a file for the secret scan: UTF-8, UTF-16 little endian, UTF-16 big endian (the
    BOM, when there is one, only adds a character), and an ASCII view of the raw bytes with the NUL bytes removed.
    A guess about the encoding is never trusted: a UTF-8 file with one NUL byte and a big-endian file without a BOM
    both hid every token from a scan that picked one decoding."""
    return [data.decode("utf-8", "replace"), data.decode("utf-16-le", "replace"), data.decode("utf-16-be", "replace"),
            bytes(b for b in data if b).decode("latin-1")]


def line_sha(line):
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _find_hits(text):
    """(line number, label, matched text, sha256 of the whole line) for every secret-pattern hit in `text`."""
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                hits.append((number, label, match.group(0), line_sha(line)))
    return hits


def find_secrets(text, allowed=None):
    """(line number, label) for every secret-pattern hit; `${VAR}` placeholders are not secrets. `allowed` holds the
    sha256 of whole lines (no line break) that were reviewed and are exempt."""
    return [(number, label) for number, label, _, sha in _find_hits(text) if not (allowed and sha in allowed)]


def _scan(data, allowed=None):
    """(line number, label, sha256 of the line) for every hit in any decoding of `data`. The same token found at the
    same line in several decodings is one hit: it carries the sha of the first decoding and is exempt when the sha of
    any decoding of that line is in `allowed` (a BOM or a raw-byte view changes the line text, not the token)."""
    groups = {}
    for text in decode_views(data):
        for number, label, token, sha in _find_hits(text):
            groups.setdefault((number, label, token), []).append(sha)
    return [(number, label, shas[0]) for (number, label, _), shas in groups.items()
            if not (allowed and any(sha in allowed for sha in shas))]


def scan_secrets(data, allowed=None):
    """(line number, label) for every secret-pattern hit in any decoding of `data` (bytes)."""
    return [(number, label) for number, label, _ in _scan(data, allowed)]


def _collect(home, cfg, items):
    """{bundle path: bytes} of the device's learned state; problems and skips go to `items`."""
    claude = home / ".claude"
    desired = {}
    for rel, data in _tree(claude / "agents").items():
        if "/" not in rel and rel.endswith(".md"):
            desired[f"agents/{rel}"] = data
    settings_path = claude / "settings.json"
    if settings_path.is_file():
        try:
            settings = sm.parse(settings_path.read_bytes(), settings_path)
        except sm.SettingsError as exc:
            items.append(item("FAIL", f"backup: {exc}"))
            settings = None
        if settings is not None:
            subset = {k: settings[k] for k in SETTINGS_KEYS if k in settings}
            desired["settings.agentic.json"] = (json.dumps(subset, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    user_cfg = config.home_dir() / config.FILE_NAME
    if user_cfg.is_file():
        desired["config/batuta.json"] = user_cfg.read_bytes()
    projects = claude / "projects"
    for memory in sorted(projects.glob("*/memory")) if projects.is_dir() else []:
        for rel, data in _tree(memory).items():
            desired[f"memory/{memory.parent.name}/{rel}"] = data
    for rel, data in _tree(claude / "rules").items():
        if rel.endswith(".md") and STUB_MARK not in data.decode("utf-8", "replace"):
            desired[f"rules/{rel}"] = data
    core = claude / "CLAUDE.md"
    uc = cfg.get("user_core")
    if isinstance(uc, dict) and uc.get("template"):
        if core.is_file():
            items.append(item("SKIP", "CLAUDE.md is rendered from its template (user_core.template); rebuilt, not backed up"))
    elif core.is_file():
        desired["user/CLAUDE.md"] = core.read_bytes()
    return desired


def _backup(args):
    items, as_json, home = [], _flag_json(args), _home(args)

    def done(summary):
        return emit(AREA, "backup", items, summary, as_json)

    cfg = _load_config(args, items)
    if cfg is None:
        return done("device backup: failed")
    desired = _collect(home, cfg.config, items)
    if any(i["tag"] == "FAIL" for i in items):
        return done("device backup: failed, nothing written")
    out = Path(args.out)
    if out.exists() and not out.is_dir():
        items.append(item("FAIL", f"{out.as_posix()} is not a folder"))
        return done("device backup: failed, nothing written")
    if out.is_dir() and any(out.iterdir()) and not (out / "MANIFEST.json").is_file():
        items.append(item("REFUSED", f"{out.as_posix()} is not empty and has no MANIFEST.json from an earlier backup; "
                                     f"refusing to mirror into a folder that is not a bundle"))
        return done("device backup: refused, nothing written")
    allowed = {str(s).lower() for s in args.allow or []}
    leaks = []
    for rel, data in sorted(desired.items()):
        name_hits = find_secrets(rel)
        shown = "<file name withheld>" if name_hits else rel
        for number, label, sha in _scan(data, allowed):
            leaks.append(item("REFUSED", f"{shown}:{number} matches a {label} pattern (reviewed and safe? pass "
                                         f"--allow {sha})"))
        for _, label in name_hits:             # a secret in a file name would reach the bundle path and MANIFEST.json
            leaks.append(item("REFUSED", f"a file name under {rel.split('/')[0]}/ matches a "
                                         f"{label} pattern; rename or remove that file (the name is not echoed)"))
    if leaks:
        items.extend(leaks)
        return done(f"device backup: refused, {len(leaks)} secret hit(s), nothing written")
    if not desired:
        items.append(item("WARN", f"nothing to back up under {(home / '.claude').as_posix()}"))
        return done("device backup: nothing collected")
    areas = ("agents", "memory", "rules", "user", "config")
    manifest = {"batuta_version": version_area.read_version(),
                "files": [{"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for rel, data in sorted(desired.items())]}
    full = dict(desired)
    full["MANIFEST.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    counts = _sync(out, full, areas, args.apply, items)
    if counts is None:
        return done("device backup: refused, nothing written")
    n_new, n_changed, n_removed, same = counts
    return done(f"device backup: {n_new} new, {n_changed} changed, {n_removed} removed, {same} unchanged files "
                f"in {out.as_posix()} ({_mode(args.apply)})")


# ------------------------------------------------------------------ registration


def register(subparsers):
    def common(p, apply=True):
        p.add_argument("--home", help="home folder holding .claude/ (default: the user's home)")
        p.add_argument("--deploy-root", help="the device copy's folder (default: BATUTA_HOME, else ~/.batuta)")
        if apply:
            p.add_argument("--apply", action="store_true", help="write (default: dry run)")

    p = subparsers.add_parser("deploy", help="copy the plugin into the device copy and write its profile (C15)")
    common(p)
    p.add_argument("--python", help="the interpreter to record in the profile (default: the running one)")
    p.set_defaults(func=_deploy)

    p = subparsers.add_parser("restore", help="merge the settings presets append-only (verified), render the user core")
    common(p)
    p.add_argument("--force", action="store_true", help="back up and replace a stub file that is not a generated stub")
    p.add_argument("--stubs", help="the rules/ folder of a `context build`: install its stubs with working links")
    p.set_defaults(func=_restore)

    p = subparsers.add_parser("check", help="read-only device check; --hook prints the SessionStart object")
    common(p, apply=False)
    p.add_argument("--hook", action="store_true", help="print the SessionStart JSON (OK or INCOMPLETE) and exit 0")
    p.set_defaults(func=_check)

    p = subparsers.add_parser("backup", help="collect the learned state into a bundle folder, refusing on a secret")
    common(p)
    p.add_argument("--out", required=True, help="the bundle folder")
    p.add_argument("--allow", action="append", help="sha256 of a reviewed line the secret scan exempts (repeatable)")
    p.set_defaults(func=_backup)
