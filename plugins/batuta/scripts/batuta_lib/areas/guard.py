"""Area `guard`: the guardrails as PreToolUse hook handlers, each with a script and a CI twin.

Handlers (C31): `guard-automation`, `guard-locked-tests`, `guard-approvals`, `guard-secrets`, `guard-destructive`,
`guard-require-brief`; the launcher `scripts/hook.py <id>` calls `handler(payload)` and prints the decision. A deny or
an ask is a C16 PreToolUse output with exit code 0; an allow has no output.

Command line:
    guard <name> --payload FILE [--explain]   run one guard on a payload file and print the decision
    guard scan --diff RANGE [--root DIR]      run the automation and destructive packs over the added lines of a diff
                                              (settings from the base revision; nothing is exempt silently)
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from pathlib import Path

from batuta_lib.guards import approvals, automation, destructive, locked_tests, project_root, require_brief, secrets, string_list
from batuta_lib.output import emit, item

AREA = "guard"
HELP = "Guardrails as hook handlers: automation, locked tests, approvals, secrets, destructive commands, briefs."

GUARDS = {"automation": automation, "locked-tests": locked_tests, "approvals": approvals, "secrets": secrets,
          "destructive": destructive, "require-brief": require_brief}
DEFAULT_SCAN_IGNORE = ["**/*.md"]      # the shipped default; a base-revision `guards.scan_ignore` replaces it
SCAN_MARKER = re.compile(r"batuta-guard:\s*ignore\s+([\w,\s-]+)")
CONFIG_PATH = ".batuta/batuta.json"
SECURITY_KEY = re.compile(r"\"(guards|tdd|lock_file|require_brief|secret_globs|protected_branches|destructive_disable|scan_ignore)\"")
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


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ValueError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def _git_diff(root: Path, rng: str) -> str:
    if rng.startswith("-") or not rng.strip():
        raise ValueError(f"the range {rng!r} is not a git revision range (it must not start with '-')")
    return _git(root, "diff", "--unified=0", "--no-color", "--no-ext-diff", rng, "--")


def base_revision(root: Path, rng: str) -> str:
    """The revision the configuration is read from: the left side of `A..B` or `A...B`, else the revision itself."""
    left = re.split(r"\.{2,3}", rng, maxsplit=1)[0] or "HEAD"
    return left


def base_guard_settings(root: Path, rng: str) -> dict:
    """The `guards` section of `.batuta/batuta.json` as it was at the base revision ({} when absent or unreadable): the
    change under review cannot change the rules it is reviewed with."""
    try:
        text = _git(root, "show", f"{base_revision(root, rng)}:{CONFIG_PATH}")
        doc = json.loads(text)
    except (ValueError, OSError):
        return {}
    value = doc.get("guards") if isinstance(doc, dict) else None
    return value if isinstance(value, dict) else {}


def parse_diff(diff: str) -> dict[str, dict]:
    """{file: {"added": [(line number, text)], "removed": [text]}} of a unified diff."""
    files: dict[str, dict] = {}
    current, number = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            current = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            if current is not None:
                files.setdefault(current, {"added": [], "removed": []})
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            number = int(match.group(1)) if match else 0
        elif current is not None and line.startswith("+"):
            files[current]["added"].append((number, line[1:]))
            number += 1
        elif current is not None and line.startswith("-"):
            files[current]["removed"].append(line[1:])
    return files


def added_lines(diff: str) -> dict[str, list[tuple[int, str]]]:
    """{file: [(line number, text)]} of the lines a unified diff adds."""
    return {path: info["added"] for path, info in parse_diff(diff).items()}


def _ignored(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, p) or (p.startswith("**/") and fnmatch.fnmatchcase(path, p[3:])) for p in patterns)


def _marker_ids(text: str) -> set[str]:
    match = SCAN_MARKER.search(text)
    return {i for i in re.split(r"[\s,]+", match.group(1).strip()) if i} if match else set()


def line_hits(text: str, protected: list[str], disabled: set[str]) -> list[tuple[str, str]]:
    """(rule id, reason) for one added line: the automation rules and the destructive packs."""
    seen: dict[str, str] = {}
    for candidate in (text, YAML_PREFIX.sub("", text)):
        for rid, why in automation.scan_hits(candidate):
            if rid != automation.LOOP_ID:
                seen.setdefault(rid, why)
        for pack, why in destructive.scan_text(candidate, protected, disabled):
            seen.setdefault(pack, f"[{pack}] {why}")
    return list(seen.items())


def scan_added(files: dict, ignore: list[str], protected: list[str], disabled: set[str]) -> list[tuple[str, str, int, str, str]]:
    """(status, file, line, rule id, reason) for every hit on an added line. Status `fail` is a hit nothing excuses,
    `ignored` a hit in a file excluded by `guards.scan_ignore`, `marker` a hit excused by an inline marker that names
    its rule id. Nothing is dropped silently."""
    hits: list[tuple[str, str, int, str, str]] = []
    for path, lines in files.items():
        file_ignored = _ignored(path, ignore)
        for number, text in lines:
            marked = _marker_ids(text)
            for rid, why in line_hits(text, protected, disabled):
                status = "ignored" if file_ignored else "marker" if rid in marked else "fail"
                hits.append((status, path, number, rid, why))
        suffix = Path(path).suffix.lower()
        if (suffix in SHELLISH or Path(path).name == "Makefile") and lines:
            joined = "\n".join(t for _, t in lines)
            if automation.LOOP_ID in {rid for rid, _ in automation.scan_hits(joined)}:
                first = next((n for n, t in lines if automation.LOOP.search(t)), lines[0][0])
                marked = set().union(*(_marker_ids(t) for _, t in lines))
                status = "ignored" if file_ignored else "marker" if automation.LOOP_ID in marked else "fail"
                hits.append((status, path, first, automation.LOOP_ID, automation.LOOP_WHY))
    return hits


def config_changes(files: dict) -> list[str]:
    """Files of the diff that touch the security keys of `.batuta/batuta.json`."""
    out = []
    for path, info in files.items():
        if path.endswith(CONFIG_PATH):
            texts = [t for _, t in info["added"]] + info["removed"]
            if any(SECURITY_KEY.search(t) for t in texts):
                out.append(path)
    return out


def _scan(args) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        files = parse_diff(_git_diff(root, args.diff))
    except (OSError, ValueError) as exc:
        return emit(AREA, "scan", [item("FAIL", str(exc))], "guard scan: cannot read the diff", _wants_json(args))
    settings = base_guard_settings(root, args.diff)
    ignore = string_list(settings.get("scan_ignore"), DEFAULT_SCAN_IGNORE) if "scan_ignore" in settings else list(DEFAULT_SCAN_IGNORE)
    protected = destructive.DEFAULT_PROTECTED + string_list(settings.get("protected_branches"))
    disabled = set(string_list(settings.get("destructive_disable")))
    hits = scan_added({p: i["added"] for p, i in files.items()}, ignore, protected, disabled)
    items = []
    for status, path, line, rid, why in hits:
        if status == "fail":
            items.append(item("FAIL", f"{why} [{rid}]", f"{path}:{line}"))
        elif status == "ignored":
            items.append(item("WARN", f"ignored by guards.scan_ignore: {why} [{rid}]", f"{path}:{line}"))
        else:
            items.append(item("WARN", f"excused by an inline marker naming {rid}: {why}", f"{path}:{line}"))
    for path in config_changes(files):
        items.append(item("WARN", "the security settings of the harness changed (guards.*, tdd.lock_file): review them by hand", path))
    fails = sum(1 for h in hits if h[0] == "fail")
    ignored = sum(1 for h in hits if h[0] == "ignored")
    marked = sum(1 for h in hits if h[0] == "marker")
    if not items:
        total = sum(len(i["added"]) for i in files.values())
        return emit(AREA, "scan", [item("OK", f"no unattended-automation or destructive command in {total} added line(s)")],
                    "guard scan: clean", _wants_json(args))
    summary = f"guard scan: {fails} hit(s), {ignored} ignored hit(s), {marked} marker-excused hit(s)"
    return emit(AREA, "scan", items, summary, _wants_json(args))


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
    scan.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    scan.set_defaults(func=_scan)
