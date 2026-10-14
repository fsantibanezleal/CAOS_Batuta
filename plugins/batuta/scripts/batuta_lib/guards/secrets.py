"""Guard `secrets`: files that match the secret globs are never read by an agent.

Covers the Read tool, Grep and Glob paths and shell reads (cat, type, head, grep, Get-Content, source, cp, curl @file,
`<` redirects, inline interpreter reads). The defaults cover environment files, private keys and certificates, cloud
and package-registry credentials; `guards.secret_globs` in batuta.json adds more. Templates (`.env.example` and the
like) and public keys are allowed.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from . import allow, command_of, deny, file_path_of, guard_config, norm_path, project_root, section, shell, string_list, \
    tool_input, tool_name
from . import text as textlib

NAME = "secrets"
DEFAULT_GLOBS = [
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa", "id_rsa.*", "id_dsa", "id_dsa.*", "id_ecdsa",
    "id_ecdsa.*", "id_ed25519", "id_ed25519.*", "credentials", "credentials.*", ".npmrc", ".pypirc", ".netrc",
    ".git-credentials", "secrets/**", ".ssh/**",
]
ALLOW_GLOBS = ["*.example", "*.sample", "*.template", "*.dist", "*.pub"]
READ_WORDS = re.compile(r"open\(|read|load|\bcat\b|\btype\b|get-content|fopen|slurp")
INTERPRETERS = {"python", "python3", "py", "node", "nodejs", "deno", "bun", "ruby", "perl", "php", "powershell", "pwsh"}
EXPLAIN = [
    "Denies reads of files that match the secret globs (Read, Grep and Glob paths, shell reads, inline interpreter reads).",
    "Default globs: " + ", ".join(DEFAULT_GLOBS),
    "Allowed templates and public keys: " + ", ".join(ALLOW_GLOBS),
    "Add globs with guards.secret_globs in batuta.json (a list of strings); a broken configuration keeps the defaults.",
]


def state(root: Path) -> str:
    extra = string_list(section(guard_config(root), "guards").get("secret_globs"))
    return f"{len(DEFAULT_GLOBS)} default globs and {len(extra)} configured"


def match(path: str, globs: list[str]) -> str | None:
    """The glob that marks `path` (already normalized) as secret, None when none does or it is a template or public key."""
    if not path:
        return None
    parts = [p for p in path.split("/") if p and p not in (".", "..")]
    if not parts:
        return None
    base = parts[-1]
    if any(fnmatch.fnmatchcase(base, a) for a in ALLOW_GLOBS):
        return None
    for glob in globs:
        g = glob.lower()
        if g.endswith("/**"):
            if g[:-3] in parts:
                return glob
        elif "/" in g:
            if fnmatch.fnmatchcase(path, g) or fnmatch.fnmatchcase(path, "*/" + g):
                return glob
        elif fnmatch.fnmatchcase(base, g):
            return glob
    return None


def _globs(root: Path) -> list[str]:
    return DEFAULT_GLOBS + string_list(section(guard_config(root), "guards").get("secret_globs"))


def _deny(token: str, glob: str) -> dict:
    return deny(f"BLOCKED by guard-secrets: {token} matches the secret glob '{glob}'. Do not read credential files; "
                "ask the user for the value, or use the name of the environment variable that holds it.")


def decide(payload) -> dict:
    name = tool_name(payload)
    root = project_root(payload)
    candidates: list[str] = []
    command = command_of(payload)
    if command:
        normal = textlib.normalize(command)
        candidates = shell.read_targets_of(normal)
        flat = normal.lower()
        segs = shell.all_segments(normal)
        if any(shell.command_name(s) in INTERPRETERS for s in segs) and READ_WORDS.search(flat):
            for text in [flat] + [t.lower() for t in textlib.nested_texts(normal)]:
                candidates += [w for w in re.split(r"[\s'\"(),;=]+", text) if w]
    elif name in ("Read", "NotebookRead"):
        candidates = [file_path_of(payload)]
    elif name in ("Grep", "Glob"):
        value = tool_input(payload).get("path")
        candidates = [value] if isinstance(value, str) else []
    if not candidates:
        return allow()
    globs = _globs(root)
    for token in candidates:
        glob = match(norm_path(token, root), globs)
        if glob:
            return _deny(token, glob)
    return allow()
