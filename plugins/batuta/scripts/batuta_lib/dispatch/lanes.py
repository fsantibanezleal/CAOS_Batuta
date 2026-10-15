"""The dispatch lanes (plan section 3.5): the subagent launch specification, the tool-less provider call and the Claude Agent
SDK session with its PreToolUse policy.

Nothing here detaches a process or outlives the run: a provider call is one bounded request loop, an SDK session runs inside
`asyncio.run` under a monotonic deadline, and a guard runs as a short subprocess that is waited for.

Cost rule (binding): cost is cumulative per task across every call, crash, timeout and resume. A call that ends without usage
figures (a crash, a timeout, a cut stream, an answer that cannot be parsed and carries none) is charged its full allowed
budget, an upper bound, never 0.
"""
from __future__ import annotations

import ast
import asyncio
import functools
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
from batuta_lib.guards import shell as guardshell
from batuta_lib.guards import text as guardtext

MAX_RESUMES = 3                 # resumes of one session after an API error, then BLOCKED
MAX_FIX_ROUNDS = 2              # times the failure of a check goes back to the agent
DEFAULT_MAX_OUT = 16000         # output tokens a provider call may ask for when the cap allows it
UNPRICED_MAX_OUT = 4096
MIN_OUT = 256                   # below this the cap buys no useful answer: the run stops before sending
GUARD_TIMEOUT = 30
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
TOOL_LESS_BLOCKED_KINDS = ("implement", "job", "skeleton", "run")   # kinds that need tools: refused on a provider lane
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell", "Monitor")
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
AREAS_DIR = Path(__file__).resolve().parents[1] / "areas"

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
- Never push to a shared branch, never merge, never touch credentials, never read the process environment. Say in the
  report what the main session must do.
- When completely done, end with a message that starts with `DONE:`; if you cannot finish, start it with `BLOCKED:` and the reason.
"""


class SessionRefused(Exception):
    """The session cannot be used as configured (for example it is not on the API key); never retried."""


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
_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def split_reply(text):
    """(report text without the diff blocks, the diff blocks joined)."""
    blocks = [m.group(1) for m in _FENCE.finditer(text)]
    report = _FENCE.sub("", text)
    patch = "".join(b if b.endswith("\n") else b + "\n" for b in blocks)
    return re.sub(r"\n{3,}", "\n\n", report), patch


def _cunquote(path):
    """A path as git prints it: plain, or in double quotes with C escapes and octal bytes (UTF-8) decoded."""
    path = path.strip()
    if len(path) < 2 or path[0] != '"' or path[-1] != '"':
        return path
    inner, out, i = path[1:-1], bytearray(), 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            octal = re.match(r"[0-7]{1,3}", inner[i + 1:i + 4])
            if octal:
                out.append(int(octal.group(0), 8) & 0xFF)
                i += 1 + len(octal.group(0))
                continue
            if nxt in _C_ESCAPES:
                out.append(_C_ESCAPES[nxt])
                i += 2
                continue
        out.extend(ch.encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")


def _strip_prefix(path, prefix):
    path = _cunquote(path)
    return path[2:] if path.startswith(prefix) else path


_GIT_PAIR = re.compile(r'^("a/(?:[^"\\]|\\.)*"|a/\S.*?) ("b/(?:[^"\\]|\\.)*"|b/\S.*)$')


def patch_files(patch):
    """Every path a unified diff touches (both sides of a rename), in order, once, without /dev/null. Git's quoted paths
    (C escapes, octal bytes) are decoded before anything is compared with the write scope."""
    found = []

    def add(path):
        if path and path != "/dev/null" and path not in found:
            found.append(path)

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            m = _GIT_PAIR.match(line[len("diff --git "):])
            if m:
                add(_strip_prefix(m.group(1), "a/"))
                add(_strip_prefix(m.group(2), "b/"))
        elif line.startswith(("--- ", "+++ ")):
            raw = line[4:].split("\t")[0]
            add(_strip_prefix(raw, "a/" if line.startswith("--- ") else "b/"))
        elif line.startswith(("rename from ", "copy from ")):
            add(_cunquote(line.split(" from ", 1)[1].split("\t")[0]))
        elif line.startswith(("rename to ", "copy to ")):
            add(_cunquote(line.split(" to ", 1)[1].split("\t")[0]))
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
    rate_in, rate_out = price.rates(est_in)
    remaining = max_cost - est_in * rate_in / 1_000_000
    if remaining <= 0:
        return 0
    allowed = int(remaining * 1_000_000 / rate_out) if rate_out > 0 else DEFAULT_MAX_OUT
    allowed = min(allowed, DEFAULT_MAX_OUT)
    return allowed if allowed >= MIN_OUT else 0


def allowed_budget_cost(price, est_in, max_out):
    """The most a call can cost: its estimated input plus every output token it was allowed to ask for."""
    return prices.cost_usd(price, est_in, max_out) if price else 0.0


class _Budget:
    """What the attempts of one provider call have been charged so far (a running upper bound, never below the truth)."""

    def __init__(self):
        self.charged = 0.0
        self.tokens_in = 0
        self.tokens_out = 0
        self.max_out = 0


def run_provider(request, brief_text, *, kind, endpoint, credential, transport, price, max_cost, deadline,
                 report_only=False, clock=time.monotonic):
    """One tool-less call to a provider, with its bounded retries. Returns an Outcome whose status is `ran` (the area runs the
    gates on the report), `over-budget`, `error` or `timeout`. `max_cost` is what is left of the task's cap.

    Every attempt that may have billed (an error after the request was sent, a 5xx or 408 answer) is charged its full allowed
    budget, and the next attempt is sized to what is left of the cap; when that cannot cover an attempt the call stops BLOCKED
    (`over-budget`). A 429 answer and an error before the send retry without a charge. The error text is redacted here."""
    system, prompt = provider_messages(request, brief_text)
    est_in = estimate_tokens(system + prompt)
    if plan_output_budget(price, est_in, max_cost) == 0:
        return Outcome("over-budget", f"the projected cost of this call exceeds what is left of the cap ({max_cost} USD); nothing was sent")
    if clock() >= deadline:
        return Outcome("timeout", "the time limit ended before the call was made")
    budget = _Budget()

    def prepare(attempt):
        max_out = plan_output_budget(price, est_in, max_cost - budget.charged)
        if max_out == 0:
            raise tr.StopRetries(f"what is left of the cap ({round(max_cost - budget.charged, 6)} USD) cannot cover another attempt")
        budget.max_out = max_out
        return max_out

    def charge(attempt, why):
        budget.charged += allowed_budget_cost(price, est_in, budget.max_out)
        budget.tokens_in += est_in
        budget.tokens_out += budget.max_out

    def outcome(status, error, extra_cost=0.0, extra_in=0, extra_out=0):
        out = Outcome(status, redact(error, [credential]))
        out.cost_usd = round(budget.charged + extra_cost, 6)
        out.tokens_in, out.tokens_out = budget.tokens_in + extra_in, budget.tokens_out + extra_out
        return out

    try:
        done = adapters.complete(kind, transport, model=request["model"], system=system, prompt=prompt, max_tokens=None,
                                 credential=credential, endpoint=endpoint, timeout=request["timeout_s"], deadline=deadline, clock=clock,
                                 prepare=prepare, charge=charge)
    except tr.StopRetries as exc:
        out = outcome("over-budget", f"{exc}; the attempts already made were charged their allowed budgets ({round(budget.charged, 6)} USD)")
        return out
    except tr.TransportFailure as exc:
        out = outcome("timeout" if "time limit" in str(exc) else "error", str(exc))
        if budget.charged or budget.tokens_in:
            out.error += f" (attempts that may have billed were charged their allowed budgets: {round(budget.charged, 6)} USD)"
        return out
    except adapters.AdapterError as exc:
        if not exc.billed:
            return outcome("error", str(exc))
        if exc.usage:
            cost = prices.cost_usd(price, *exc.usage) if price else 0.0
            out = outcome("error", str(exc) + " (the cost of that attempt is that of the usage the answer carries)", cost, *exc.usage)
        else:
            cost = allowed_budget_cost(price, est_in, budget.max_out)
            out = outcome("error", str(exc) + f" (the answer carries no usage figures: the upper bound of {cost} USD is charged for that attempt)",
                          cost, est_in, budget.max_out)
        return out
    cost = prices.cost_usd(price, done.tokens_in, done.tokens_out) if price else 0.0
    out = Outcome("ran", cost_usd=round(budget.charged + cost, 6), tokens_in=budget.tokens_in + done.tokens_in,
                  tokens_out=budget.tokens_out + done.tokens_out)
    if price is None:
        out.notes.append("unpriced: the cost is recorded as 0 and the cap could not be enforced on it")
    if out.cost_usd > max_cost + 1e-12:
        out.status = "over-budget"
        out.error = f"the call cost {out.cost_usd} USD, over what was left of the cap ({max_cost} USD; partial cost recorded, the answer is discarded)"
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


# ------------------------------------------------------------------ sdk lane: guards and the policy


def default_guards():
    """The guard handler ids of the guard area, read the way the launcher reads them (the literal `HOOKS` dict of each area
    module, parsed with `ast`, nothing imported or executed): every id that starts with `guard-`, in declaration order."""
    ids = []
    for path in sorted(AREAS_DIR.glob("*.py")):
        try:
            source = path.read_text(encoding="utf-8-sig")
            if "HOOKS" not in source:
                continue
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)] if isinstance(node, ast.Assign) else []
            if "HOOKS" in targets and isinstance(node.value, ast.Dict):
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.startswith("guard-") \
                            and key.value not in ids:
                        ids.append(key.value)
    return ids


def guard_entries_from_registry(path):
    """The PreToolUse entries of hooks.json: [{id, matcher, timeout, fail_closed}] in file order. Without the file, one entry
    per default guard (no matcher: every tool). A file that names no guard gives an empty list (the caller refuses)."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return [{"id": g, "matcher": None, "timeout": None, "fail_closed": False} for g in default_guards()]
    entries = []
    for block in (doc.get("hooks") or {}).get("PreToolUse", []):
        for hook in block.get("hooks", []):
            args = hook.get("args")
            ident = args[-1] if args else (hook.get("command", "").split() or [""])[-1].strip('"')
            if not re.fullmatch(r"[a-z][a-z0-9-]*", ident or ""):
                continue
            timeout = hook.get("timeout")
            entries.append({"id": ident, "matcher": block.get("matcher") or None,
                            "timeout": timeout if isinstance(timeout, (int, float)) and timeout > 0 else None,
                            "fail_closed": hook.get("onFailure") == "block"})
    return entries


def guard_ids_from_registry(path):
    """(ids of the PreToolUse guards in hooks.json, ids that fail closed). Without the file, the default guards."""
    entries = guard_entries_from_registry(path)
    ids = []
    for e in entries:
        if e["id"] not in ids:
            ids.append(e["id"])
    return ids, {e["id"] for e in entries if e["fail_closed"]}


def _deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def clean_env(env):
    """An environment for a guard subprocess without anything that looks like a credential."""
    return {k: v for k, v in env.items() if not SECRET_NAME.search(k)}


_PROTECTED = r"(?:main|master|develop|trunk)"
DENY_RULES = [
    # reading the process environment (the API key sits in it): env, printenv, set, PowerShell env: drive, $env:, /proc, language APIs
    (r"(?:^|[;&|(`])\s*(?:env|printenv)(?:\s*$|\s*[;&|)]|\s+-)", "reads the process environment (it holds the API key)"),
    (r"\bprintenv\b", "reads the process environment (it holds the API key)"),
    (r"(?:^|[;&|(])\s*set\s*(?:$|[;&|)])", "lists the process environment (it holds the API key)"),
    (r"\b(?:get-childitem|gci|dir|ls|get-item|gi|get-content|gc|cat|type)\b[^;&|\n]*\benv:", "reads the PowerShell environment drive"),
    (r"\$\{?env:|\[environment\]::|getenvironmentvariable", "reads an environment variable through PowerShell"),
    (r"/proc/[^/\s]+/environ", "reads the process environment through /proc"),
    (r"\bos\.environ\b|\bos\.getenv\b|\bprocess\.env\b|\bENV\[|\bSystem\.getenv\b|\bgetenv\s*\(", "reads the process environment through a language API"),
    (r"\$\{?[A-Z0-9_]*(?:API_KEY|AUTH_TOKEN|SECRET|TOKEN)[A-Z0-9_]*|%[A-Z0-9_]*(?:API_KEY|AUTH_TOKEN|SECRET|TOKEN)[A-Z0-9_]*%",
     "expands a credential variable"),
    # pushes and merges (an unattended session never merges; pushing a feature branch by name is allowed)
    (rf"git\s+push\b[^\n]*(?:\s|:){_PROTECTED}\b", "pushes to a protected branch (merges go through the main session)"),
    (r"git\s+push\b[^\n]*(?:--force\S*|\s-f\b|\s\+)", "force push"),
    (r"git\s+push(?:\s+origin)?\s*(?:$|[;&|])", "a bare git push (name the feature branch: git push -u origin <branch>)"),
    (r"gh\s+pr\s+merge\b|gh\s+api\b[^\n]*/merges?\b", "merges a pull request (the main session merges)"),
    (r"gh\s+(?:repo|release)\s+delete|gh\s+secret\b", "deletes a repository or release, or touches secrets"),
    (rf"git\s+(?:checkout|switch)\s+{_PROTECTED}\b", "switches a worktree to a protected branch"),
    (r"git\s+(?:reset\s+--hard|clean\s+-[a-z]*f)", "discards work"),
    (r"docker\s+(?:system|builder|image|volume)\s+prune", "prunes Docker data"),
]
_DENY_COMPILED = [(re.compile(p, re.IGNORECASE | re.MULTILINE), why) for p, why in DENY_RULES]
_PROC_ENVIRON = re.compile(r"/proc/[^/\s]+/environ", re.IGNORECASE)


def deny_reason(tool_name, tool_input):
    """Why the dispatcher denies this tool call whatever the guards say, or None. The deny list ports the rules of the API
    orchestrator this lane replaces: reading the process environment, pushes to shared branches, merges and deletions."""
    if tool_name in SHELL_TOOLS:
        command = str((tool_input or {}).get("command", ""))
        folded = guardtext.deobfuscate(guardtext.normalize(command))
        for text in [folded, *guardtext.nested_texts(folded)]:
            for pattern, why in _DENY_COMPILED:
                if pattern.search(text):
                    return why
        return None
    if tool_name in ("Read", "Grep", "Glob"):
        target = str((tool_input or {}).get("file_path") or (tool_input or {}).get("path") or (tool_input or {}).get("pattern") or "")
        if _PROC_ENVIRON.search(guardtext.normalize(target).replace("\\", "/")):
            return "reads the process environment through /proc"
    return None


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


def _matches(matcher, tool_name):
    """Does an entry's matcher select the tool (as Claude Code applies it)? Raises re.error for an invalid pattern."""
    return not matcher or matcher == "*" or re.fullmatch(matcher, tool_name) is not None


NO_WRITE = ("/dev/null", "/dev/stdout", "/dev/stderr", "nul", "$null", "-")


def _cd_dest(seg):
    """The folder a directory-change command moves into (the first operand, or the value of -Path), or None when it has none."""
    args = guardshell.args_of(seg)
    i = 0
    while i < len(args):
        if args[i].lower() in ("-path", "-literalpath") and i + 1 < len(args):
            return args[i + 1].strip("'\"")
        if not args[i].startswith("-"):
            return args[i].strip("'\"")
        i += 1
    return None


def _is_absolute(path):
    return path.startswith("/") or re.match(r"^[A-Za-z]:", path) is not None


def shell_write_violations(command, root, allowed, extra_roots):
    """The write targets of a shell command that fall outside the write scope, the report and the extra roots.

    The targets come from the guards' own shell parser (redirects, tee, cp, mv, rm, touch, sed -i, PowerShell cmdlets, nested
    commands). The command is walked in order and a directory change (`cd`, `pushd`, `chdir`, `Set-Location`, `sl`) moves the
    folder a relative target is resolved against; a change that cannot be resolved statically (a variable, `~`, `-`, no operand,
    a subshell) leaves relative targets unresolvable, and an unresolvable target counts as outside."""
    folded = guardtext.deobfuscate(guardtext.normalize(command))
    bad = []
    cwd = Path(root).resolve()
    cd_seen = False
    walked = set()

    def unresolvable(t):
        return any(ch in t for ch in "$%*?~`")

    def check(target, cwd_now):
        t = target.strip().strip("'\"")
        if not t or t.lower() in NO_WRITE:
            return
        if unresolvable(t):
            ok = False
        else:
            path = Path(t.replace("\\", "/"))
            if _is_absolute(t):
                resolved = path
            elif cwd_now is None:
                resolved = None
            else:
                resolved = cwd_now / path
            ok = resolved is not None and _write_allowed(str(resolved), root, allowed, extra_roots)
        if not ok and t not in bad:
            bad.append(t)

    for seg in guardshell.all_segments(folded):
        if guardshell.command_name(seg) in guardshell.CD:
            cd_seen = True
            dest = _cd_dest(seg)
            if dest is None or dest == "-" or unresolvable(dest) or cwd is None or "(" in folded or "{" in folded:
                if dest is not None and not unresolvable(dest) and _is_absolute(dest) and "(" not in folded and "{" not in folded:
                    cwd = Path(dest.replace("\\", "/")).resolve()
                else:
                    cwd = None
            elif _is_absolute(dest):
                cwd = Path(dest.replace("\\", "/")).resolve()
            else:
                cwd = (cwd / dest.replace("\\", "/")).resolve()
            continue
        for target, _tag in guardshell.write_items(seg):
            walked.add(target.strip().strip("'\""))
            check(target, cwd)
    # what the walk above did not list: writers fed through a pipe or xargs (their targets come from the input, `*` when it has
    # none), links, and the spelling of a target joined with an earlier directory change. These are spelled relative to the project
    # root, so they are judged against it: a literal path inside the scope passes, anything else (or `*`) is denied.
    for target in guardshell.write_targets_of(folded):
        t = target.strip().strip("'\"")
        if t and (t not in walked or unresolvable(t) or _is_absolute(t)):
            check(t, Path(root).resolve())
    return bad


def make_policy(guard_ids, launcher, *, cwd, fail_closed=(), env=None, scope=None, entries=None):
    """The PreToolUse hook of the SDK session.

    Order: the dispatcher's own deny list, the write-scope check, then EVERY configured guard (an entry's matcher is
    applied as Claude Code applies it, its timeout is passed on). Each guard runs through `launcher(guard_id, payload_text,
    env[, timeout=]) -> (exit code, stdout, stderr)` with the C16 payload, off the event loop, and is read as Claude Code
    reads it (C31): exit 2 blocks with the message, exit 0 with a decision on stdout gives that decision, any other exit is a
    non-blocking error unless the guard fails closed. The strictest answer wins: deny, then ask, then allow; a guard never
    hides a later one. `scope` is optional: (project root, allowed write paths, extra writable roots)."""
    guard_env = clean_env(env or {})
    closed = set(fail_closed)
    plan = list(entries) if entries is not None else [{"id": g, "matcher": None, "timeout": None, "fail_closed": False} for g in guard_ids]

    def run_guard(gid, payload, timeout):
        call = functools.partial(launcher, timeout=timeout) if timeout else launcher
        try:
            return call(gid, payload, guard_env)
        except Exception as exc:  # noqa: BLE001 (a launcher that cannot run is a failed guard)
            return 1, "", f"{type(exc).__name__}: {exc}"

    async def pre_tool(input_data, tool_use_id, context):
        name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input") or {}
        why = deny_reason(name, tool_input)
        if why:
            return _deny(f"dispatch policy: {why}. Do it another way, or stop and report it.")
        if scope is not None and name in WRITE_TOOLS:
            root, allowed, extra_roots = scope
            target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
            if not _write_allowed(target, root, allowed, extra_roots):
                return _deny(f"dispatch policy: {name} on {target or '(no path)'} is outside the write scope of the brief")
        if scope is not None and name in SHELL_TOOLS:
            root, allowed, extra_roots = scope
            outside = shell_write_violations(str(tool_input.get("command", "")), root, allowed, extra_roots)
            if outside:
                return _deny("dispatch policy: the command writes outside the write scope of the brief: " + ", ".join(outside[:5]))
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input, "cwd": str(cwd)})
        denied, asked = None, None
        for entry in plan:
            gid = entry["id"]
            try:
                selected = _matches(entry.get("matcher"), name)
            except re.error:
                denied = denied or _deny(f"guard {gid} has a matcher that is not a valid regular expression ({entry.get('matcher')!r}): "
                                         "the call is denied, failing closed")
                continue
            if not selected:
                continue
            code, out, err = await asyncio.to_thread(run_guard, gid, payload, entry.get("timeout"))
            decision = None
            if code == 2:
                decision = _deny((err or "").strip() or f"blocked by {gid}")
            elif code == 0 and (out or "").strip():
                try:
                    parsed = json.loads(out)
                    verdict = parsed["hookSpecificOutput"]["permissionDecision"]
                    decision = parsed if verdict in ("deny", "ask") else None
                    if verdict not in ("deny", "ask", "allow"):
                        raise ValueError("unknown decision")
                except (ValueError, KeyError, TypeError):
                    if gid in closed or entry.get("fail_closed"):
                        decision = _deny(f"guard {gid} answered in a form that cannot be read and fails closed")
            elif code != 0 and (gid in closed or entry.get("fail_closed")):
                decision = _deny(f"guard {gid} could not decide and fails closed: {(err or 'unreadable answer').strip()[:300]}")
            if decision is None:
                continue
            if decision["hookSpecificOutput"]["permissionDecision"] == "deny":
                denied = denied or decision
            else:
                asked = asked or decision
        return denied or asked or {}

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
                    raise SessionRefused("the session is not using the API key (apiKeySource=" + str(data.get("apiKeySource")) + ")")
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

    `state` (dict: session_id, cost_usd, tokens_in, tokens_out, resumes) carries what the task has spent so far, including
    earlier runs, and is handed to `save` as the session goes. Every call gets at most the cap that is left
    (`max_budget_usd`). A call that ends without a ResultMessage (an exception, a timeout) is charged that whole budget, so a
    crash and resume loop can never spend more than the cap. `verify(outcome) -> (status, failure text)` runs the brief's
    checks and the report gates; a status other than `complete` sends the failure back to the agent for at most
    MAX_FIX_ROUNDS rounds, except `timeout`, which ends the run."""
    out = Outcome(session_id=state.get("session_id"))
    prompt = brief_text + SDK_FOOTER if not state.get("session_id") else (
        "You were interrupted. Continue the task from where you stopped: check the repository state and your report "
        "file first, then carry on. The brief is unchanged.")
    fix_rounds = 0
    last_failure = ""

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
            out.status = "over-budget"
            out.error = f"the cost cap of {max_cost} USD is spent" + (f" (last failure: {last_failure})" if last_failure else "")
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
        except SessionRefused as exc:
            out.status, out.error = "error", redact(str(exc), [key]) + ": refused, not retried"
            return fill()
        except (asyncio.TimeoutError, TimeoutError):
            state["cost_usd"] = state.get("cost_usd", 0.0) + remaining
            save(state)
            out.status = "timeout"
            out.error = (f"the time limit ended during the session; no usage figures came back, so its allowed budget of "
                         f"{round(remaining, 6)} USD is charged (an upper bound)")
            return fill()
        except Exception as exc:  # noqa: BLE001 (a crash or a lost connection)
            state["cost_usd"] = state.get("cost_usd", 0.0) + remaining
            state["resumes"] = state.get("resumes", 0) + 1
            save(state)
            last_failure = (f"{type(exc).__name__}: {redact(str(exc), [key])[:300]}; no usage figures came back, so the allowed "
                            f"budget of {round(remaining, 6)} USD was charged (an upper bound)")
            if state["resumes"] > MAX_RESUMES:
                out.status, out.error = "error", f"{last_failure} (after {MAX_RESUMES} resumes)"
                return fill()
            _backoff(state["resumes"], deadline, clock, sleep, rng)
            prompt = "You were interrupted by an error. Continue from where you stopped (check the repository state and your report first)."
            continue
        if result is None:
            state["cost_usd"] = state.get("cost_usd", 0.0) + remaining
            save(state)
            out.status = "error"
            out.error = (f"the session ended without a result message; its allowed budget of {round(remaining, 6)} USD "
                         "is charged (an upper bound)")
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
        if status == "timeout":
            out.status, out.error = "timeout", redact(failures, [key])[:500] or "the time limit ended while the checks ran"
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
