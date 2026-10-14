#!/usr/bin/env python3
"""The one hook launcher (contract C31): `hook.py <handler id>`.

Reads the C16 payload of the event on stdin, finds the handler `<id>` in the area modules under
`batuta_lib/areas/` (a literal `HOOKS = {id: handler}`, read with `ast` without importing; only the module that
defines the id is imported), calls `handler(payload)`, checks the handler result and then prints `output` as JSON on
stdout, writes `message` to stderr and exits with `exit_code` (0, or 2 to block).

An unknown id, an id defined twice, a module that fails to import, an exception, an invalid result or a field over
the official 10,000-character cap writes the reason to stderr and exits 1, which Claude Code treats as a
non-blocking error: the launcher itself fails open. A guard that must block when it cannot decide is wired with
`onFailure: "block"` in hooks.json; that choice is never made here.

Standard library only; writes no bytecode.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
AREAS_DIR = HERE / "batuta_lib" / "areas"
HOOK_ID = re.compile(r"[a-z][a-z0-9-]*")
OUTPUT_CAP = 10000  # the official cap on hook output (characters)
RESULT_KEYS = {"contract_version", "exit_code", "output", "message"}
DECISIONS = {"allow", "deny", "ask"}


def discover(areas_dir: Path):
    """({id: [module names]}, problems): the literal `HOOKS` dicts of the area modules, read without importing."""
    found: dict[str, list[str]] = {}
    problems: list[str] = []
    for path in sorted(Path(areas_dir).glob("*.py")):
        try:
            source = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            problems.append(f"{path.stem}: cannot read ({exc})")
            continue
        if "HOOKS" not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            problems.append(f"{path.stem}: cannot parse ({exc.msg})")
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            else:
                continue
            if "HOOKS" in targets and isinstance(node.value, ast.Dict):
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        found.setdefault(key.value, []).append(path.stem)
    return found, problems


def validate_result(result) -> list[str]:
    """Problems of a handler result against C31 `handler_result` (empty when sound); light, no schema load."""
    if not isinstance(result, dict):
        return [f"the handler result must be an object, not {type(result).__name__}"]
    problems = [f"unknown key '{k}' in the handler result" for k in sorted(set(result) - RESULT_KEYS)]
    if result.get("contract_version") != "1.0":
        problems.append("contract_version must be '1.0'")
    code = result.get("exit_code")
    if isinstance(code, bool) or code not in (0, 2):
        problems.append("exit_code must be 0 or 2")
    output = result.get("output")
    if output is not None:
        problems.extend(_output_problems(output))
    message = result.get("message")
    if message is not None and not isinstance(message, str):
        problems.append("message must be a string")
    if code == 2 and not (isinstance(message, str) and message.strip()):
        problems.append("exit code 2 blocks and states why in message (a non-blank text)")
    return problems


def _output_problems(output) -> list[str]:
    """The output must be a C16 object: a block (decision and reason), a PreToolUse decision or a SessionStart context."""
    if not isinstance(output, dict):
        return ["output must be an object or null"]
    if "decision" in output:
        if output.get("decision") != "block" or not (isinstance(output.get("reason"), str) and output["reason"]):
            return ["output: a block needs decision 'block' and a non-empty reason"]
        if len(output["reason"]) > OUTPUT_CAP:
            return [f"output: the block reason must be at most {OUTPUT_CAP} characters"]
        return []
    spec = output.get("hookSpecificOutput")
    if not isinstance(spec, dict):
        return ["output is not a C16 output (no 'decision' and no 'hookSpecificOutput')"]
    name = spec.get("hookEventName")
    if name == "PreToolUse":
        reason = spec.get("permissionDecisionReason")
        if spec.get("permissionDecision") not in DECISIONS or not isinstance(reason, str):
            return ["output: a PreToolUse output needs permissionDecision (allow, deny or ask) and permissionDecisionReason"]
        if len(reason) > OUTPUT_CAP:
            return [f"output: permissionDecisionReason must be at most {OUTPUT_CAP} characters"]
        return []
    if name == "SessionStart":
        context = spec.get("additionalContext")
        if not isinstance(context, str) or len(context) > OUTPUT_CAP:
            return [f"output: SessionStart additionalContext must be a string of at most {OUTPUT_CAP} characters"]
        return []
    return ["output: hookEventName must be PreToolUse or SessionStart"]


def _load(module_name: str, areas_dir: Path):
    scripts = str(areas_dir.parent.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(f"batuta_hook_area_{module_name}", areas_dir / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(stream, text: str) -> None:
    stream.write(text)
    stream.flush()


def run(hook_id: str, stdin_text: str, stdout, stderr, areas_dir: Path | None = None) -> int:
    """Run one handler; returns the exit code (0, 1 or 2). Never raises."""
    areas_dir = Path(areas_dir) if areas_dir else AREAS_DIR

    def fail(reason: str) -> int:
        _write(stderr, f"hook {hook_id or '?'}: {reason}\n")
        return 1

    try:
        if not isinstance(hook_id, str) or not HOOK_ID.fullmatch(hook_id):
            return fail("a handler id is required (lowercase letters, digits and hyphens)")
        text = stdin_text.lstrip("﻿")
        payload = json.loads(text) if text.strip() else {}
        if not isinstance(payload, dict):
            return fail("the payload on stdin must be a JSON object")
        found, _problems = discover(areas_dir)
        modules = found.get(hook_id)
        if not modules:
            return fail(f"unknown handler id '{hook_id}' (no area module defines it)")
        if len(modules) > 1:
            return fail(f"handler id '{hook_id}' is defined twice (in {', '.join(modules)})")
        # a handler's stray prints go to stderr: stdout carries exactly one JSON decision (or nothing)
        with contextlib.redirect_stdout(stderr):
            module = _load(modules[0], areas_dir)
            handler = getattr(module, "HOOKS", {}).get(hook_id)
            if not callable(handler):
                return fail(f"handler '{hook_id}' in {modules[0]} is not callable")
            result = handler(payload)
        problems = validate_result(result)
        if problems:
            return fail("invalid handler result: " + "; ".join(problems))
        printed = ""
        if result.get("output") is not None:
            printed = json.dumps(result["output"])
        if printed:
            _write(stdout, printed + "\n")
        if result["exit_code"] == 2:
            _write(stderr, result["message"].rstrip() + "\n")
        return result["exit_code"]
    except json.JSONDecodeError as exc:
        return fail(f"the payload on stdin is not valid JSON ({exc.msg})")
    except BaseException as exc:  # noqa: BLE001 (SystemExit and KeyboardInterrupt included: always a non-blocking error)
        return fail(f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    hook_id = argv[0] if len(argv) == 1 else ""
    try:
        data = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        data = ""
    return run(hook_id, data, sys.stdout, sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
