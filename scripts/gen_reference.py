#!/usr/bin/env python3
"""Generate the reference pages of the wiki from the code and the contracts, so they cannot drift.

Writes three files into `docs/reference/` (or into `--out DIR`):

  cli.md            every area and verb with its arguments, read from the dispatcher's argparse parsers;
  configuration.md  every key of the C01 schema with type, default and description, plus the environment variables;
  contracts.md      the catalog C01 to C34 with owner unit, format, version, frozen state and fixture counts,
                    read from `plugins/batuta/contracts/README.md` and the schema files.

Nothing is typed by hand about a command or a key except two small tables whose source is named where they are defined
(KEY_NOTES for C01 keys whose schema has no description, FREEZE_FACTS for the freeze dates of the contracts README).
Output is deterministic: UTF-8, LF, no timestamps, no terminal width, no machine path. `tests/test_docs_reference.py`
regenerates into a temporary folder and fails on any difference with the committed pages.

Usage:
    python scripts/gen_reference.py              write docs/reference/{cli,configuration,contracts}.md
    python scripts/gen_reference.py --out DIR    write them into DIR
    python scripts/gen_reference.py --check      compare with docs/reference and exit 1 on a difference
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "batuta" / "scripts"
CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"
DEFAULT_OUT = ROOT / "docs" / "reference"
PAGES = ("cli.md", "configuration.md", "contracts.md")

# Source: docs/decisions/ADR-0001 (CLI contract) and plan section 3.1 (port map): the unit that owns each area.
AREA_UNITS = {
    "route": "U2", "brief": "U2", "report": "U2",
    "spec": "U3", "size": "U3", "adr": "U3", "tech": "U3",
    "tdd": "U4",
    "gate": "U5", "skeleton": "U5", "provider": "U5", "lessons": "U5",
    "context": "U6", "memory": "U6",
    "device": "U7", "preflight": "U7",
    "guard": "U8", "leaks": "U8",
    "init": "U9", "fragments": "U9", "reserve": "U9",
    "dispatch": "U13",
    "contract": "U0", "version": "U1",
}

# Source: plugins/batuta/contracts/README.md, section Freeze (the generator refuses to run when that text changes).
FREEZE_FACTS = {
    "all": "frozen at 1.0 on 2026-10-13",
    "early": ("C12", "C13", "C14"),
    "early_text": "frozen first, on 2026-10-12",
    "revised": {"C01": "1.1", "C16": "1.1"},
    "added": {"C34": "1.0"},
    "revised_text": "additive revision 5 (ADR-0006), frozen on merge",
}
FREEZE_PHRASES = (
    "C01 to C33, was frozen at version 1.0 on 2026-10-13",
    "C12, C13, C14 and the C01",
    "frozen first, on 2026-10-12",
    "Additive revision 5 (ADR-0006) raised C01 and C16 to 1.1 and added C34 at 1.0, frozen on merge",
)

# Source of every entry: the C01 section of plugins/batuta/contracts/README.md and the area fragments in changes/.
# Used only for a C01 key whose schema carries no description (the generator fails when a key has neither).
KEY_NOTES = {
    "contract_version": "The contract version of the document: `1.0`, or `1.1` when it uses the `tdd` block.",
    "version": "Optional integer version of the document layout.",
    "roots": "The three device roots, by role. Values are paths or `$VAR` references; never a drive letter or user path.",
    "roots.temp": "Root for temporary files. An unset `$VAR` falls back to `<BATUTA_HOME>/temp`.",
    "roots.data": "Root for data and downloads. An unset `$VAR` falls back to `<BATUTA_HOME>/data`.",
    "roots.worktrees": "Root for git worktrees. An unset `$VAR` falls back to `<BATUTA_HOME>/worktrees`.",
    "roles": "One entry per agent role; `route check` compares each agent file with the role of the same name.",
    "roles.<role>": "The model and effort of one role.",
    "roles.<role>.model": "The model alias or id the role runs on: `haiku`, `sonnet`, `opus`, `fable` or `inherit`.",
    "roles.<role>.effort": "The reasoning effort: `low`, `medium`, `high` or `xhigh`.",
    "roles.<role>.omit_claude_md": "When true the agent file must carry `omitClaudeMd: true`, so the role does not load CLAUDE.md.",
    "caps": "Limits on delegation, read by `route`, `brief` and `dispatch`.",
    "caps.max_concurrent_agents": "Most agents running at once.",
    "caps.max_agents_per_task": "Most agents launched for one task.",
    "caps.max_opus_reviews_per_task": "Most reviews on the strongest model per task.",
    "caps.spawn_depth": "How deep a subagent may spawn subagents; the settings preset exports it as `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`.",
    "gates": "Which gates are critical and which model each kind of gate uses for its independent check.",
    "gates.adversary_model_critical": "Model of the reviewer that checks a critical gate.",
    "gates.adversary_model_routine": "Model of the adversary that checks every other gate.",
    "coordination_root": "Relative path of the folder that holds briefs, ledger and state (`delegation/ledger.md` lives under it).",
    "knowledge_manifest": "Relative path of the knowledge manifest (C12) read by `context build`.",
    "user_core.template": "Path, relative to the deploy root, of the template rendered into the user's always-loaded core.",
    "user_core.values": "Placeholder name to string, filled into the template.",
    "gates.critical": "Lifecycle gate names (`L0-understand` to `L10-lessons`) whose independent check is the reviewer on the critical model.",
    "dispatch.lanes": "The enabled lanes: `subagent`, `sdk` or `provider:<name>`.",
    "dispatch.providers": "Provider name to provider settings; credentials are environment variable names, never values.",
    "dispatch.sdk": "Settings of the sdk lane.",
    "tdd.markers": "Extra weakening markers (see the note on this key).",
    "budgets": "Byte and line limits of what loads at every session start (C14); `context check` enforces them.",
    "budgets.user_core_bytes": "Most bytes of the user-level core.",
    "budgets.project_core_bytes": "Most bytes of the project CLAUDE.md chain.",
    "budgets.unscoped_rules_bytes": "Most bytes of rule files that carry no `paths` front matter.",
    "budgets.memory_index_bytes": "Most bytes of a memory index (MEMORY.md).",
    "budgets.memory_index_lines": "Most lines of a memory index (MEMORY.md).",
    "dispatch.default_lane": "The lane used when `--lane` is not given.",
    "dispatch.providers.<name>": "One provider, referenced by a lane as `provider:<name>`.",
    "dispatch.providers.<name>.kind": "The adapter: `openai-compatible`, `gemini`, `bedrock` or `vertex` (`anthropic` for the sdk lane's credential).",
    "dispatch.providers.<name>.credential_env": "Name of the environment variable that holds the credential, never the credential.",
    "dispatch.providers.<name>.endpoint_env": "Name of the environment variable that holds the endpoint URL.",
}

# The C01 schema text of `tdd.markers` says the list replaces the default; the code adds to it (test_markers.weakening_markers).
# Source: changes/u4-plugin-readme.md (optional `tdd` block) and batuta_lib/test_markers.py.
TDD_OVERRIDES = {
    "tdd.markers": "Names of extra weakening markers that `tdd check` looks for. They add to the default list of every language; a default marker cannot be removed.",
}

# Source: the module docstrings of the areas (`adr.py`, `reserve.py`, `spec.py`, `brief.py`). Used only for an argument whose
# argparse definition has no help text; the generator fails on any other argument without one.
ARG_NOTES = {
    ("adr new", "--title"): "Title of the decision; the file is `docs/decisions/ADR-NNNN-<slug>.md` with the next free number.",
    ("brief new", "--title"): "Title of the brief, written as its first heading.",
    ("brief lint", "BRIEF"): "Path of the brief file to check.",
    ("reserve next", "REPO"): "Repository name of the `<repo>:<kind>` sequence.",
    ("reserve next", "KIND"): "Kind of number of the `<repo>:<kind>` sequence (for example a migration revision).",
    ("spec new", "--title"): "Title of the feature; the folder is `specs/<NNN-slug>/` with the next free number.",
}

ENV_VARS = (
    ("BATUTA_HOME", "config.ENV_HOME", "The user folder of Batuta: user `batuta.json`, the device copy and the fallback roots. Default `~/.batuta`."),
    ("BATUTA_CONFIG", "config.ENV_CONFIG", "Path of a `batuta.json` that wins over the project and user files. A path that does not exist is an error."),
    ("BATUTA_TEMP", None, "Usual value of `roots.temp` (`$BATUTA_TEMP`). Unset falls back to `<BATUTA_HOME>/temp`."),
    ("BATUTA_DATA", None, "Usual value of `roots.data` (`$BATUTA_DATA`). Unset falls back to `<BATUTA_HOME>/data`."),
    ("BATUTA_WORKTREES", None, "Usual value of `roots.worktrees` (`$BATUTA_WORKTREES`). Unset falls back to `<BATUTA_HOME>/worktrees`."),
    ("BATUTA_PYTHON", None, "Python interpreter the npx entry uses before it tries `py -3`, `python3` and `python` (changes/u9b-plugin-readme.md)."),
    ("BATUTA_LEAKS_DENY_LIST", None, "Path of the private deny-list file of `leaks scan`, outside the repository (docs/reference/enforcement-matrix.md)."),
)

# Source: docs/reference/enforcement-matrix.md, section "Configuration read by the guards". Keys outside C01's declared set
# (C01 allows extra keys) that the guard and leaks areas read.
GUARD_KEYS = (
    ("tdd.lock_file", "`guard-locked-tests`, tdd area", "`.batuta/test-locks.json`", "Relative POSIX path of the test lock file; no `..`."),
    ("guards.secret_globs", "`guard-secrets`", "built-in list (environment files, keys, certificates, credentials)", "Extra globs of files an agent never reads."),
    ("guards.protected_branches", "`guard-destructive`", "`main`, `master`, `develop`, `release/*`", "Extra protected branch names or globs."),
    ("guards.destructive_disable", "`guard-destructive`", "none", "Names of destructive packs to switch off."),
    ("guards.require_brief", "`guard-require-brief`", "`deny`", "`deny`, `ask` or `off`: what happens to an Agent launch without a valid brief."),
    ("guards.scan_ignore", "`guard scan`", "`**/*.md`", "Globs the scan skips; read from the base revision of the scanned range."),
    ("leaks.allow_emails", "`leaks scan`", "the built-in non-personal addresses", "Extra e-mail patterns the scan accepts."),
)


# ------------------------------------------------------------------------------------------------------ helpers


def _load_batuta():
    """The dispatcher module and its parser, built the way `batuta.py` builds it."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import batuta  # noqa: E402  (the dispatcher script)

    areas, warnings = batuta.load_areas()
    if warnings:
        raise SystemExit("an area failed to load, the reference would be incomplete:\n" + "\n".join(warnings))
    return batuta, batuta.build_parser(areas, "0"), areas


def _md_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _code(text):
    return "`" + str(text).replace("`", "'") + "`"


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return out


# ------------------------------------------------------------------------------------------------------ cli.md


def _sub_action(parser):
    for action in parser._actions:  # noqa: SLF001 (argparse offers no public walk)
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return action
    return None


def _children(parser):
    """[(name, help, parser)] of the verbs of a parser, aliases collapsed onto the first name."""
    sub = _sub_action(parser)
    if sub is None:
        return []
    helps = {pa.dest: pa.help for pa in sub._choices_actions}  # noqa: SLF001
    seen, out = set(), []
    for name, child in sub.choices.items():
        if id(child) in seen:
            continue
        seen.add(id(child))
        out.append((name, helps.get(name) or "", child))
    return out


def _is_help(action):
    return isinstance(action, argparse._HelpAction)  # noqa: SLF001


def _real_actions(parser):
    return [a for a in parser._actions if not _is_help(a) and not isinstance(a, argparse._SubParsersAction)  # noqa: SLF001
            and a.dest != "func"]


def _flag_name(action):
    return " / ".join(action.option_strings) if action.option_strings else action.dest


def _metavar(action):
    if action.metavar:
        return action.metavar if isinstance(action.metavar, str) else " ".join(action.metavar)
    if action.choices:
        return "{" + ",".join(str(c) for c in action.choices) + "}"
    return action.dest.upper()


def _takes_value(action):
    return not isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._StoreConstAction,  # noqa: SLF001
                                   argparse._CountAction, argparse._VersionAction))  # noqa: SLF001


def _is_required(action):
    if action.option_strings:
        return bool(action.required)
    return action.nargs not in ("?", "*", argparse.REMAINDER)


def _arg_text(action):
    """How the argument is written on the command line."""
    if not action.option_strings:
        meta = _metavar(action)
        if action.nargs == "+":
            return f"{meta} [{meta} ...]"
        if action.nargs == "*":
            return f"[{meta} ...]"
        if action.nargs == "?":
            return f"[{meta}]"
        return meta
    first = max(action.option_strings, key=len)
    return f"{first} {_metavar(action)}" if _takes_value(action) else first


def _cell_text(action):
    """The argument as shown in a table: every spelling of an option, then its value."""
    if not action.option_strings:
        return _arg_text(action)
    names = " / ".join(sorted(action.option_strings, key=lambda s: (len(s), s)))
    return f"{names} {_metavar(action)}" if _takes_value(action) else names


def _type_text(action):
    if not _takes_value(action):
        return "flag"
    parts = []
    if action.choices:
        parts.append("one of " + ", ".join(str(c) for c in action.choices))
    else:
        t = getattr(action.type, "__name__", None) if action.type else "str"
        parts.append(t or "str")
    if action.nargs == "+":
        parts.append("one or more")
    elif action.nargs == "*":
        parts.append("zero or more")
    if isinstance(action, argparse._AppendAction):  # noqa: SLF001
        parts.append("repeatable")
    return ", ".join(parts)


def _default_text(action):
    if not _takes_value(action) or action.default in (None, argparse.SUPPRESS):
        return "none"
    if isinstance(action.default, (list, tuple)) and not action.default:
        return "none"
    return _code(action.default)


def _help_text(action, command=None):
    text = (action.help or "").replace("%(default)s", str(action.default)).replace("%%", "%")
    text = " ".join(text.split())
    if not text and command is not None:
        text = ARG_NOTES.get((command, action.option_strings[0] if action.option_strings else action.dest.upper()), "")
        if not text:
            raise SystemExit(f"{command}: argument {_flag_name(action)} has no help text; add help= to its parser "
                             "or an entry to ARG_NOTES in scripts/gen_reference.py")
    return text


def _usage(path, parser):
    groups = {}
    for group in parser._mutually_exclusive_groups:  # noqa: SLF001
        for action in group._group_actions:  # noqa: SLF001
            groups[id(action)] = group
    parts, done = [], set()
    for action in _real_actions(parser):
        group = groups.get(id(action))
        if group is not None:
            if id(group) in done:
                continue
            done.add(id(group))
            members = " | ".join(_arg_text(a) for a in group._group_actions if not _is_help(a))  # noqa: SLF001
            parts.append(f"({members})" if group.required else f"[{members}]")
        elif action.option_strings:
            text = _arg_text(action)
            parts.append(text if _is_required(action) else f"[{text}]")
        else:
            parts.append(_arg_text(action))
    ordered = [p for p in parts if not p.startswith(("[-", "(-"))] + [p for p in parts if p.startswith(("[-", "(-"))]
    return " ".join(["batuta.py", path] + ordered)


def _command_section(path, help_text, parser, level):
    out = [f"{'#' * level} `{path}`", ""]
    if help_text:
        out += [help_text[0].upper() + help_text[1:] + ("" if help_text.endswith(".") else "."), ""]
    out += ["```", _usage(path, parser), "```", ""]
    actions = _real_actions(parser)
    group_required = set()
    for group in parser._mutually_exclusive_groups:  # noqa: SLF001
        if group.required:
            group_required.update(id(a) for a in group._group_actions)  # noqa: SLF001
    if actions:
        rows = []
        for action in actions:
            required = "yes" if _is_required(action) else ("one of a group" if id(action) in group_required else "no")
            rows.append([_code(_cell_text(action)), required, _type_text(action), _default_text(action), _help_text(action, path)])
        out += _table(["Argument", "Required", "Type", "Default", "Description"], rows) + [""]
    return out


def _walk(path, parser, level, out, counter):
    for name, help_text, child in _children(parser):
        full = f"{path} {name}".strip()
        if _sub_action(child) is not None and not _real_actions(child):
            out += [f"{'#' * level} `{full}`", ""]
            if help_text:
                out += [help_text[0].upper() + help_text[1:] + ("" if help_text.endswith(".") else "."), ""]
            _walk(full, child, level + 1, out, counter)
        else:
            counter[0] += 1
            out += _command_section(full, help_text, child, level)
            if _sub_action(child) is not None:
                _walk(full, child, level + 1, out, counter)


def build_cli():
    batuta, parser, areas = _load_batuta()
    from batuta_lib import output  # noqa: E402

    out = ["# Command line reference", "",
           "Generated by `scripts/gen_reference.py` from the argparse parsers of the dispatcher "
           "(`plugins/batuta/scripts/batuta.py`); do not edit by hand. `tests/test_docs_reference.py` fails when this page "
           "differs from the code.", "",
           "Every command is `python batuta.py <area> <verb> [arguments]`. The dispatcher imports every module of "
           "`batuta_lib/areas/`; a module that fails to load is reported as `WARN area <name> failed to load: <error>` and "
           "skipped.", "", "## Global options", "",
           "Accepted before or after the area and verb.", ""]
    rows = [[_code(_cell_text(a)), "no", _type_text(a), _default_text(a), _help_text(a)] for a in _real_actions(parser)
            if a.dest != "area"]
    out += _table(["Argument", "Required", "Type", "Default", "Description"], rows) + [""]
    out += ["## Output and exit codes", "",
            "Every area prints tag-prefixed lines, then a summary; with `--json` it prints the C20 object "
            "(`contract_version`, `tool`, `area`, `verb`, `exit_code`, `items`, `summary`).", "",
            "Tags: " + ", ".join(f"`{t}`" for t in output.TAGS) + ".", "",
            "Exit code 0 is ok, 1 is a failure or refusal (any `FAIL` or `REFUSED` item, and also a usage error), and 2 is "
            "warnings or an honest partial (any `WARN` item). A write is a dry run unless `--apply` is given.", ""]
    counter = [0]
    for area_name, area_help, area_parser in _children(parser):
        unit = AREA_UNITS.get(area_name, "")
        out += [f"## Area `{area_name}`", "", (area_help or "").rstrip(".") + "." + (f" Owner unit: {unit}." if unit else ""), ""]
        _walk(area_name, area_parser, 3, out, counter)
    index = ["## Index", ""] + [f"- `{n}`: {h}" for n, h, _ in _children(parser)] + [""]
    head, body = out[: out.index("## Global options")], out[out.index("## Global options"):]
    return "\n".join(head + index + body).rstrip("\n") + "\n"


# ------------------------------------------------------------------------------------------------ configuration.md


def _resolve(schema, node):
    while isinstance(node, dict) and "$ref" in node:
        node = schema["$defs"][node["$ref"].split("/")[-1]]
    return node


def _type_of(node, schema=None):
    t = node.get("type", "any")
    t = " or ".join(t) if isinstance(t, list) else t
    if t == "array" and isinstance(node.get("items"), dict):
        item = _resolve(schema, node["items"]) if schema else node["items"]
        inner = _type_of(item, schema)
        t = f"array of {inner}"
    if t == "object" and isinstance(node.get("additionalProperties"), dict) and node["additionalProperties"].get("type") == "string":
        t = "object of string"
    if "enum" in node:
        t += ": " + ", ".join(str(v) for v in node["enum"])
    for key, label in (("minimum", "min"), ("maximum", "max"), ("minLength", "min length")):
        if key in node:
            t += f" ({label} {node[key]})"
    if node.get("pattern"):
        t += " (pattern)"
    return t


def _walk_schema(schema, node, path, required, rows):
    node = _resolve(schema, node)
    if not isinstance(node, dict):
        return
    desc = node.get("description", "")
    rows.append({"path": path, "type": _type_of(node, schema), "required": required, "description": desc, "node": node})
    for key, sub in (node.get("properties") or {}).items():
        _walk_schema(schema, sub, f"{path}.{key}" if path else key, key in (node.get("required") or []), rows)
    add = node.get("additionalProperties")
    if isinstance(add, dict) and "$ref" in add:
        label = {"roles": "<role>", "providers": "<name>"}.get(path.split(".")[-1], "<key>")
        _walk_schema(schema, add, f"{path}.{label}", False, rows)


def _defaults():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from batuta_lib import config, tdd_history, tdd_lock  # noqa: E402

    base = config.default_config({"BATUTA_HOME": "<BATUTA_HOME>"})
    flat = {}

    def flatten(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                flatten(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            flat[path] = node
        else:
            flat[path] = node

    flatten(base, "")
    for k in ("roots.temp", "roots.data", "roots.worktrees"):
        flat[k] = f"<BATUTA_HOME>/{k.split('.')[1]}"
    flat["tdd.test_command"] = tdd_history.DEFAULT_TEST_COMMAND + " (with `-t .` added when `tests` is a package)"
    flat["tdd.replay_timeout_seconds"] = int(tdd_history.DEFAULT_REPLAY_TIMEOUT)
    flat["tdd.lock_file"] = tdd_lock.DEFAULT_LOCK
    flat["tdd.markers"] = "the built-in list of every language"
    return flat, base


def _default_cell(path, flat, base):
    if path.startswith("roles.<role>"):
        return "see the role table below"
    if path in flat:
        value = flat[path]
        return _code(json.dumps(value)) if isinstance(value, (list, dict)) else _code(value)
    if path in ("roots", "roles", "caps", "gates", "budgets", "dispatch", "tdd", "user_core", "dispatch.providers"):
        return "object"
    return "none"


def build_configuration():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from batuta_lib import config, contract  # noqa: E402

    schema = contract.load_schema(contract.find_schema(CONTRACTS, "C01"))
    flat, base = _defaults()
    rows = []
    for key, sub in schema["properties"].items():
        _walk_schema(schema, sub, key, key in schema.get("required", []), rows)
    _walk_schema(schema, {"$ref": "#/$defs/tdd"}, "tdd", False, rows)
    table, missing = [], []
    for row in rows:
        path = row["path"]
        description = TDD_OVERRIDES.get(path) or row["description"] or KEY_NOTES.get(path, "")
        if not description:
            missing.append(path)
            continue
        table.append([_code(path), row["type"], "yes" if row["required"] else "no", _default_cell(path, flat, base),
                      " ".join(description.split())])
    if missing:
        raise SystemExit("C01 keys with no description in the schema or in KEY_NOTES: " + ", ".join(missing))
    out = ["# Configuration reference", "",
           "Generated by `scripts/gen_reference.py` from the C01 schema "
           "(`plugins/batuta/contracts/C01-batuta-config.schema.json`) and the built-in defaults of "
           "`batuta_lib/config.py`; do not edit by hand. `tests/test_docs_reference.py` fails when this page differs "
           "from the code.", "",
           f"`batuta.json` is a C01 document (contract version {_c01_version(schema)}). It is found in this order: "
           "`--config PATH`, `$BATUTA_CONFIG`, the project file `.batuta/batuta.json`, the user file "
           "`<BATUTA_HOME>/batuta.json`, then the built-in defaults. `$VAR` and `${VAR}` expand from the environment "
           "before validation, so a variable cannot smuggle in a path that C01 refuses. A field that holds an "
           "environment variable NAME (`credential_env`, `endpoint_env`) is never expanded.", "",
           "## Keys", "",
           "The Default column is the value of the built-in defaults when no file exists; `none` means the key is optional "
           "and absent by default. Keys the schema does not list are allowed (`additionalProperties`), which is how the "
           "areas read their own optional keys (next section).", ""]
    out += _table(["Key", "Type", "Required", "Default", "Description"], table) + [""]
    out += ["## Default roles", ""]
    out += _table(["Role", "Model", "Effort", "Omit CLAUDE.md"],
                  [[_code(r), _code(v["model"]), _code(v["effort"]), "yes" if v.get("omit_claude_md") else "no"]
                   for r, v in base["roles"].items()]) + [""]
    out += ["## Keys read by areas that C01 does not declare", "",
            "Source: `docs/reference/enforcement-matrix.md`. Every key is optional; a missing key keeps the default.", ""]
    out += _table(["Key", "Read by", "Default", "Meaning"], [[_code(k), by, d, m] for k, by, d, m in GUARD_KEYS]) + [""]
    out += ["## Environment variables", ""]
    env_rows = []
    for name, const, text in ENV_VARS:
        if const:
            actual = getattr(config, const.split(".")[1])
            if actual != name:
                raise SystemExit(f"{const} is {actual!r}, not {name!r}")
        env_rows.append([_code(name), text])
    out += _table(["Variable", "Use"], env_rows) + [""]
    return "\n".join(out).rstrip("\n") + "\n"


def _c01_version(schema):
    return "1.1" if "1.1" in schema["properties"]["contract_version"].get("enum", []) else schema.get("contract_version", "1.0")


# ------------------------------------------------------------------------------------------------ contracts.md


def _catalog_rows(text):
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\| (C\d\d) \| `([^`]+)` \| (.*) \| (.*) \| (.*) \| ([\d.]+) \|$", line)
        if m:
            rows.append(m.groups())
    return rows


def _producer_units(producer):
    units = []
    for token in re.findall(r"`([a-z-]+) [a-z-]+`|`([a-z-]+)`", producer):
        area = token[0] or token[1]
        unit = AREA_UNITS.get(area)
        if unit and unit not in units:
            units.append(unit)
    return ", ".join(units) if units else "-"


def _fixture_counts(cid):
    folder = CONTRACTS / "fixtures" / cid
    valid = sum(1 for p in folder.glob("valid-*")) if folder.is_dir() else 0
    invalid = sum(1 for p in folder.glob("invalid-*")) if folder.is_dir() else 0
    return valid, invalid


def build_contracts():
    readme = (CONTRACTS / "README.md").read_text(encoding="utf-8")
    for phrase in FREEZE_PHRASES:
        if phrase not in readme:
            raise SystemExit(f"the contracts README no longer says {phrase!r}: update FREEZE_FACTS in scripts/gen_reference.py")
    catalog = _catalog_rows(readme)
    if not catalog:
        raise SystemExit("no catalog rows found in the contracts README")
    rows = []
    for cid, file_name, artifact, producer, consumers, version in catalog:
        schema_path = CONTRACTS / file_name
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if schema.get("contract_id") != cid:
            raise SystemExit(f"{file_name} says contract_id {schema.get('contract_id')!r}, not {cid}")
        if schema.get("contract_version") != version:
            raise SystemExit(f"{file_name} is version {schema.get('contract_version')!r}, the README says {version}")
        sections = CONTRACTS / file_name.replace(".schema.json", ".sections.json")
        if sections.is_file():
            meta = json.loads(sections.read_text(encoding="utf-8"))
            kind = meta.get("front_matter", "required")
            fmt = "Markdown lines" if meta.get("mode") == "lines" else {
                "required": "Markdown, front matter", "bullets": "Markdown, metadata bullets", "none": "Markdown, tables and sections"
            }.get(kind, "Markdown")
        else:
            fmt = "JSON"
        first = FREEZE_FACTS["early_text"].replace("frozen first, on ", "first on ")
        done = FREEZE_FACTS["all"].replace("frozen at ", "").replace(" on ", " on ")
        if cid == "C01":
            frozen = (f"budgets block {first}; {done}; 1.1 with {FREEZE_FACTS['revised_text']}")
        elif cid in FREEZE_FACTS["revised"]:
            frozen = f"{done}; {FREEZE_FACTS['revised'][cid]} with {FREEZE_FACTS['revised_text']}"
        elif cid in FREEZE_FACTS["added"]:
            frozen = f"{FREEZE_FACTS['added'][cid]} with {FREEZE_FACTS['revised_text']}"
        elif cid in FREEZE_FACTS["early"]:
            frozen = f"{first}; {done}"
        else:
            frozen = done
        owner = "U0r5 (ADR-0006)" if cid == "C34" else "U0"
        v, i = _fixture_counts(cid)
        title = schema.get("title", "")
        rows.append([_code(cid), title, _code(file_name), fmt, version, owner, _producer_units(producer), frozen, f"{v} / {i}"])
    out = ["# Data contracts catalog", "",
           "Generated by `scripts/gen_reference.py` from `plugins/batuta/contracts/README.md` (the catalog table and the "
           "Freeze section) and the schema files next to it; do not edit by hand. `tests/test_docs_reference.py` fails "
           "when this page differs from the code. The README holds the artifact, producer and consumer text of each row; "
           "this page adds the version read from each schema, the format, the owner unit and the fixture counts.", "",
           "Owner unit is the unit that wrote and froze the contract: U0 for C01 to C33 (plan section 5), U0r5 for the "
           "additive revision of C01 and C16 and for C34 (ADR-0006). Producer unit is the unit that owns the command "
           "area named in the README's Producer column (the port map of plan section 3.1); a dash means the README "
           "names a person, an agent or a tool outside the command areas.", "",
           "Fixtures are counted from `plugins/batuta/contracts/fixtures/<id>/` as valid / invalid files; every contract "
           "has at least two valid and three invalid ones, and `contract lint` fails below that.", ""]
    out += _table(["Id", "Title", "Schema file", "Format", "Version", "Owner unit", "Producer unit", "Frozen", "Fixtures"], rows) + [""]
    out += ["## Rules every contract follows", "",
            "- A contract changes only by a new version: a major bump for a breaking change, a minor bump for an additive "
            "one, and the old version stays until no producer emits it. After the freeze, contracts evolve only "
            "additively (plan decision 23).",
            "- Producers validate what they write and consumers what they read, with `python batuta.py contract validate "
            "<id> <file>`; CI lints every schema and fixture with `python batuta.py contract lint`.",
            "- The schema dialect is a restricted JSON Schema draft 2020-12; the validator refuses a schema that uses "
            "anything outside it. See `plugins/batuta/contracts/README.md` for the dialect, the sections files of the "
            "Markdown contracts and the fixture rules.", ""]
    return "\n".join(out).rstrip("\n") + "\n"


# ------------------------------------------------------------------------------------------------------ main


def build_all():
    return {"cli.md": build_cli(), "configuration.md": build_configuration(), "contracts.md": build_contracts()}


def write_pages(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = build_all()
    for name, text in pages.items():
        (out_dir / name).write_bytes(text.encode("utf-8"))
    return pages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder to write the pages into (default: docs/reference)")
    parser.add_argument("--check", action="store_true", help="compare with docs/reference and exit 1 on a difference")
    args = parser.parse_args(argv)
    if args.check:
        bad = []
        for name, text in build_all().items():
            path = DEFAULT_OUT / name
            if not path.is_file() or path.read_bytes() != text.encode("utf-8"):
                bad.append(name)
        if bad:
            print("gen_reference: out of date: " + ", ".join(bad) + "; run `python scripts/gen_reference.py`")
            return 1
        print("gen_reference: docs/reference matches the code")
        return 0
    pages = write_pages(args.out)
    for name in pages:
        print(f"wrote {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
