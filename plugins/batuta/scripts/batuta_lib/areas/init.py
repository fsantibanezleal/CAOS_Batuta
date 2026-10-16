"""Area `init`: adopt Batuta in one command, check it, update it and take it away again.

Verbs:
    user       create `<BATUTA_HOME>/batuta.json` (C01) when missing, then deploy the device copy, restore the settings
               presets and the user core (the device area), and install the agent files into `~/.claude/agents/`
    project    render the project template (`templates/project/`) into `--target`: AGENTS.md, CLAUDE.md,
               `.claude/settings.json` (merged append-only), `.batuta/batuta.json`, the constitution and thresholds, an
               example feature and the `batuta-gates` workflow
    doctor     the device check plus probes (Python, Git Bash on Windows, Node, the `claude` CLI, the plugin's `python`
               option, configuration, roots, and in a project the workflow's test step against `tdd.test_command`)
    update     render again from the current templates what the install manifest lists, backing up what changes
    uninstall  restore the backups and remove the files whose hash is unchanged; an edited file is kept (DIFFERENT)

Every write is a dry run unless `--apply`; every write is atomic; a file init replaces is backed up next to it as
`<name>.bak-<stamp>` first; `.claude/settings.json` is never replaced, only merged append-only through the settings merge
of the device area. What init wrote (path, hash, backup, folders it created) is recorded in the install manifest
(`install_manifest.py`): `<deploy root>/installed.json` for the user install, `<project>/.batuta/installed.json` for a
project. Exit codes: 0 ok, 1 failure or refusal, 2 warnings (for example a file kept because it changed).

The project template variables are the same for `init project` and the copier channel (`copier.yml`): `project_name`,
`project_slug`, `python_version`, `test_command`, `default_branch`. Templates hold `{{ name }}` placeholders only.
"""
import argparse
import contextlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

from batuta_lib import config, contract, render
from batuta_lib import device_profile as dp
from batuta_lib import install_manifest as im
from batuta_lib import settings_merge as sm
from batuta_lib.areas import device
from batuta_lib.output import emit, item

AREA = "init"
HELP = "Adopt Batuta: init user and init project, then doctor, update and uninstall."

PLUGIN_ROOT = Path(__file__).resolve().parents[3]          # plugins/batuta, or the device copy itself
SCRIPT = PLUGIN_ROOT / "scripts" / "batuta.py"
VARIABLES = ("project_name", "project_slug", "python_version", "test_command", "default_branch")
DEFAULTS = {"python_version": "3.12", "test_command": "python -m unittest discover -s tests -t . -v",
            "default_branch": "main"}
USER_DEFAULTS = {"language": "English", "tone": "direct, no filler"}
USER_KEYS = ("user_name", "language", "tone")
USER_CORE_TEMPLATE = "templates/user/CLAUDE.template.md"
# the example feature of the template is what `spec new` creates for these values (a test keeps the two in step)
EXAMPLE_TITLE = "Example feature"
EXAMPLE_TIER = "M"
EXAMPLE_OWNER = "Project owner"
EXAMPLE_DATE = date(2026, 1, 1)
WORKFLOW = ".github/workflows/batuta-gates.yml"
SETTINGS = ".claude/settings.json"
MIN_PYTHON = (3, 10)
MIN_NODE = 18


class InitError(ValueError):
    """An input or a template cannot be used; the message says what to change."""


# ------------------------------------------------------------------ the template and its variables


def template_dir():
    """The project template: the device copy's `templates/project`, or the repository's own (a checkout or an npx copy)."""
    candidates = [PLUGIN_ROOT / "templates" / "project"]
    if PLUGIN_ROOT.parent.name == "plugins":
        candidates.append(PLUGIN_ROOT.parents[1] / "templates" / "project")
    for folder in candidates:
        if folder.is_dir():
            return folder
    raise InitError("the project template (templates/project) is not found next to this copy of Batuta; run init from a "
                    "checkout of the repository, from `npx github:fsantibanezleal/CAOS_Batuta`, or after `init user --apply`")


def read_template(folder):
    """{relative POSIX path: text} of every file of the template folder (no caches)."""
    out = {}
    folder = Path(folder)
    for p in sorted(folder.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            out[p.relative_to(folder).as_posix()] = p.read_text(encoding="utf-8")
    return out


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def check_variables(variables):
    """The five variables as text, or InitError naming every problem (they land in JSON, YAML and Markdown unescaped)."""
    unknown = sorted(set(variables) - set(VARIABLES))
    missing = [k for k in VARIABLES if k not in variables]
    problems = [f"unknown variable {k!r} (the variables are {', '.join(VARIABLES)})" for k in unknown]
    problems += [f"missing variable {k}" for k in missing]
    values = {k: str(v) for k, v in variables.items() if k in VARIABLES}
    rules = {
        "project_name": (r"[^\x00-\x1f\"\\{}]{1,100}", "1 to 100 characters without control characters, quotes, backslashes or braces"),
        "project_slug": (r"[a-z0-9]+(?:-[a-z0-9]+)*", "lower case letters, digits and single hyphens"),
        "python_version": (r"3\.(?:1[0-9]|[2-9][0-9])", "3.10 or newer, as in 3.12"),
        "test_command": (r"(?! )[^\x00-\x1f\"\\{}]{1,300}", "one line without double quotes, backslashes or braces (use single quotes "
                                                              "inside the command)"),
        "default_branch": (r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", "letters, digits, '.', '_', '-' and '/'"),
    }
    for key, (pattern, words) in rules.items():
        if key in values and not re.fullmatch(pattern, values[key]):
            problems.append(f"{key} {values[key]!r} must be {words}")
    if "default_branch" in values and (".." in values["default_branch"] or values["default_branch"].endswith(("/", ".lock"))):
        problems.append(f"default_branch {values['default_branch']!r} is not a valid branch name")
    if problems:
        raise InitError("; ".join(problems))
    return values


def render_project(variables, folder=None):
    """{relative path: rendered text} of the project template for `variables`. InitError on a bad variable."""
    values = check_variables(variables)
    out = {}
    for rel, text in read_template(folder or template_dir()).items():
        try:
            out[rel] = render.render(text, values)
        except render.RenderError as exc:
            raise InitError(f"template file {rel}: {exc}") from exc
    return out


def parse_vars(pairs, allowed):
    """{key: value} from `k=v` strings; InitError for a malformed or unknown one."""
    out = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise InitError(f"--var {pair!r} must be written key=value")
        if key not in allowed:
            raise InitError(f"--var {key}: unknown variable (the variables are {', '.join(allowed)})")
        out[key] = value
    return out


# ------------------------------------------------------------------ small file helpers


def _flag_json(args):
    return bool(getattr(args, "json", False))


def _sha(data):
    return im.sha256_bytes(data)


def _backup(path):
    """Copy `path` to `<name>.bak-<stamp>` next to it (byte for byte); returns the new path."""
    path = Path(path)
    stamp = sm.stamp()
    target = path.with_name(f"{path.name}.bak-{stamp}")
    n = 1
    while target.exists():
        n += 1
        target = path.with_name(f"{path.name}.bak-{stamp}-{n}")
    shutil.copy2(path, target)
    return target


def _write_bytes(path, data):
    """Atomic binary write (temp file in the same folder, then `os.replace`)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _is_link(path):
    try:
        return Path(path).is_symlink() or bool(os.lstat(path).st_file_attributes & 0x400)   # a Windows reparse point
    except (OSError, AttributeError):
        return Path(path).is_symlink()


def _blocked(base, rel):
    """Why init must not write `rel` under `base` (a folder or a link in the way, a path leaving the base), else None."""
    base = Path(base)
    target = base / rel
    cursor = base
    for part in Path(rel).parts[:-1]:
        cursor = cursor / part
        if cursor.exists() or _is_link(cursor):
            if _is_link(cursor):
                return f"{cursor.as_posix()} is a link; refusing to write through it"
            if not cursor.is_dir():
                return f"{cursor.as_posix()} is a file where a folder is needed"
    if target.exists() or _is_link(target):
        if _is_link(target):
            return f"{rel} is a link; refusing to replace it"
        if not target.is_file():
            return f"{rel} is a folder where a file is needed"
    real = Path(os.path.realpath(base))
    if not dp._inside(Path(os.path.realpath(target)), real):
        return f"{rel} resolves outside {base.as_posix()}"
    return None


def _anchor(path):
    """The nearest existing folder at or above `path`."""
    p = Path(os.path.abspath(path))
    while not p.exists() and p.parent != p:
        p = p.parent
    return p


def _new_dirs(anchor, files):
    """The folders (relative to `anchor`, parents first) that writing the absolute `files` would create."""
    anchor = Path(anchor)
    found = []
    for f in sorted(files):
        rel = Path(os.path.relpath(Path(f).parent, anchor))
        parts = [] if str(rel) == "." else rel.parts
        for i in range(1, len(parts) + 1):
            sub = "/".join(parts[:i])
            if not (anchor / sub).exists() and sub not in found:
                found.append(sub)
    return found


def _git_items(target):
    items = []
    repo = dp.repository_of(target)
    if repo is None:
        items.append(item("WARN", "no git repository at or above the target: run `git init` there; the CI workflow is "
                                  "written anyway and runs once the project is pushed to GitHub"))
    elif os.path.normcase(os.path.abspath(repo)) != os.path.normcase(os.path.abspath(target)):
        items.append(item("WARN", f"the target is inside the repository {repo.as_posix()}, not at its root: GitHub reads "
                                  "`.github/workflows` at the repository root only, so move the workflow there"))
    return items


# ------------------------------------------------------------------ project: plan and apply


def _settings_preset(text):
    """The template's settings as a C17 preset (so the device area's append-only merge applies it)."""
    try:
        template = json.loads(text)
    except ValueError as exc:
        raise InitError(f"the template's {SETTINGS} is not JSON: {exc}") from exc
    preset = {"contract_version": "1.0", "env": {}, **template}
    if isinstance(template.get("permissions"), dict):   # C17 names both lists; an absent one adds nothing
        preset["permissions"] = {"deny": [], "ask": [], **template["permissions"]}
    schema = contract.load_schema(contract.find_schema(config.contracts_dir(), "C17"))
    problems = contract.validate_instance("C17", preset, schema)
    if problems:
        raise InitError(f"the template's {SETTINGS} does not satisfy C17: " + "; ".join(problems))
    return preset


def _plan_project(target, rendered, items):
    """[(rel, status, text)] for each template file; refusals and unusable settings go to `items`. status is NEW, SAME,
    CHANGED or, for the settings file, MERGED (some preset items are missing) or SAME."""
    plan = []
    for rel in sorted(rendered):
        text = rendered[rel]
        why = _blocked(target, rel)
        if why:
            items.append(item("REFUSED", f"{rel}: {why}", rel))
            continue
        path = Path(target) / rel
        if rel == SETTINGS:
            try:
                preset = _settings_preset(text)
                raw = path.read_bytes() if path.is_file() else None
                current = sm.parse(raw, path)
                sm.check_shapes(current, preset, path)
            except (InitError, sm.SettingsError, OSError) as exc:
                items.append(item("FAIL", f"{rel}: {exc}", rel))
                continue
            rows = sm.plan(current, preset)
            items.extend(item("WARN", f"{rel} {label}", rel) for tag, label in rows if tag == "WARN")
            missing = [label for tag, label in rows if tag == "NEW"]
            status = "NEW" if current is None else ("MERGED" if missing else "SAME")
            plan.append((rel, status, text))
            continue
        if not path.is_file():
            status = "NEW"
        else:
            status = "SAME" if _sha(path.read_bytes()) == _sha(text.encode("utf-8")) else "CHANGED"
        plan.append((rel, status, text))
    return plan


def _apply_file(manifest, base, base_dir, rel, status, data, items, label=None):
    """Write `data` at `base_dir/rel` for a NEW or CHANGED plan row (CHANGED backs the old file up first) and record it."""
    path = Path(base_dir) / rel
    backup = None
    if status == "CHANGED":
        backup = _backup(path)
        items.append(item("OK", f"backup of {rel} at {backup.name}", rel))
    _write_bytes(path, data)
    manifest.record(base, rel, data, backup.name if backup else None)


def _project_status_items(plan, items):
    for rel, status, _ in plan:
        if status == "MERGED":
            items.append(item("MERGED", f"{rel} (the template's permission rules added, nothing removed)", rel))
        elif status == "CHANGED":
            items.append(item("CHANGED", rel, rel))
        else:
            items.append(item(status, rel, rel))


def _write_project(manifest, target, anchor, plan, rendered, items):
    """Apply a plan; every file written is recorded in `manifest` at once (the caller saves it, also after an error)."""
    created = _new_dirs(anchor, [Path(target) / rel for rel, _, _ in plan] + [manifest.path])
    for sub in created:
        manifest.record_dir("anchor", sub)
    for rel, status, text in plan:
        if status == "SAME":
            continue
        path = Path(target) / rel
        if rel == SETTINGS:
            notes = []
            try:
                result = sm.write_verified(path, _settings_preset(text), notes=notes)
            except (sm.SettingsError, OSError, InitError) as exc:
                items.extend(item("WARN", n) for n in notes)
                items.append(item("FAIL", f"{rel}: {exc}", rel))
                continue
            items.extend(item("WARN", n) for n in notes)
            backup = Path(result["backup"]) if result.get("backup") else None
            if backup:
                items.append(item("OK", f"backup of {rel} at {backup.name}", rel))
            if result.get("wrote"):
                manifest.record("project", rel, path.read_bytes(), backup.name if backup else None)
            continue
        _apply_file(manifest, "project", target, rel, status, text.encode("utf-8"), items)


def _new_project_manifest(target, anchor, variables):
    anchor_rel = Path(os.path.relpath(anchor, target)).as_posix()
    return im.Manifest(Path(target) / config.PROJECT_DIR / im.FILE_NAME, "project",
                       {"project": ".", "anchor": anchor_rel}, variables)


def _project_variables(target, overrides, base=None):
    values = {"project_name": Path(os.path.abspath(target)).name or "project"}
    values["project_slug"] = slugify(values["project_name"])
    values.update(DEFAULTS)
    values.update(base or {})
    values.update(overrides)
    return values


def _project(args):
    items, as_json = [], _flag_json(args)

    def done(summary):
        return emit(AREA, "project", items, summary, as_json)

    try:
        overrides = parse_vars(args.var, VARIABLES)
        target = Path(os.path.abspath(args.target))
        if target.exists() and not target.is_dir():
            raise InitError(f"{target.as_posix()} is a file; --target names a folder")
        variables = _project_variables(target, overrides)
        rendered = render_project(variables)
        manifest_path = target / config.PROJECT_DIR / im.FILE_NAME
        manifest = im.Manifest.load(manifest_path) if manifest_path.exists() else None
        if manifest is not None and manifest.kind != "project":
            raise InitError(f"{manifest_path.as_posix()} is not a project manifest")
    except (InitError, im.ManifestError) as exc:
        items.append(item("FAIL", str(exc)))
        return done("init project: failed, nothing written")
    anchor = _anchor(target)
    plan = _plan_project(target, rendered, items)
    blocked = [i for i in items if i["tag"] in ("FAIL", "REFUSED")]
    _project_status_items(plan, items)
    items.extend(_git_items(target))
    if blocked:
        return done("init project: refused, nothing written")
    if not args.apply:
        items.append(item("SKIP", "dry run: nothing written (use --apply)"))
        return done(f"init project: {sum(1 for _, s, _ in plan if s != 'SAME')} of {len(plan)} file(s) to write (dry run)")
    if manifest is None:
        manifest = _new_project_manifest(target, anchor, variables)
    manifest.variables = variables
    try:
        _write_project(manifest, target, anchor, plan, rendered, items)
    except OSError as exc:
        items.append(item("FAIL", f"write failed ({type(exc).__name__}: {exc}); the manifest lists what was written"))
    finally:
        if manifest.files or manifest.dirs:
            manifest.save()
    return done(f"init project: {sum(1 for _, s, _ in plan if s != 'SAME')} of {len(plan)} file(s) written in "
                f"{target.as_posix()}")


# ------------------------------------------------------------------ user install


def _user_variables(overrides, base=None):
    values = {"user_name": os.environ.get("USER") or os.environ.get("USERNAME") or "the user", **USER_DEFAULTS}
    values.update(base or {})
    values.update(overrides)
    bad = [k for k, v in values.items() if not re.fullmatch(r"[^\x00-\x1f{}]{1,200}", str(v))]
    if bad:
        raise InitError(f"{', '.join(bad)}: 1 to 200 characters without control characters or braces")
    return values


def user_config_doc(values):
    """The user's `batuta.json` (C01): the built-in roles, caps, gates and budgets, roots from `BATUTA_*` variables, and the
    user core template with its values."""
    base = config.default_config()
    doc = {"contract_version": "1.1", "roots": {n: f"$BATUTA_{n.upper()}" for n in config.ROOT_NAMES},
           **{k: base[k] for k in ("roles", "caps", "gates", "dispatch", "coordination_root", "knowledge_manifest", "budgets")},
           "user_core": {"template": USER_CORE_TEMPLATE, "values": {k: values[k] for k in USER_KEYS}}}
    problems = config.validate(doc)
    if problems:
        raise InitError("the user configuration does not satisfy C01: " + "; ".join(problems))
    return doc


def _call_device(handler, **kwargs):
    """Run a device-area verb in this process and return (exit code, its C20 items)."""
    ns = argparse.Namespace(json=True, **kwargs)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = handler(ns)
    try:
        return code, json.loads(buffer.getvalue())["items"]
    except (ValueError, KeyError):
        return 1, [item("FAIL", f"the device area gave no readable result: {buffer.getvalue()[:200]!r}")]


def _user_paths(args):
    home = Path(args.home) if getattr(args, "home", None) else Path.home()
    deploy = dp.validate_root(dp.deploy_root(getattr(args, "deploy_root", None)), "deploy root", home)
    return home, deploy, home / ".claude"


def _walk_deploy(deploy):
    """{relative path: bytes} of what the device area mirrors into `deploy`, plus its profile (no caches, no backups)."""
    out = {}
    for area in device.MIRRORED:
        for p in sorted((Path(deploy) / area).rglob("*")) if (Path(deploy) / area).is_dir() else []:
            rel = p.relative_to(deploy)
            if p.is_file() and "__pycache__" not in rel.parts and p.suffix != ".pyc" and not device.BACKUP_COPY.search(p.name):
                out[rel.as_posix()] = p.read_bytes()
    profile = Path(deploy) / dp.PROFILE_FILE
    if profile.is_file():
        out[dp.PROFILE_FILE] = profile.read_bytes()
    return out


def _backup_names(folder, stem):
    folder = Path(folder)
    return {p.name for p in folder.glob(stem + ".bak-*")} if folder.is_dir() else set()


def _user_flow(args, items, mode):
    """`init user` and `init update --scope user`; returns the summary text."""
    apply = args.apply
    label = "init user" if mode == "init" else "init update"
    home, deploy, claude = _user_paths(args)
    manifest_path = deploy / im.FILE_NAME
    manifest = im.Manifest.load(manifest_path)
    if manifest is not None and manifest.kind != "user":
        raise InitError(f"{manifest_path.as_posix()} is not a user manifest")
    if mode == "update" and manifest is None:
        items.append(item("REFUSED", f"{manifest_path.as_posix()} not found: nothing was installed here by init user "
                                     "(run `init user --apply` first)"))
        return f"{label}: refused, nothing written"
    values = _user_variables(parse_vars(getattr(args, "var", None), USER_KEYS), manifest.variables if manifest else None)
    fresh = manifest is None
    if fresh:
        manifest = im.Manifest(manifest_path, "user", {"deploy": deploy.as_posix(), "claude": claude.as_posix()}, values)
    manifest.variables = values
    deploy_existed = deploy.exists()
    claude_existed = claude.exists()
    agents_existed = (claude / "agents").exists()
    pre_dirs = {a for a in device.MIRRORED if (deploy / a).exists()}
    sub_before = {p.relative_to(deploy).as_posix() for a in device.MIRRORED if (deploy / a).is_dir()
                  for p in (deploy / a).rglob("*") if p.is_dir()}

    # 1. the user's own configuration, never overwritten
    cfg_path = deploy / config.FILE_NAME
    cfg_text = json.dumps(user_config_doc(values), indent=2, ensure_ascii=False) + "\n"
    status = render.status(cfg_path, cfg_text)
    if status == "CHANGED":
        items.append(item("SKIP", f"{config.FILE_NAME} exists and differs from the template; kept as it is", config.FILE_NAME))
    else:
        items.append(item(status, config.FILE_NAME, config.FILE_NAME))
        if apply and status == "NEW":
            render.write_atomic(cfg_path, cfg_text)
            manifest.record("deploy", config.FILE_NAME, cfg_text.encode("utf-8"))

    cfg_arg = getattr(args, "config", None) or (cfg_path.as_posix() if cfg_path.is_file() else None)

    # 2. the device copy; a file the user edited since init is backed up before the mirror overwrites it
    if mode == "update" and apply:
        for e in list(manifest.files):
            if e["base"] == "deploy" and manifest.state(deploy, e["path"]) == "DIFFERENT" and (deploy / e["path"]).is_file():
                saved = _backup(deploy / e["path"])
                e["previous"].append(saved.name)
                items.append(item("OK", f"backup of {e['path']} at {saved.name} (edited since init)", e["path"]))
    code, ditems = _call_device(device._deploy, config=cfg_arg, home=str(home), deploy_root=str(deploy), apply=apply,
                                python=getattr(args, "python", None))
    items.extend(ditems)
    if any(i["tag"] in ("FAIL", "REFUSED") for i in ditems):
        return f"{label}: the device copy could not be installed, nothing further was done"
    if apply:
        mirrored = _walk_deploy(deploy)
        for rel, data in mirrored.items():
            manifest.record("deploy", rel, data)
        for e in list(manifest.files):
            if e["base"] == "deploy" and e["path"] not in mirrored and e["path"] != config.FILE_NAME:
                manifest.forget("deploy", e["path"])
        if not deploy_existed:
            manifest.record_dir("deploy", ".")
        for area in device.MIRRORED:
            if (deploy / area).is_dir() and area not in pre_dirs:
                manifest.record_dir("deploy", area)
        for a in device.MIRRORED:
            if (deploy / a).is_dir():
                for p in sorted((deploy / a).rglob("*")):
                    rel = p.relative_to(deploy).as_posix()
                    if p.is_dir() and rel not in sub_before and "__pycache__" not in p.parts:
                        manifest.record_dir("deploy", rel)

    # 3. the settings presets and the user core (the device area's restore), when the device copy exists
    if apply or (deploy / dp.PROFILE_FILE).is_file():
        settings, core = claude / "settings.json", claude / "CLAUDE.md"
        before = {"settings.json": settings.read_bytes() if settings.is_file() else None,
                  "CLAUDE.md": core.read_bytes() if core.is_file() else None}
        names_before = {"settings.json": _backup_names(claude, "settings.json"), "CLAUDE.md": _backup_names(claude, "CLAUDE.md")}
        code, ritems = _call_device(device._restore, config=cfg_arg, home=str(home), deploy_root=str(deploy), apply=apply,
                                    stubs=None, force=False)
        items.extend(ritems)
        if apply:
            for rel in ("settings.json", "CLAUDE.md"):
                path = claude / rel
                after = path.read_bytes() if path.is_file() else None
                if after is not None and after != before[rel]:
                    new = sorted(_backup_names(claude, rel) - names_before[rel])
                    manifest.record("claude", rel, after, new[0] if new else None)
            if not claude_existed and claude.exists():
                manifest.record_dir("claude", ".")
    else:
        items.append(item("SKIP", "restore of the settings and the user core is planned after the device copy exists "
                                  "(run with --apply)"))

    # 4. the agent files (the device channel has no plugin to bring them)
    source = PLUGIN_ROOT / "agents"
    files = sorted(source.glob("*.md")) if source.is_dir() else []
    if not files:
        items.append(item("WARN", f"no agent files next to this copy of Batuta ({source.as_posix()}); install the plugin or "
                                  "copy the agent files into ~/.claude/agents"))
    for f in files:
        rel, data = f"agents/{f.name}", f.read_bytes()
        why = _blocked(claude, rel)
        if why:
            items.append(item("REFUSED", f"{rel}: {why}", rel))
            continue
        path = claude / rel
        st = "NEW" if not path.is_file() else ("SAME" if _sha(path.read_bytes()) == _sha(data) else "CHANGED")
        items.append(item(st, rel, rel))
        if apply and st != "SAME":
            _apply_file(manifest, "claude", claude, rel, st, data, items)
    if apply and not agents_existed and (claude / "agents").exists():
        manifest.record_dir("claude", "agents")

    if apply and (manifest.files or manifest.dirs):
        manifest.save()
    return f"{label}: the user install in {deploy.as_posix()} ({'applied' if apply else 'dry run'})"


def _user(args):
    items = []
    try:
        summary = _user_flow(args, items, "init")
    except (InitError, im.ManifestError, dp.ProfileError, OSError) as exc:
        items.append(item("FAIL", str(exc)))
        summary = "init user: failed"
    if not args.apply:
        items.append(item("SKIP", "dry run: nothing written (use --apply)"))
    return emit(AREA, "user", items, summary, _flag_json(args))


# ------------------------------------------------------------------ update


def _update_project(args, items):
    target = Path(os.path.abspath(args.target))
    manifest_path = target / config.PROJECT_DIR / im.FILE_NAME
    manifest = im.Manifest.load(manifest_path)
    if manifest is None or manifest.kind != "project":
        items.append(item("REFUSED", f"{manifest_path.as_posix()} not found: nothing was installed here by init project"))
        return "init update: refused, nothing written"
    variables = _project_variables(target, parse_vars(getattr(args, "var", None), VARIABLES), manifest.variables)
    rendered = render_project(variables)
    plan = _plan_project(target, rendered, items)
    blocked = [i for i in items if i["tag"] in ("FAIL", "REFUSED")]
    _project_status_items(plan, items)
    stale = [e for e in manifest.files if e["base"] == "project" and e["path"] not in rendered]
    for e in stale:
        state = manifest.state(target, e["path"])
        items.append(item("REMOVED" if state == "SAME" else state, f"{e['path']} is no longer in the template", e["path"]))
    if blocked:
        return "init update: refused, nothing written"
    if not args.apply:
        items.append(item("SKIP", "dry run: nothing written (use --apply)"))
        return "init update: dry run"
    manifest.variables = variables
    try:
        _write_project(manifest, target, manifest.base_dir("anchor") if "anchor" in manifest.bases else target, plan,
                       rendered, items)
        for e in stale:
            if manifest.state(target, e["path"]) == "SAME":
                (target / e["path"]).unlink()
            manifest.forget("project", e["path"])
    except OSError as exc:
        items.append(item("FAIL", f"write failed ({type(exc).__name__}: {exc})"))
    finally:
        manifest.save()
    return f"init update: {sum(1 for _, s, _ in plan if s != 'SAME')} of {len(plan)} file(s) rewritten in {target.as_posix()}"


def _update(args):
    items = []
    try:
        if args.scope == "user":
            summary = _user_flow(args, items, "update")
        else:
            summary = _update_project(args, items)
    except (InitError, im.ManifestError, dp.ProfileError, OSError) as exc:
        items.append(item("FAIL", str(exc)))
        summary = "init update: failed"
    return emit(AREA, "update", items, summary, _flag_json(args))


# ------------------------------------------------------------------ uninstall


def _remove_dirs(manifest, items, apply):
    """Remove the folders init created, deepest first, only when empty (a `__pycache__` left by a run does not count)."""
    ordered = sorted(manifest.dirs, key=lambda d: (-(0 if d["path"] == "." else d["path"].count("/") + 1), d["base"]))
    for d in ordered:
        folder = manifest.base_dir(d["base"]) / (d["path"] if d["path"] != "." else "")
        label = d["path"] if d["path"] != "." else f"({d['base']})"
        if not folder.is_dir() or _is_link(folder):
            manifest.forget_dir(d["base"], d["path"])
            continue
        for cache in list(folder.rglob("__pycache__")):
            shutil.rmtree(cache, ignore_errors=True)
        if any(folder.iterdir()):
            items.append(item("SKIP", f"folder {label} still holds files that init did not write; kept", label))
            continue
        folder.rmdir()
        manifest.forget_dir(d["base"], d["path"])
        items.append(item("REMOVED", f"folder {label}", label))


def _uninstall_manifest(manifest, apply, items):
    kept = []
    for e in sorted(manifest.files, key=lambda x: (x["base"], x["path"])):
        base_dir = manifest.base_dir(e["base"])
        rel, target = e["path"], manifest.base_dir(e["base"]) / e["path"]
        state = manifest.state(base_dir, rel)
        if state == "MISSING":
            items.append(item("MISSING", f"{rel} was already removed", rel))
            if apply:
                manifest.forget(e["base"], rel)
            continue
        if state == "DIFFERENT":
            hint = " (remove the Batuta permission rules by hand if you want them gone)" if rel.endswith("settings.json") else ""
            items.append(item("DIFFERENT", f"{rel} changed since init; kept{hint}", rel))
            kept.append(rel)
            continue
        if e["backup"]:
            saved = target.with_name(e["backup"])
            if not saved.is_file():
                items.append(item("WARN", f"{rel}: the backup {e['backup']} of the file init replaced is missing; the installed "
                                          "file is kept", rel))
                kept.append(rel)
                continue
            items.append(item("CHANGED", f"{rel} restored from {e['backup']}", rel))
            if apply:
                _write_bytes(target, saved.read_bytes())
                saved.unlink()
        else:
            items.append(item("REMOVED", rel, rel))
            if apply:
                target.unlink()
        for name in e["previous"]:
            items.append(item("SKIP", f"kept {name}, an earlier version of {rel} (it may hold your edits)", rel))
        if apply:
            manifest.forget(e["base"], rel)
    if kept:
        items.append(item("WARN", f"{len(kept)} file(s) changed since init were kept: {', '.join(kept)}"))
    return kept


def _uninstall(args):
    items, as_json = [], _flag_json(args)
    try:
        if args.scope == "user":
            home, deploy, claude = _user_paths(args)
            manifest_path = deploy / im.FILE_NAME
        else:
            manifest_path = Path(os.path.abspath(args.target)) / config.PROJECT_DIR / im.FILE_NAME
        manifest = im.Manifest.load(manifest_path)
        if manifest is None or manifest.kind != args.scope:
            items.append(item("REFUSED", f"{manifest_path.as_posix()} not found: nothing was installed here by "
                                         f"init {args.scope}"))
            return emit(AREA, "uninstall", items, "init uninstall: refused, nothing changed", as_json)
        kept = _uninstall_manifest(manifest, args.apply, items)
        if args.apply:
            if not manifest.files:
                manifest.delete()
            else:
                manifest.save()
            _remove_dirs(manifest, items, args.apply)
            if manifest.files or manifest.dirs:
                if manifest_path.exists():
                    manifest.save()
        else:
            items.append(item("SKIP", "dry run: nothing changed (use --apply)"))
    except (InitError, im.ManifestError, dp.ProfileError, OSError) as exc:
        items.append(item("FAIL", str(exc)))
        return emit(AREA, "uninstall", items, "init uninstall: failed", as_json)
    return emit(AREA, "uninstall", items, f"init uninstall: {len(kept)} file(s) kept, the rest removed"
                if args.apply else "init uninstall: dry run", as_json)


# ------------------------------------------------------------------ doctor

_which = shutil.which                  # injectable by tests: where a command is, or None
_platform = lambda: sys.platform       # noqa: E731  (injectable by tests)
_python_version = lambda: tuple(sys.version_info[:3])   # noqa: E731  (injectable by tests)


def _node_version(path):
    """`node --version` of the executable at `path` as text such as `v22.1.0`, or None (injectable by tests)."""
    if not path:
        return None
    try:
        done = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _fix_command(text):
    return f'"{Path(sys.executable).as_posix()}" "{SCRIPT.as_posix()}" {text}'


def _bad(message, fix=None, tag="FAIL"):
    return item(tag, message + (f"; fix: {fix}" if fix else ""))


def _probe_python():
    version = _python_version()
    text = ".".join(str(n) for n in version)
    if tuple(version[:2]) >= MIN_PYTHON:
        return item("OK", f"Python {text} runs Batuta")
    return _bad(f"Python {text} is older than 3.10", "install Python 3.10 or newer; for the npx channel set BATUTA_PYTHON to "
                "its command (for example `py -3`), for the plugin channel set the plugin option python")


def _git_bash():
    """The path of Git for Windows' bash, or None (the WSL launcher in System32 is not it)."""
    found = _which("bash")
    if found and not re.search(r"(?i)[\\/](system32|windowsapps)[\\/]", found):
        return found
    env = os.environ
    for var, tail in (("ProgramFiles", "Git/bin/bash.exe"), ("ProgramFiles(x86)", "Git/bin/bash.exe"),
                      ("LOCALAPPDATA", "Programs/Git/bin/bash.exe")):
        if env.get(var) and (Path(env[var]) / tail).is_file():
            return (Path(env[var]) / tail).as_posix()
    git = _which("git")
    if git:
        candidate = Path(git).parent.parent / "bin" / "bash.exe"
        if candidate.is_file():
            return candidate.as_posix()
    return None


def _probe_bash(channel):
    if _platform() != "win32":
        return None
    found = _git_bash()
    if found:
        return item("OK", f"Git Bash found ({found})")
    if channel == "plugin":
        return _bad("Git Bash not found: the plugin's hooks run through bash on Windows",
                    "install Git for Windows from https://git-scm.com/download/win (it brings Git Bash)")
    return item("OK", "Git Bash not found; the device channel does not need it (its hooks run through the profile's Python)")


def _probe_node():
    path = _which("node")
    version = _node_version(path)
    if not path or not version:
        return _bad("Node not found: only the npx channel needs Node (18 or newer); the plugin and device channels run without it",
                    "install Node 18 or newer if you want `npx github:fsantibanezleal/CAOS_Batuta`", "WARN")
    match = re.match(r"v?(\d+)", version)
    if match and int(match.group(1)) < MIN_NODE:
        return _bad(f"Node {version} is older than {MIN_NODE}: only the npx channel needs it", f"install Node {MIN_NODE} or newer",
                    "WARN")
    return item("OK", f"Node {version} (needed by the npx channel only)")


def _probe_claude():
    if _which("claude"):
        return item("OK", "claude CLI found")
    return _bad("claude CLI not found: the plugin channel is unchecked here", "install Claude Code to use the plugin channel",
                "WARN")


def _plugin_option_python(home):
    """(value, where) of the plugin's `python` option: the environment Claude Code exports to hooks, else the user's
    settings (`pluginConfigs`), else (None, None)."""
    value = os.environ.get("CLAUDE_PLUGIN_OPTION_PYTHON")
    if value:
        return value, "the environment (CLAUDE_PLUGIN_OPTION_PYTHON)"
    path = Path(home) / ".claude" / "settings.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None, None
    configs = doc.get("pluginConfigs") if isinstance(doc, dict) else None
    for key, entry in sorted((configs or {}).items()) if isinstance(configs, dict) else []:
        if str(key).split("@")[0] == "batuta" and isinstance(entry, dict):
            options = entry.get("options") if isinstance(entry.get("options"), dict) else entry
            if isinstance(options.get("python"), str) and options["python"].strip():
                return options["python"].strip(), f"settings.json ({key})"
    return None, None


def _python_command_version(value):
    """The `major.minor` that the command in `value` reports, or None."""
    parts = [value] if Path(value).is_file() else shlex.split(value, posix=False)
    if not parts:
        return None
    try:
        done = subprocess.run([*parts, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout.strip()
    return text if done.returncode == 0 and re.fullmatch(r"\d+\.\d+", text) else None


def _probe_plugin_python(home):
    value, where = _plugin_option_python(home)
    if value is None:
        if _which("python3") or _platform() == "win32":
            return item("OK", "plugin option python not set; the default `python3` is used")
        return _bad("plugin option python is not set and `python3` is not on PATH",
                    "set the plugin option python to Python 3.10 or newer (on Windows `py` or the full path of python.exe)",
                    "WARN")
    version = _python_command_version(value)
    if version is None:
        return _bad(f"plugin option python {value!r} (from {where}) cannot be run",
                    "set the plugin option python to Python 3.10 or newer (on Windows `py` or the full path of python.exe)")
    major, minor = (int(n) for n in version.split("."))
    if (major, minor) < MIN_PYTHON:
        return _bad(f"plugin option python {value!r} (from {where}) is Python {version}, older than 3.10",
                    "set the plugin option python to Python 3.10 or newer")
    return item("OK", f"plugin option python {value!r} (from {where}) is Python {version}")


def _writable(folder):
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def _probe_roots(cfg, home):
    items = []
    try:
        roots = dp.resolve_roots(cfg, None, home)
    except dp.ProfileError as exc:
        return [_bad(f"roots: {exc}", "set the root in batuta.json or its BATUTA_* variable to an absolute folder outside "
                                      "any repository")]
    bad = []
    for name, key in dp.ROOT_KEYS.items():
        folder = Path(roots[key])
        if folder.exists() and not folder.is_dir():
            items.append(_bad(f"root '{name}' {folder.as_posix()} is a file, not a folder", f"point root '{name}' at a folder"))
            bad.append(name)
            continue
        anchor = _anchor(folder)
        if not anchor.is_dir() or not _writable(anchor):
            items.append(_bad(f"root '{name}' {folder.as_posix()} is not writable ({anchor.as_posix()})",
                              f"give your account write access to it or point root '{name}' elsewhere"))
            bad.append(name)
    if not bad:
        items.append(item("OK", "roots writable: " + ", ".join(dp.ROOT_KEYS)))
    return items


def _workflow_test_step(text):
    """The command of the step with `id: tests` in a workflow (its `run` block, dedented), or None."""
    lines = text.split("\n")
    steps = [i for i, ln in enumerate(lines) if re.match(r"^\s+- ", ln)]
    for n, start in enumerate(steps):
        end = steps[n + 1] if n + 1 < len(steps) else len(lines)
        block = lines[start:end]
        if not any(re.match(r"^\s+(- )?id:\s*tests\s*$", ln) for ln in block):
            continue
        for i, ln in enumerate(block):
            match = re.match(r"^(\s+)run:\s*(.*)$", ln)
            if not match:
                continue
            inline = match.group(2).strip()
            if inline and inline not in ("|", ">", "|-", ">-"):
                return inline
            body = []
            for line in block[i + 1:]:
                if line.strip() and len(line) - len(line.lstrip()) <= len(match.group(1)):
                    break
                body.append(line.strip())
            return "\n".join(b for b in body if b)
    return None


def _probe_project(project, args):
    items = []
    has_config = (project / config.PROJECT_DIR / config.FILE_NAME).is_file()
    workflow = project / WORKFLOW
    if not has_config and not workflow.is_file() and not (project / config.PROJECT_DIR / im.FILE_NAME).is_file():
        return [item("SKIP", f"{project.as_posix()} is not a Batuta project (no .batuta/batuta.json and no {WORKFLOW}); "
                             "run `init project --apply` there to make it one")]
    fix = _fix_command(f'init project --target "{project.as_posix()}" --apply')
    try:
        resolved = config.load(getattr(args, "config", None), project_root=project)
    except config.ConfigError as exc:
        return [_bad(f"project configuration: {exc}", "fix the file named above")]
    items.append(item("OK", f"project configuration valid ({resolved.source})"))
    from batuta_lib.tdd_history import DEFAULT_TEST_COMMAND
    configured = (resolved.config.get("tdd") or {}).get("test_command") or DEFAULT_TEST_COMMAND
    if not workflow.is_file():
        items.append(_bad(f"{WORKFLOW} not found: the required CI job batuta-gates is missing", fix))
        return items
    step = _workflow_test_step(workflow.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
    if step is None:
        items.append(_bad(f"{WORKFLOW} has no test step (the step with `id: tests`) in the batuta-gates job", fix))
    elif step.strip() != configured.strip():
        items.append(_bad(f"the batuta-gates test step runs {step.strip()!r} but tdd.test_command is {configured.strip()!r}: "
                          "the head check of `tdd check --replay` and the CI run must be the same command",
                          "make them one string: edit the `tests` step of the workflow or tdd.test_command in "
                          ".batuta/batuta.json"))
    else:
        items.append(item("OK", f"batuta-gates test step runs exactly tdd.test_command ({configured.strip()})"))
    return items


def _doctor(args):
    started = time.monotonic()
    items, as_json = [], _flag_json(args)
    home = Path(args.home) if args.home else Path.home()
    channel = args.channel
    if channel == "auto":
        channel = "plugin" if os.environ.get("CLAUDE_PLUGIN_ROOT") else "device"
    items.append(_probe_python())
    bash = _probe_bash(channel)
    if bash:
        items.append(bash)
    items.append(_probe_node())
    items.append(_probe_claude())
    if channel == "plugin":
        items.append(_probe_plugin_python(home))

    project = Path(os.path.abspath(args.project or "."))
    in_project = (project / config.PROJECT_DIR / config.FILE_NAME).is_file()
    try:
        deploy = dp.validate_root(dp.deploy_root(args.deploy_root), "deploy root", home)
    except dp.ProfileError as exc:
        items.append(_bad(f"deploy root: {exc}"))
        deploy = None
    cfg = None
    try:
        resolved = config.load(getattr(args, "config", None), project_root=project if in_project else None)
        cfg = resolved.config
        items.append(item("OK", f"configuration valid ({resolved.source}"
                                + (f", {resolved.path.as_posix()}" if resolved.path else "") + ")"))
    except config.ConfigError as exc:
        items.append(_bad(f"configuration: {exc}", "fix the file named above, or recreate it with `init user --apply`"))
    if cfg is not None:
        items.extend(_probe_roots(cfg, home))

    if deploy is not None:
        profile = deploy / dp.PROFILE_FILE
        if profile.is_file():
            for it in device._check_items(home, deploy, getattr(args, "config", None)):
                fix_text = it.pop("fix", None)
                items.append({**it, "message": it["message"] + (f"; fix: {fix_text}" if fix_text else "")})
        elif channel == "device":
            items.append(_bad(f"device copy not found at {deploy.as_posix()}", _fix_command("init user --apply")))
        else:
            items.append(item("SKIP", "no device copy; the plugin channel does not need one"))

    items.extend(_probe_project(project, args))
    elapsed = time.monotonic() - started
    failing = any(i["tag"] in ("FAIL", "REFUSED") for i in items)
    return emit(AREA, "doctor", items, f"doctor ({channel} channel): {'problems found' if failing else 'no failures'} "
                                       f"in {elapsed:.1f}s", as_json)


# ------------------------------------------------------------------ registration


def register(subparsers):
    def home_flags(p):
        p.add_argument("--home", help="home folder holding .claude/ (default: the user's home)")
        p.add_argument("--deploy-root", help="the device copy's folder (default: BATUTA_HOME, else ~/.batuta)")

    p = subparsers.add_parser("user", help="create the user configuration, deploy the device copy, restore settings, install agents")
    home_flags(p)
    p.add_argument("--python", help="the interpreter to record in the device profile (default: the running one)")
    p.add_argument("--var", action="append", help="user_name, language or tone as key=value (repeatable)")
    p.add_argument("--apply", action="store_true", help="write (default: dry run)")
    p.set_defaults(func=_user)

    p = subparsers.add_parser("project", help="render the project template into a folder (dry run unless --apply)")
    p.add_argument("--target", default=".", help="the project folder (default: the current folder)")
    p.add_argument("--var", action="append", help="project_name, project_slug, python_version, test_command or "
                                                   "default_branch as key=value (repeatable)")
    p.add_argument("--apply", action="store_true", help="write (default: dry run)")
    p.set_defaults(func=_project)

    p = subparsers.add_parser("doctor", help="the device check plus probes, each OK, WARN or FAIL with its fix")
    home_flags(p)
    p.add_argument("--project", help="the project folder to check (default: the current folder)")
    p.add_argument("--channel", choices=("auto", "device", "plugin"), default="auto",
                   help="which channel to check (default: plugin when run by Claude Code's plugin, else device)")
    p.set_defaults(func=_doctor)

    for name, func, text in (("update", _update, "render again from the current templates what the manifest lists"),
                             ("uninstall", _uninstall, "restore backups and remove what init wrote and the user left unchanged")):
        p = subparsers.add_parser(name, help=text)
        p.add_argument("--scope", choices=("project", "user"), default="project", help="what to act on (default: project)")
        p.add_argument("--target", default=".", help="the project folder for --scope project (default: the current folder)")
        home_flags(p)
        if name == "update":
            p.add_argument("--var", action="append", help="a template variable as key=value (repeatable)")
            p.add_argument("--python", help="the interpreter to record in the device profile (user scope)")
        p.add_argument("--apply", action="store_true", help="write (default: dry run)")
        p.set_defaults(func=func)
