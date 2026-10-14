"""Area `guard`: the guardrails as PreToolUse hook handlers, each with a script and a CI twin.

Handlers (C31): `guard-automation`, `guard-locked-tests`, `guard-approvals`, `guard-secrets`, `guard-destructive`,
`guard-require-brief`; the launcher `scripts/hook.py <id>` calls `handler(payload)` and prints the decision. A deny or
an ask is a C16 PreToolUse output with exit code 0; an allow has no output.

Command line:
    guard <name> --payload FILE [--explain]   run one guard on a payload file and print the decision
    guard scan --diff RANGE [--root DIR]      run the automation and destructive packs over the added lines of a diff
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from pathlib import Path

from batuta_lib.guards import (approvals, automation, destructive, guard_config, locked_tests, project_root,
                               require_brief, secrets, section, string_list)
from batuta_lib.output import emit, item

AREA = "guard"
HELP = "Guardrails as hook handlers: automation, locked tests, approvals, secrets, destructive commands, briefs."

GUARDS = {"automation": automation, "locked-tests": locked_tests, "approvals": approvals, "secrets": secrets,
          "destructive": destructive, "require-brief": require_brief}
DEFAULT_SCAN_IGNORE = ["tests/**", "plugins/batuta/scripts/batuta_lib/guards/**", "docs/reference/enforcement-matrix.md"]
SCAN_MARKER = "batuta-guard: ignore"
SHELLISH = {".sh", ".ps1", ".bat", ".cmd", ".yml", ".yaml"}
YAML_PREFIX = re.compile(r"^\s*(-\s+)?([\w.-]+:\s+)?(\|\s*)?")


def handle_automation(payload):
    return automation.decide(payload)


def handle_locked_tests(payload):
    return locked_tests.decide(payload)


def handle_approvals(payload):
    return approvals.decide(payload)


def handle_secrets(payload):
    return secrets.decide(payload)


def handle_destructive(payload):
    return destructive.decide(payload)


def handle_require_brief(payload):
    return require_brief.decide(payload)


HOOKS = {
    "guard-automation": handle_automation,
    "guard-locked-tests": handle_locked_tests,
    "guard-approvals": handle_approvals,
    "guard-secrets": handle_secrets,
    "guard-destructive": handle_destructive,
    "guard-require-brief": handle_require_brief,
}


def explain(name: str, cwd=None) -> str:
    """What a guard checks and what it does with the data it finds (or does not find) in `cwd`."""
    module = GUARDS[name]
    root = project_root({"cwd": str(cwd)} if cwd else {})
    lines = [f"guard {name} (hook handler guard-{name})", *module.EXPLAIN]
    if hasattr(module, "state"):
        lines.append("state: " + module.state(root))
    return "\n".join(lines)


def _wants_json(args) -> bool:
    return bool(getattr(args, "json", False))


def _run_guard(name: str, args) -> int:
    verb = name
    if args.explain:
        items = [item("OK", line) for line in explain(name, Path.cwd()).splitlines()]
        return emit(AREA, verb, items, f"guard {name}: explanation", _wants_json(args))
    if not args.payload:
        return emit(AREA, verb, [item("FAIL", "--payload FILE is required (or --explain)")], "guard: no payload",
                    _wants_json(args))
    path = Path(args.payload)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("the payload must be a JSON object")
        result = HOOKS[f"guard-{name}"](payload)
    except (OSError, ValueError) as exc:  # ConfigError is a ValueError
        return emit(AREA, verb, [item("FAIL", f"cannot run guard {name}: {exc}", path.as_posix())],
                    f"guard {name}: failed", _wants_json(args))
    output = result.get("output")
    if output is None:
        items, summary = [item("OK", f"allow ({name})")], f"guard {name}: allow"
    else:
        spec = output["hookSpecificOutput"]
        tag = "REFUSED" if spec["permissionDecision"] == "deny" else "WARN"
        items, summary = [item(tag, spec["permissionDecisionReason"])], f"guard {name}: {spec['permissionDecision']}"
    return emit(AREA, verb, items, summary, _wants_json(args))


def _git_diff(root: Path, rng: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), "diff", "--unified=0", "--no-color", "--no-ext-diff", rng],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ValueError(f"git diff {rng} failed: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def added_lines(diff: str) -> dict[str, list[tuple[int, str]]]:
    """{file: [(line number, text)]} of the lines a unified diff adds."""
    files: dict[str, list[tuple[int, str]]] = {}
    current, number = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            current = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            if current is not None:
                files.setdefault(current, [])
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            number = int(match.group(1)) if match else 0
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            files[current].append((number, line[1:]))
            number += 1
    return files


def scan_added(files: dict, ignore: list[str], protected: list[str], disabled: set[str]) -> list[tuple[str, int, str]]:
    """(file, line, reason) for every added line the automation or destructive packs refuse."""
    hits: list[tuple[str, int, str]] = []
    for path, lines in files.items():
        if path.endswith(".md") or any(fnmatch.fnmatchcase(path, pat) for pat in ignore):
            continue
        live = [(n, t) for n, t in lines if SCAN_MARKER not in t]
        for number, text in live:
            seen = set()
            for candidate in (text, YAML_PREFIX.sub("", text)):
                for why in automation.scan_text(candidate):
                    if why != automation.LOOP_WHY and why not in seen:
                        seen.add(why)
                        hits.append((path, number, why))
                for pack, why in destructive.scan_text(candidate, protected, disabled):
                    if pack not in seen:
                        seen.add(pack)
                        hits.append((path, number, f"[{pack}] {why}"))
        suffix = Path(path).suffix.lower()
        if (suffix in SHELLISH or Path(path).name == "Makefile") and live:
            joined = "\n".join(t for _, t in live)
            if automation.LOOP_WHY in automation.scan_text(joined):
                first = next((n for n, t in live if automation.LOOP.search(t)), live[0][0])
                hits.append((path, first, automation.LOOP_WHY))
    return hits


def _scan(args) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        files = added_lines(_git_diff(root, args.diff))
    except (OSError, ValueError) as exc:
        return emit(AREA, "scan", [item("FAIL", str(exc))], "guard scan: cannot read the diff", _wants_json(args))
    cfg = guard_config(project_root({"cwd": str(root)}))
    guards_cfg = section(cfg, "guards")
    ignore = DEFAULT_SCAN_IGNORE + string_list(guards_cfg.get("scan_ignore")) + list(args.ignore or [])
    protected, disabled = destructive.settings(project_root({"cwd": str(root)}))
    hits = scan_added(files, ignore, protected, disabled)
    if not hits:
        total = sum(len(v) for v in files.values())
        return emit(AREA, "scan", [item("OK", f"no unattended-automation or destructive command in {total} added line(s)")],
                    "guard scan: clean", _wants_json(args))
    items = [item("FAIL", why, f"{path}:{line}") for path, line, why in hits]
    return emit(AREA, "scan", items, f"guard scan: {len(hits)} hit(s)", _wants_json(args))


def register(subparsers) -> None:
    for name in GUARDS:
        parser = subparsers.add_parser(name, help=f"run guard {name} on a payload file")
        parser.add_argument("--payload", metavar="FILE", help="a C16 PreToolUse payload (JSON file)")
        parser.add_argument("--explain", action="store_true", help="say what the guard checks and what it found")
        parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
        parser.set_defaults(func=lambda args, n=name: _run_guard(n, args))
    scan = subparsers.add_parser("scan", help="CI twin: scan the added lines of a git diff")
    scan.add_argument("--diff", metavar="RANGE", required=True, help="git revision range, for example origin/develop..HEAD")
    scan.add_argument("--root", metavar="DIR", help="repository folder (default: the current folder)")
    scan.add_argument("--ignore", metavar="GLOB", action="append", help="skip files matching the glob (repeatable)")
    scan.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    scan.set_defaults(func=_scan)
