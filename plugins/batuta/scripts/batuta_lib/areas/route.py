"""Area `route`: which agent role runs on which model, from the configuration (C01), and the agent files that carry it.

Verbs:
    show   print the role table (role, model, effort, omit_claude_md)
    check  validate the configuration (C01), every agent file in `plugins/batuta/agents/` (C18), the match between an
           agent's model and its role's model, and `omitClaudeMd: true` on every agent whose role runs on Haiku

An agent file is named after its role. A role without an agent file is fine (the file may come from a later unit); an
agent file without a role is a warning. Without a configuration file the C01 defaults apply, announced by a WARN line on
stderr that does not change the exit code. Exit codes: 0 ok, 1 failure, 2 warnings.
"""
from __future__ import annotations

import sys
from pathlib import Path

from batuta_lib import config, delegation
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm
from batuta_lib.output import emit, item

AREA = "route"
HELP = "Roles and models: show the routing table, check the agent files against it."

AGENTS_DIR = Path(__file__).resolve().parents[3] / "agents"


def _wants_json(args):
    return bool(getattr(args, "json", False))


def _load(args):
    """(roles, warnings, failure item or None)."""
    try:
        _root, resolved, warnings = delegation.project_config(args)
    except config.ConfigError as exc:
        return None, [], item("FAIL", f"configuration: {exc}")
    return resolved.config.get("roles", {}), warnings, None


def _flag(value):
    return "true" if value else "false"


def role_table(roles):
    """Rows (role, model, effort, omit_claude_md) in the order of the configuration."""
    return [(name, spec.get("model", ""), spec.get("effort", ""), bool(spec.get("omit_claude_md", False)))
            for name, spec in roles.items()]


def _show(args):
    roles, warnings, failure = _load(args)
    items = []
    for line in warnings:
        print(line, file=sys.stderr)
    if failure:
        return emit(AREA, "show", [failure], "route show failed", _wants_json(args))
    for name, model, effort, omit in role_table(roles):
        items.append(item("OK", f"role {name}: model={model} effort={effort} omit_claude_md={_flag(omit)}"))
    return emit(AREA, "show", items, f"{len(items)} role(s)", _wants_json(args))


def check_agents(roles, agents_dir):
    """Items for every agent file in `agents_dir` against C18 and the roles."""
    items = []
    schema_path = core.find_schema(config.contracts_dir(), "C18")
    folder = Path(agents_dir)
    if not folder.is_dir():
        return [item("FAIL", f"the agents folder does not exist: {folder.as_posix()}")]
    files = sorted(folder.glob("*.md"))
    if not files:
        items.append(item("WARN", f"no agent file in {folder.as_posix()}"))
    for path in files:
        rel = path.as_posix()
        stem = path.stem
        problems = core.validate_file(path, schema_path)
        if problems:
            items.extend(item("FAIL", f"agent {stem}: {p}", rel) for p in problems)
            continue
        meta, _body = fm.parse(delegation.read_text(path))
        bad = False
        if meta.get("name") != stem:
            items.append(item("FAIL", f"agent {stem}: name {meta.get('name')!r} differs from the file name", rel))
            bad = True
        role = roles.get(stem)
        if role is None:
            items.append(item("WARN", f"agent {stem} has no role of that name in the configuration", rel))
            continue
        model = str(meta.get("model", "")).strip()
        if model != role.get("model"):
            items.append(item("FAIL", f"agent {stem}: model {model!r} differs from the model {role.get('model')!r} of its role", rel))
            bad = True
        if role.get("model") == "haiku" and meta.get("omitClaudeMd") is not True:
            items.append(item("FAIL", f"agent {stem}: its role runs on haiku, so the file needs omitClaudeMd: true", rel))
            bad = True
        if not bad:
            items.append(item("OK", f"agent {stem} conforms to C18 and to its role", rel))
    return items


def _check(args):
    roles, warnings, failure = _load(args)
    for line in warnings:
        print(line, file=sys.stderr)
    if failure:
        return emit(AREA, "check", [failure], "route check failed", _wants_json(args))
    try:
        _root, resolved, _w = delegation.project_config(args)
        problems = config.validate(resolved.config)
    except config.ConfigError as exc:
        problems = [str(exc)]
    items = [item("FAIL", f"configuration: {p}") for p in problems] or [item("OK", "configuration satisfies C01")]
    items.extend(check_agents(roles, getattr(args, "agents_dir", None) or AGENTS_DIR))
    return emit(AREA, "check", items, f"{len(items)} item(s)", _wants_json(args))


def register(subparsers):
    show = subparsers.add_parser("show", help="print the role table from the configuration")
    show.add_argument("--root", default=".", help="project root holding .batuta/batuta.json (default: the current folder)")
    show.set_defaults(func=_show)
    check = subparsers.add_parser("check", help="check the configuration and the agent files against it")
    check.add_argument("--root", default=".", help="project root holding .batuta/batuta.json (default: the current folder)")
    check.add_argument("--agents-dir", default=None, help="the agent files (default: the plugin's agents folder)")
    check.set_defaults(func=_check)
