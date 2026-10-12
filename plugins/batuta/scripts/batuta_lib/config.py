"""Configuration shared by every area: where `batuta.json` comes from, its validation (C01) and `$VAR` expansion.

Resolution order, first hit wins:

1. `--config PATH`
2. the environment variable `BATUTA_CONFIG`
3. the project file `.batuta/batuta.json` under the project root
4. the user file `<BATUTA_HOME>/batuta.json` (`BATUTA_HOME` defaults to `~/.batuta`)
5. the built-in defaults (`default_config`), when no file exists at all

A path named by `--config` or `BATUTA_CONFIG` that does not exist is an error, never a silent fallback. A file is a
whole C01 document: it is validated as written (the same check as `contract validate C01`), then `$VAR` and `${VAR}`
expand from the environment. An unset root variable falls back to `<BATUTA_HOME>/temp|data|worktrees`; an unset
variable anywhere else stays as written and is listed in `Resolved.unresolved`. No drive letter or user path is built
into the defaults.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from batuta_lib import contract

ENV_CONFIG = "BATUTA_CONFIG"
ENV_HOME = "BATUTA_HOME"
FILE_NAME = "batuta.json"
PROJECT_DIR = ".batuta"
ROOT_NAMES = ("temp", "data", "worktrees")
_VAR = re.compile(r"\$(?:\{(\w+)\}|(\w+))", re.ASCII)


class ConfigError(ValueError):
    """The configuration cannot be used; the message lists every problem."""


@dataclass
class Resolved:
    config: dict
    source: str                      # "--config", "BATUTA_CONFIG", "project", "user" or "defaults"
    path: Path = None                # the file read, None for the defaults
    unresolved: list = field(default_factory=list)


def _env(env):
    return os.environ if env is None else env


def home_dir(env=None):
    """`BATUTA_HOME`, or `~/.batuta`."""
    e = _env(env)
    return Path(e[ENV_HOME]) if e.get(ENV_HOME) else Path.home() / PROJECT_DIR


def contracts_dir():
    """Batuta's own contracts, shipped inside the plugin (the C01 schema is read from here)."""
    return Path(__file__).resolve().parents[2] / "contracts"


def _schema():
    sp = contract.find_schema(contracts_dir(), "C01")
    if sp is None:
        raise ConfigError(f"the C01 schema is not found in {contracts_dir()}")
    return contract.load_schema(sp)


def candidates(config_arg=None, project_root=None, env=None):
    """The places to look, in order, as (source, path). The first two are explicit and must exist when given."""
    e = _env(env)
    out = []
    if config_arg:
        out.append(("--config", Path(config_arg)))
    if e.get(ENV_CONFIG):
        out.append(("BATUTA_CONFIG", Path(e[ENV_CONFIG])))
    if project_root is not None:
        out.append(("project", Path(project_root) / PROJECT_DIR / FILE_NAME))
    out.append(("user", home_dir(e) / FILE_NAME))
    return out


def find_config(config_arg=None, project_root=None, env=None):
    """(source, path) of the first configuration file, or None. Raises ConfigError for a named file that is missing."""
    for source, path in candidates(config_arg, project_root, env):
        if path.is_file():
            return source, path
        if source in ("--config", "BATUTA_CONFIG"):
            raise ConfigError(f"{source} names {path.as_posix()}, which does not exist")
    return None


def expand(value, env=None):
    """Expand `$VAR` and `${VAR}` in a string. Returns (text, names that were unset); an unset name stays as written."""
    e = _env(env)
    missing = []

    def sub(m):
        name = m.group(1) or m.group(2)
        if name in e:
            return e[name]
        missing.append(name)
        return m.group(0)

    return _VAR.sub(sub, value), missing


def _expand_tree(node, env, missing):
    if isinstance(node, str):
        text, miss = expand(node, env)
        missing.extend(miss)
        return text
    if isinstance(node, list):
        return [_expand_tree(x, env, missing) for x in node]
    if isinstance(node, dict):
        return {k: _expand_tree(v, env, missing) for k, v in node.items()}
    return node


def default_config(env=None):
    """The built-in configuration: the roles, caps, gates and budgets of the design, roots under `BATUTA_HOME`."""
    home = home_dir(env)
    return {
        "contract_version": "1.0",
        "version": 1,
        "roots": {name: str(home / name) for name in ROOT_NAMES},
        "roles": {
            "searcher": {"model": "haiku", "effort": "low", "omit_claude_md": True},
            "runner": {"model": "haiku", "effort": "low", "omit_claude_md": True},
            "implementer": {"model": "sonnet", "effort": "medium"},
            "test-author": {"model": "sonnet", "effort": "medium"},
            "doc-writer": {"model": "sonnet", "effort": "medium"},
            "adversary": {"model": "sonnet", "effort": "high"},
            "reviewer": {"model": "opus", "effort": "high"},
        },
        "caps": {"max_concurrent_agents": 4, "max_agents_per_task": 8, "max_opus_reviews_per_task": 1, "spawn_depth": 1},
        "gates": {"critical": ["L2-decide", "L5-freeze", "L9-promote"], "critical_units": [],
                  "adversary_model_critical": "opus", "adversary_model_routine": "sonnet"},
        "dispatch": {"default_lane": "subagent", "lanes": ["subagent"]},
        "coordination_root": PROJECT_DIR,
        "knowledge_manifest": f"{PROJECT_DIR}/knowledge/manifest.json",
        "budgets": {"user_core_bytes": 7000, "project_core_bytes": 7000, "unscoped_rules_bytes": 2000,
                    "memory_index_bytes": 4000, "memory_index_lines": 60},
    }


def validate(doc):
    """Problems of a configuration document against C01 (empty when sound)."""
    return contract.validate_instance("C01", doc, _schema())


def load(config_arg=None, project_root=None, env=None):
    """Resolve, read, validate and expand the configuration. Raises ConfigError with every problem."""
    e = _env(env)
    found = find_config(config_arg, project_root, e)
    if found is None:
        return Resolved(default_config(e), "defaults")
    source, path = found
    try:
        doc = contract.loads_strict(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ConfigError(f"{path.as_posix()}: invalid JSON ({exc})") from exc
    problems = validate(doc)
    if problems:
        raise ConfigError(f"{path.as_posix()} does not satisfy C01: " + "; ".join(problems))
    missing = []
    out = _expand_tree(doc, e, missing)
    home = home_dir(e)
    for name in ROOT_NAMES:
        if _VAR.search(out["roots"][name]):
            out["roots"][name] = str(home / name)
            missing = [m for m in missing if m not in _vars_of(doc["roots"][name])]
    return Resolved(out, source, path, sorted(set(missing)))


def _vars_of(text):
    return {m.group(1) or m.group(2) for m in _VAR.finditer(text)}
