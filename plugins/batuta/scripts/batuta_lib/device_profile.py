"""Device profile (C15): where this device keeps Batuta, resolved from configuration and environment, never from a
path written in a shipped file.

Resolution of the deploy root: the `--deploy-root` flag, then `BATUTA_HOME`, then `~/.batuta`. The other roots come
from the C01 `roots` (`temp`, `data`, `worktrees`, and the optional `models`), already `$VAR`-expanded by
`batuta_lib.config`, falling back to `<BATUTA_HOME>/temp|data|worktrees|models`. Every root is validated after
expansion (decision 9): absolute, not a drive or filesystem root, not inside a repository, not the home folder or
`~/.claude`, and on a drive that exists. The profile is written to `<deploy root>/device.json` and validated as C15.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from batuta_lib import config, contract, render

PROFILE_FILE = "device.json"
ROOT_KEYS = {"temp": "temp_root", "data": "data_root", "models": "models_root", "worktrees": "worktrees_root"}


class ProfileError(ValueError):
    """A root or the profile cannot be used; the message says why and what to change."""


def deploy_root(flag=None, env=None):
    """The device copy's folder: `--deploy-root`, else `BATUTA_HOME`, else `~/.batuta` (expanded, not yet validated)."""
    if flag:
        text, missing = config.expand(str(flag), env)
        if missing:
            raise ProfileError(f"--deploy-root uses the environment variable {missing[0]}, which is not set")
        return Path(text)
    return config.home_dir(env)


def repository_of(path):
    """The nearest folder at or above `path` that holds a `.git` entry (a repository or worktree root), else None."""
    p = Path(os.path.abspath(path))
    for folder in [p, *p.parents]:
        try:
            if (folder / ".git").exists():
                return folder
        except OSError:
            continue
    return None


def _inside(child, parent):
    c = [os.path.normcase(x) for x in child.parts]
    p = [os.path.normcase(x) for x in parent.parts]
    return c[:len(p)] == p


def validate_root(path, label, home=None, exists=os.path.exists):
    """The normalised absolute folder for `path`, or ProfileError. `exists` is injectable for the drive test."""
    text = str(path)
    if not text.strip():
        raise ProfileError(f"{label} is empty; set it in batuta.json or its environment variable")
    raw = Path(text)
    if not raw.is_absolute():
        raise ProfileError(f"{label} {text!r} must be an absolute path (after $VAR expansion); set it in batuta.json "
                           f"roots or through its environment variable")
    folder = Path(os.path.abspath(text))
    if folder.parent == folder:
        raise ProfileError(f"{label} {folder.as_posix()} is a drive or filesystem root; use a folder on it")
    if folder.anchor and not exists(folder.anchor):
        raise ProfileError(f"{label} {folder.as_posix()} is on a drive or mount that is not available "
                           f"({folder.anchor}); set the root to a folder that exists on this device")
    repo = repository_of(folder)
    if repo is not None:
        raise ProfileError(f"{label} {folder.as_posix()} is inside the repository {repo.as_posix()}; "
                           f"device state never lives in a repository")
    home = Path(os.path.abspath(home if home is not None else Path.home()))
    claude = home / ".claude"
    if folder == home or _inside(home, folder) or _inside(folder, claude):
        raise ProfileError(f"{label} {folder.as_posix()} is, contains or sits inside the home folder or ~/.claude")
    return folder


def resolve_roots(cfg, env=None, home=None, exists=os.path.exists):
    """{temp_root, data_root, models_root, worktrees_root} as validated folders, from a loaded C01 configuration."""
    roots = cfg.get("roots") or {}
    base = config.home_dir(env)
    out = {}
    for name, key in ROOT_KEYS.items():
        value = roots.get(name) or str(base / name)
        out[key] = validate_root(value, f"root '{name}'", home, exists)
    return out


def build_profile(deploy, roots, python, batuta_version, deployed_from=None):
    """The C15 document for this device (validated; ProfileError when it is not sound)."""
    doc = {"contract_version": "1.0", "python": Path(python).as_posix(), "deploy_root": Path(deploy).as_posix(),
           **{k: Path(v).as_posix() for k, v in roots.items()}, "batuta_version": batuta_version}
    if deployed_from:
        doc["deployed_from"] = Path(deployed_from).as_posix()
    problems = validate_profile(doc)
    if problems:
        raise ProfileError("the device profile does not satisfy C15: " + "; ".join(problems))
    return doc


def validate_profile(doc):
    """Problems of a profile document against C15 (empty when sound)."""
    sp = contract.find_schema(config.contracts_dir(), "C15")
    if sp is None:
        raise ProfileError(f"the C15 schema is not found in {config.contracts_dir()}")
    return contract.validate_instance("C15", doc, contract.load_schema(sp))


def profile_text(doc):
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def write_profile(deploy, doc):
    render.write_atomic(Path(deploy) / PROFILE_FILE, profile_text(doc))


def read_profile(deploy):
    """The validated profile in `<deploy>/device.json`; ProfileError when it is absent, unreadable or not C15."""
    path = Path(deploy) / PROFILE_FILE
    if not path.is_file():
        raise ProfileError(f"{path.as_posix()} not found; run `device deploy --apply` first")
    try:
        doc = contract.loads_strict(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ProfileError(f"{path.as_posix()} cannot be read ({exc})") from exc
    problems = validate_profile(doc)
    if problems:
        raise ProfileError(f"{path.as_posix()} does not satisfy C15: " + "; ".join(problems))
    return doc


def render_values(profile):
    """The placeholder values a template may use: the interpreter and the device roots from the profile."""
    return {"python": profile["python"], "deploy_root": profile["deploy_root"], "temp_root": profile["temp_root"],
            "data_root": profile["data_root"], "models_root": profile["models_root"],
            "worktrees_root": profile["worktrees_root"]}
