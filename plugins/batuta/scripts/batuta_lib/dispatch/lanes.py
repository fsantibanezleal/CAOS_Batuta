"""The dispatch lanes (plan section 3.5): the subagent launch specification, the tool-less provider call and the Claude Agent
SDK session with its PreToolUse policy.

Nothing here detaches a process or outlives the run: a provider call is one bounded request loop, an SDK session runs inside
`asyncio.run` under a monotonic deadline, and a guard runs as a short subprocess that is waited for.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from batuta_lib import delegation
from batuta_lib.dispatch import adapters, prices
from batuta_lib.dispatch import transport as tr
from batuta_lib.dispatch.redact import redact

MAX_RESUMES = 3                 # resumes of one session after an API error or a crash, then BLOCKED
MAX_FIX_ROUNDS = 2              # times the failure of a check goes back to the agent
DEFAULT_MAX_OUT = 16000         # output tokens a provider call may ask for when the cap allows it
UNPRICED_MAX_OUT = 4096
MIN_OUT = 256                   # below this the cap buys no useful answer: the run stops before sending
GUARD_TIMEOUT = 30
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
DEFAULT_GUARDS = ("guard-automation", "guard-locked-tests", "guard-approvals", "guard-secrets", "guard-destructive")
TOOL_LESS_BLOCKED_KINDS = ("implement", "job", "skeleton", "run")   # kinds that need tools: refused on a provider lane
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)

PROVIDER_SYSTEM = """You are executing a delegated brief WITHOUT tools: you cannot read files, run commands or write files.
Work only from the brief below. Reply with the complete report in Markdown, following the report layout of the brief
(a short summary, one section per deliverable, and a Completeness table with one row per deliverable: DONE, PARTIAL or
BLOCKED, with evidence). Never claim to have run a command or read a file you were not given: mark such items UNVERIFIED
or BLOCKED. If code or documents must change, give the change as ONE unified diff in a fenced code block that starts with
```diff, using paths relative to the project root and touching only these paths: {scope}. The diff is applied by a person
after the gates, not by you."""

SDK_FOOTER = """

## Working rules for this run (the dispatcher enforces some of them)
- You run unattended through the API: nobody answers questions. Decide, act, and record decisions in your report.
- Keep the report file named in the brief current as you go; the run can be interrupted and resumed from your files.
- Never push to a shared branch, never merge, never touch credentials. Say in the report what the main session must do.
- When completely done, end with a message that starts with `DONE:`; if you cannot finish, start it with `BLOCKED:` and the reason.
"""


# ------------------------------------------------------------------ subagent lane


def subagent_spec(request):
    """The exact launch specification for the main session. The CLI cannot launch a Claude Code subagent itself."""
    prompt = (f"Your brief is the file {request['brief']}. Read it in full first; it is your complete instruction set. "
              f"Write your report to {request['report']} and finish with the report layout the brief sets.")
    return {"lane": "subagent", "tool": "Agent", "subagent_type": request["role"], "model": request["model"],
            "description": f"Run the brief {request['run_id']}", "prompt": prompt, "run_in_background": True,
            "launched": False,
            "note": "Nothing was launched: the main session starts this subagent with the Agent tool, in the background, "
                    "and checks the report with `report check` before accepting it."}


# ------------------------------------------------------------------ provider replies and patches


_FENCE = re.compile(r"^[ \t]*```(?:diff|patch)[ \t]*\r?\n(.*?)^[ \t]*```[ \t]*$\r?\n?", re.MULTILINE | re.DOTALL)


def split_reply(text):
    """(report text without the diff blocks, the diff blocks joined)."""
    blocks = [m.group(1) for m in _FENCE.finditer(text)]
    report = _FENCE.sub("", text)
    patch = "".join(b if b.endswith("\n") else b + "\n" for b in blocks)
    return re.sub(r"\n{3,}", "\n\n", report), patch


def _unquote(path):
    path = path.strip()
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        path = path[1:-1]
    return path


def _strip_prefix(path, prefix):
    path = _unquote(path)
    return path[2:] if path.startswith(prefix) else path


def patch_files(patch):
    """Every path a unified diff touches (both sides of a rename), in order, once, without /dev/null."""
    found = []

    def add(path):
        path = path.split("\t")[0].strip()
        if path and path != "/dev/null" and path not in found:
            found.append(path)

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            rest = line[len("diff --git "):]
            m = re.match(r'^("?a/.+?"?) ("?b/.+"?)$', rest)
            if m:
                add(_strip_prefix(m.group(1), "a/"))
                add(_strip_prefix(m.group(2), "b/"))
        elif line.startswith("--- "):
            add(_strip_prefix(line[4:], "a/"))
        elif line.startswith("+++ "):
            add(_strip_prefix(line[4:], "b/"))
        elif line.startswith(("rename from ", "copy from ")):
            add(_unquote(line.split(" from ", 1)[1]))
        elif line.startswith(("rename to ", "copy to ")):
            add(_unquote(line.split(" to ", 1)[1]))
    return found


def _glob_regex(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def in_scope(path, scope):
    """Is the project-relative POSIX `path` inside one of the scope entries (a file, a folder or a glob)?"""
    for entry in scope:
        entry = entry.replace("\\", "/").strip().rstrip("/")
        if not entry:
            continue
        if any(ch in entry for ch in "*?"):
            if _glob_regex(entry).match(path):
                return True
        elif path == entry or path.startswith(entry + "/"):
            return True
    return False


def scope_violations(paths, scope):
    """The paths that are absolute, climb out with `..`, or lie outside every scope entry."""
    bad = []
    for raw in paths:
        path = raw.replace("\\", "/")
        segments = path.split("/")
        if (not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path) or ".." in segments
                or not in_scope(path, scope)):
            bad.append(raw)
    return bad


# ------------------------------------------------------------------ the brief's checks


_CHECK = re.compile(r"^\s*[-*]\s*(C\d+)\s*:\s*`([^`]+)`")


def extract_checks(brief_text):
    """[(id, command)] of the `## Checks` section: each item that names a backticked command."""
    lines = delegation.find_section(delegation.sections(brief_text), "checks") or []
    out = []
    for line in lines:
        m = _CHECK.match(line)
        if m:
            out.append((m.group(1), m.group(2).strip()))
    return out


# ------------------------------------------------------------------ outcome


@dataclass
class Outcome:
    status: str = "pending"       # a C30 result status, or "ran" when the area still has to run the gates
    error: str = ""
    report_text: str = None
    patch_text: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    session_id: str = None
    notes: list = field(default_factory=list)


def estimate_tokens(text):
    """A deliberately high estimate (three characters a token) so a projected cost is never under-counted."""
    return len(text) // 3 + 1


# ------------------------------------------------------------------ provider lane


def provider_messages(request, brief_text):
    scope = ", ".join(request.get("write_scope") or []) or "none (report only)"
    system = PROVIDER_SYSTEM.format(scope=scope)
    prompt = (f"{brief_text}\n\n---\nThe report will be saved as {request['report']}. Reply with the report text only"
              " (plus the optional diff block).")
    return system, prompt


def plan_output_budget(price, est_in, max_cost):
    """Output tokens the call may ask for so that even the worst case stays inside the cap; 0 when the cap buys no answer."""
    if price is None:
        return UNPRICED_MAX_OUT
    remaining = max_cost - est_in * price.input / 1_000_000
    if remaining <= 0:
        return 0
    allowed = int(remaining * 1_000_000 / price.output) if price.output > 0 else DEFAULT_MAX_OUT
    allowed = min(allowed, DEFAULT_MAX_OUT)
    return allowed if allowed >= MIN_OUT else 0


def run_provider(request, brief_text, *, kind, endpoint, credential, transport, price, max_cost, deadline,
                 report_only=False, clock=time.monotonic):
    """One tool-less call to a provider. Returns an Outcome whose status is `ran` (the area runs the gates on the report),
    `over-budget`, `error` or `timeout`. The error text is redacted here with the credential."""
    system, prompt = provider_messages(request, brief_text)
    est_in = estimate_tokens(system + prompt)
    max_out = plan_output_budget(price, est_in, max_cost)
    if max_out == 0:
        return Outcome("over-budget", f"the projected cost of this call exceeds the cap of {max_cost} USD; nothing was sent")
    if clock() >= deadline:
        return Outcome("timeout", "the time limit ended before the call was made")
    try:
        done = adapters.complete(kind, transport, model=request["model"], system=system, prompt=prompt, max_tokens=max_out,
                                 credential=credential, endpoint=endpoint, timeout=request["timeout_s"], deadline=deadline, clock=clock)
    except tr.TransportFailure as exc:
        status = "timeout" if "time limit" in str(exc) else "error"
        return Outcome(status, redact(str(exc), [credential]))
    except adapters.AdapterError as exc:
        return Outcome("error", redact(str(exc), [credential]))
    cost = prices.cost_usd(price, done.tokens_in, done.tokens_out) if price else 0.0
    out = Outcome("ran", tokens_in=done.tokens_in, tokens_out=done.tokens_out, cost_usd=cost)
    if price is None:
        out.notes.append("unpriced: the cost is recorded as 0 and the cap could not be enforced on it")
    if cost > max_cost + 1e-12:
        out.status = "over-budget"
        out.error = f"the call cost {cost} USD, over the cap of {max_cost} USD (partial cost recorded; the answer is discarded)"
        return out
    report, patch = split_reply(done.text)
    if report_only:
        patch = ""
    bad = scope_violations(patch_files(patch), request.get("write_scope") or []) if patch else []
    if bad:
        out.status = "error"
        out.error = "the patch touches files outside the write scope of the brief: " + ", ".join(bad)
        return out
    out.report_text, out.patch_text = report, patch
    return out


# ------------------------------------------------------------------ sdk lane: policy


def guard_ids_from_registry(path):
    """(ids of the PreToolUse guards in hooks.json, ids that fail closed). Without the file, the default guards."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return list(DEFAULT_GUARDS), set()
    ids, closed = [], set()
    for block in (doc.get("hooks") or {}).get("PreToolUse", []):
        for hook in block.get("hooks", []):
            args = hook.get("args")
            ident = args[-1] if args else (hook.get("command", "").split() or [""])[-1].strip('"')
            if not re.fullmatch(r"[a-z][a-z0-9-]*", ident or ""):
                continue
            if ident not in ids:
                ids.append(ident)
            if hook.get("onFailure") == "block":
                closed.add(ident)
    return ids, closed


def _deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def clean_env(env):
    """An environment for a guard subprocess without anything that looks like a credential."""
    return {k: v for k, v in env.items() if not SECRET_NAME.search(k)}


def _write_allowed(target, root, allowed, extra_roots):
    """May a write tool write `target`? Inside the project root and the write scope, or inside an extra root (the temp root)."""
    if not target:
        return False
    path = Path(target)
    absolute = path if path.is_absolute() else Path(root) / path
    try:
        resolved = absolute.resolve()
    except OSError:
        return False
    for extra in extra_roots:
        try:
            resolved.relative_to(Path(extra).resolve())
            return True
        except (ValueError, OSError):
            continue
    try:
        rel = resolved.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return False
    return not scope_violations([rel], allowed)


def make_policy(guard_ids, launcher, *, cwd, fail_closed=(), env=None, scope=None):
    """The PreToolUse hook of the SDK session. Each guard runs through `launcher(guard_id, payload_text, env) -> (exit code,
    stdout, stderr)` with the C16 payload and is read as Claude Code would read it (C31): exit 2 blocks with the message,
    exit 0 with a decision on stdout passes the decision through, any other exit is a non-blocking error unless the guard
    is declared fail-closed. `scope` is optional: (project root, allowed write paths, extra writable roots); a write tool outside it is denied."""
    guard_env = clean_env(env or {})
    closed = set(fail_closed)

    async def pre_tool(input_data, tool_use_id, context):
        name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input") or {}
        if scope is not None and name in WRITE_TOOLS:
            root, allowed, extra_roots = scope
            target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
            if not _write_allowed(target, root, allowed, extra_roots):
                return _deny(f"dispatch policy: {name} on {target or '(no path)'} is outside the write scope of the brief")
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input, "cwd": str(cwd)})
        for gid in guard_ids:
            try:
                code, out, err = launcher(gid, payload, guard_env)
            except Exception as exc:  # noqa: BLE001 (a launcher that cannot run is a failed guard)
                code, out, err = 1, "", f"{type(exc).__name__}: {exc}"
            if code == 2:
                return _deny((err or "").strip() or f"blocked by {gid}")
            if code == 0:
                if not (out or "").strip():
                    continue
                try:
                    decision = json.loads(out)
                    spec = decision["hookSpecificOutput"]
                    verdict = spec["permissionDecision"]
                except (ValueError, KeyError, TypeError):
                    decision, verdict = None, None
                if decision is not None:
                    if verdict == "allow":
                        continue
                    return decision
            if gid in closed:
                return _deny(f"guard {gid} could not decide and fails closed: {(err or 'unreadable answer').strip()[:300]}")
        return {}

    return pre_tool


# ------------------------------------------------------------------ sdk lane: the session loop


def tools_for(kind):
    tools = ["Read", "Glob", "Grep", "Write", "Edit", "MultiEdit", "Bash", "TodoWrite"]
    if kind in ("lookup", "research", "docs", "review"):
        tools += ["WebFetch", "WebSearch"]
    return tools


async def _session(sdk, options, prompt, state, save, deadline, clock):
    result = None
    async for msg in sdk.query(prompt=prompt, options=options):
        if isinstance(msg, sdk.SystemMessage):
            data = getattr(msg, "data", {}) or {}
            if getattr(msg, "subtype", "") == "init":
                state["session_id"] = data.get("session_id", state.get("session_id"))
                if data.get("apiKeySource") not in (None, "ANTHROPIC_API_KEY"):
                    raise RuntimeError("the session is not using the API key (apiKeySource=" + str(data.get("apiKeySource")) + ")")
                save(state)
        elif isinstance(msg, sdk.ResultMessage):
            result = msg
        if clock() >= deadline:
            raise TimeoutError("the time limit ended during the session")
    return result


def _usage(result):
    usage = getattr(result, "usage", None) or {}
    tin = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return tin, int(usage.get("output_tokens") or 0)


def run_sdk(request, brief_text, *, sdk, key, root, policy, deadline, max_cost, state, verify, save,
            kind="implement", clock=time.monotonic, sleep=None, rng=random.random):
    """Drive the Agent SDK session for a brief to an Outcome.

    `state` (dict: session_id, cost_usd, tokens_in, tokens_out, resumes) is updated and handed to `save` as the session
    goes, so a crash leaves what `dispatch resume` needs. `verify(outcome) -> (status, failure text)` runs the brief's
    checks and the report gates; a status other than `complete` sends the failure back to the agent for at most
    MAX_FIX_ROUNDS rounds. A session that was resumed continues at `state['session_id']`."""
    out = Outcome(session_id=state.get("session_id"))
    prompt = brief_text + SDK_FOOTER if not state.get("session_id") else (
        "You were interrupted. Continue the task from where you stopped: check the repository state and your report "
        "file first, then carry on. The brief is unchanged.")
    fix_rounds = 0

    def fill():
        out.session_id = state.get("session_id")
        out.cost_usd = round(state.get("cost_usd", 0.0), 6)
        out.tokens_in, out.tokens_out = int(state.get("tokens_in", 0)), int(state.get("tokens_out", 0))
        return out

    while True:
        if clock() >= deadline:
            out.status, out.error = "timeout", "the time limit ended"
            return fill()
        remaining = max_cost - state.get("cost_usd", 0.0)
        if remaining <= 1e-9:
            out.status, out.error = "over-budget", f"the cost cap of {max_cost} USD is spent"
            return fill()
        options = sdk.ClaudeAgentOptions(
            model=request["model"], cwd=str(root), allowed_tools=tools_for(kind), permission_mode="acceptEdits",
            max_turns=request["max_turns"], max_budget_usd=remaining, setting_sources=["user", "project"],
            env={"ANTHROPIC_API_KEY": key, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
            hooks={"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[policy])]},
            resume=state.get("session_id"), max_buffer_size=200 * 1024 * 1024,
            **({"effort": request["effort"]} if request.get("effort") else {}))
        try:
            result = asyncio.run(asyncio.wait_for(_session(sdk, options, prompt, state, save, deadline, clock),
                                                  timeout=max(0.001, deadline - clock())))
        except (asyncio.TimeoutError, TimeoutError):
            out.status, out.error = "timeout", "the time limit ended during the session"
            return fill()
        except Exception as exc:  # noqa: BLE001 (a crash or a lost connection: resume the same session after a back-off)
            state["resumes"] = state.get("resumes", 0) + 1
            save(state)
            if state["resumes"] > MAX_RESUMES:
                out.status, out.error = "error", f"{type(exc).__name__}: {redact(str(exc), [key])[:300]} (after {MAX_RESUMES} resumes)"
                return fill()
            _backoff(state["resumes"], deadline, clock, sleep, rng)
            prompt = "You were interrupted by an error. Continue from where you stopped (check the repository state and your report first)."
            continue
        if result is None:
            out.status, out.error = "error", "the session ended without a result message"
            return fill()
        state["session_id"] = getattr(result, "session_id", None) or state.get("session_id")
        state["cost_usd"] = state.get("cost_usd", 0.0) + float(getattr(result, "total_cost_usd", 0.0) or 0.0)
        tin, tout = _usage(result)
        state["tokens_in"], state["tokens_out"] = state.get("tokens_in", 0) + tin, state.get("tokens_out", 0) + tout
        save(state)
        subtype, api_status = getattr(result, "subtype", ""), getattr(result, "api_error_status", None)
        text = (getattr(result, "result", "") or "").strip()
        if state["cost_usd"] > max_cost + 1e-12 or subtype == "error_max_budget_usd":
            out.status, out.error = "over-budget", f"the session reached the cost cap of {max_cost} USD (cost so far {round(state['cost_usd'], 6)})"
            return fill()
        if getattr(result, "is_error", False) and (api_status in RETRYABLE_STATUS or subtype == "error_during_execution"):
            state["resumes"] = state.get("resumes", 0) + 1
            save(state)
            if state["resumes"] > MAX_RESUMES:
                out.status, out.error = "error", f"API errors ({api_status}) after {MAX_RESUMES} resumes: {redact(text, [key])[:200]}"
                return fill()
            _backoff(state["resumes"], deadline, clock, sleep, rng)
            prompt = "The API interrupted you. Continue from where you stopped (check the repository state and your report first)."
            continue
        if subtype == "error_max_turns":
            out.status, out.error = "incomplete", f"the turn limit of {request['max_turns']} was reached"
            return fill()
        if getattr(result, "is_error", False):
            out.status, out.error = "error", redact(text or subtype or "the session failed", [key])[:300]
            return fill()
        if text.startswith("BLOCKED"):
            out.status, out.error = "incomplete", redact(text, [key])[:500]
            return fill()
        status, failures = verify(fill())
        if status == "complete":
            out.status = "complete"
            return fill()
        fix_rounds += 1
        if fix_rounds > MAX_FIX_ROUNDS:
            out.status, out.error = status, redact(failures, [key])[:1500]
            return fill()
        prompt = ("The dispatcher ran the brief's checks and the report gates and they failed. Fix the causes (not the "
                  "checks), then end again with DONE: when they pass.\n\n" + failures)


def _backoff(n, deadline, clock, sleep, rng):
    wait = min(60.0, 5.0 * (2 ** (n - 1))) + rng() * 2.0
    if clock() + wait < deadline:
        (sleep or time.sleep)(wait)
