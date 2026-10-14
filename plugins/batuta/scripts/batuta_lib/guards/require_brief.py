"""Guard `require-brief`: an Agent (or Task) launch must name a brief that satisfies C02.

Every launch is checked: the prompt must name at least one path ending in `.brief.md` (absolute, or relative to the
working directory), each file must exist and satisfy the brief contract C02. A `searcher` or `runner` launch (a quick
lookup or run) may go without a brief when the prompt ends with a `BRIEF: none` line. The answer on a failure is
`deny` (default) or `ask`, from `guards.require_brief` in batuta.json (`deny`, `ask` or `off`; anything else is
`deny`). Other tools are never inspected.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import allow, ask, deny, guard_config, project_root, section, tool_input, tool_name

NAME = "require-brief"
LAUNCH_TOOLS = ("Agent", "Task")
QUICK_AGENTS = ("searcher", "runner")
MODES = ("deny", "ask", "off")
BRIEF_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\.{0,2}[\\/])?[^\s\"'`<>|*?]*?\.brief\.md(?!\w)")
BRIEF_NONE = re.compile(r"^\s*BRIEF:\s*none\s*$", re.IGNORECASE)
EXPLAIN = [
    "Every Agent or Task launch must name a path ending in .brief.md whose file satisfies the brief contract (C02).",
    "A searcher or runner launch may go without a brief when the last line of its prompt is `BRIEF: none`.",
    "Mode: guards.require_brief in batuta.json: deny (default), ask or off.",
]


def state(root: Path) -> str:
    return f"mode: {mode(root)}"


def mode(root: Path) -> str:
    value = section(guard_config(root), "guards").get("require_brief", "deny")
    return value if value in MODES else "deny"


def last_line(prompt: str) -> bool:
    """Does the prompt end with a `BRIEF: none` line (the last non-empty line, nothing after it)?"""
    lines = [ln for ln in prompt.splitlines() if ln.strip()]
    return bool(lines) and bool(BRIEF_NONE.match(lines[-1]))


def brief_paths(prompt: str) -> list[str]:
    seen: list[str] = []
    for match in BRIEF_PATH.finditer(prompt):
        if match.group(0) not in seen:
            seen.append(match.group(0))
    return seen


def _problem(payload, root: Path) -> str | None:
    from batuta_lib import config, contract
    info = tool_input(payload)
    prompt = info.get("prompt") if isinstance(info.get("prompt"), str) else ""
    agent = str(info.get("subagent_type") or "")
    paths = brief_paths(prompt)
    if not paths:
        if agent in QUICK_AGENTS and last_line(prompt):
            return None
        return ("launch refused: the prompt names no path ending in .brief.md (write a brief, check it with "
                "`batuta.py contract validate C02 <file>` and name its path in the prompt); only a searcher or runner "
                "launch whose last line is `BRIEF: none` may go without one")
    base = Path(payload["cwd"]) if isinstance(payload.get("cwd"), str) and payload["cwd"] else root
    schema = contract.find_schema(config.contracts_dir(), "C02")
    for raw in paths:
        path = Path(raw)
        path = path if path.is_absolute() else base / path
        if not path.is_file():
            return f"launch refused: the brief {raw} was not found"
        errors = contract.validate_file(path, schema, "C02")
        if errors:
            return f"launch refused: the brief {raw} does not satisfy C02: {'; '.join(errors[:3])}"
    return None


def decide(payload) -> dict:
    if tool_name(payload) not in LAUNCH_TOOLS:
        return allow()
    root = project_root(payload)
    chosen = mode(root)
    if chosen == "off":
        return allow()
    problem = _problem(payload, root)
    if problem is None:
        return allow()
    return (ask if chosen == "ask" else deny)("guard-require-brief: " + problem)
