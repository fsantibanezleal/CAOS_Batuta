"""Area `dispatch`: where a brief runs and on which provider (plan section 3.5, contract C30).

Verbs:
    plan    validate a brief and a lane against the configuration (C01) and write the C30 request
    run     run a request: a dry run by default (what would be sent, secrets redacted), `--apply` executes the lane
    resume  continue a saved Agent SDK session of an unfinished result, within the original cost cap

Lanes: `subagent` (the CLI cannot launch a Claude Code subagent: it returns the launch specification for the main
session), `sdk` (the Claude Agent SDK on an API key, resumable, the batuta guards as the PreToolUse policy) and
`provider:<name>` (a tool-less call to an OpenAI-compatible endpoint, Gemini, or Claude on Bedrock or Vertex that returns a
report and an optional patch, applied by the main session only after the gates). Credentials are read from the environment
variable NAMED in the configuration at call time; no value is ever written to disk or printed (every output is redacted).
Billed lanes stop at the per-task cost cap (`caps.max_cost_usd_per_task`) and record provider, model, tokens and cost in the
ledger (C04) through `delegation.update_ledger`. Runs are started by hand, bounded by a monotonic time limit, and end with
the command: nothing is scheduled, detached or kept alive. Exit codes: 0 ok, 1 failure or refusal, 2 warnings or an
unfinished report.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from batuta_lib import config, contract, delegation
from batuta_lib.areas import report as report_area
from batuta_lib.dispatch import adapters, lanes, prices
from batuta_lib.dispatch import ledger as dledger
from batuta_lib.dispatch import transport as tr
from batuta_lib.dispatch.redact import redact
from batuta_lib.output import emit, item

AREA = "dispatch"
HELP = "Dispatch: plan where a brief runs (subagent, Agent SDK, provider), run it under cost and time caps, resume it."

MAX_RESUMES = lanes.MAX_RESUMES
DEFAULT_TURNS = 40
DEFAULT_TIMEOUT_S = 3600
CHECK_TIMEOUT_S = 3600
SDK_ENV = "ANTHROPIC_API_KEY"
SDK_INSTALL = "pip install claude-agent-sdk"
KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]+")


class SdkMissing(Exception):
    """The Claude Agent SDK package is not installed."""


# ------------------------------------------------------------------ seams (tests replace these; nothing else does)


def _transport(args):
    """The transport of provider lanes: the replay file of `--transport-fixture`, else HTTPS through the standard library."""
    path = getattr(args, "transport_fixture", None)
    return tr.ReplayTransport(path) if path else tr.UrllibTransport()


def _load_sdk():
    """The Claude Agent SDK module, imported only when the sdk lane runs."""
    try:
        return importlib.import_module("claude_agent_sdk")
    except ImportError as exc:
        raise SdkMissing("the claude-agent-sdk package is not installed") from exc


def _launch_guard(guard_id, payload_text, env, timeout=lanes.GUARD_TIMEOUT):
    """Run one guard through the C31 launcher `scripts/hook.py <id>` with the C16 payload on stdin: (exit code, stdout, stderr)."""
    hook = delegation.batuta_script().parent / "hook.py"
    try:
        proc = subprocess.run([sys.executable, "-I", str(hook), guard_id], input=payload_text, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 1, "", f"guard {guard_id} timed out after {timeout} s"
    return proc.returncode, proc.stdout, proc.stderr


def _run_command(command, cwd, timeout):
    """Run one check of a brief (bash when present, else the platform shell): (exit code, combined output)."""
    bash = shutil.which("bash")
    try:
        if bash:
            proc = subprocess.run([bash, "-c", command], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, check=False)
        else:
            proc = subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8",  # noqa: S602
                                  errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"the check timed out after {timeout} s"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ------------------------------------------------------------------ small helpers


def _wants_json(args):
    return bool(getattr(args, "json", False))


def _load(args):
    root, resolved, warnings = delegation.project_config(args)
    return root, resolved.config, warnings


def _write_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".dispatch-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        for attempt in range(40):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:   # a reader holds the target open for a moment (Windows)
                if attempt == 39:
                    raise
                time.sleep(0.05)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _rel(root, path):
    """The project-relative POSIX path of `path`, or None when it lies outside the project root."""
    p = Path(path)
    p = p if p.is_absolute() else Path(root) / p
    try:
        return p.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return None


def _c30_problems(doc):
    path = contract.find_schema(config.contracts_dir(), "C30")
    return contract.validate_instance("C30", doc, contract.load_schema(path))


def _result_path(request_path):
    name = Path(request_path).name
    if name.endswith(".dispatch-request.json"):
        return Path(request_path).with_name(name[: -len("-request.json")] + "-result.json")
    return Path(request_path).with_name(Path(name).stem + ".dispatch-result.json")


def _state_path(result_path):
    name = Path(result_path).name
    return Path(result_path).with_name(name.replace("-result.json", "-state.json") if "-result.json" in name else name + ".state")


def _ledger_path(root, cfg):
    return delegation.delegation_dir(root, cfg) / "ledger.md"


def _is_billed(lane):
    return lane != "subagent"


def _env_value(env, name):
    value = env.get(name) if name else None
    return value if value else None


def _sdk_key(cfg, env):
    """(credential variable name, key value or None, where it came from) for the sdk lane."""
    name = ((cfg.get("dispatch", {}).get("providers", {}) or {}).get("anthropic") or {}).get("credential_env") or SDK_ENV
    value = _env_value(env, name)
    if value:
        return name, value, f"the environment variable {name}"
    key_file = (cfg.get("dispatch", {}).get("sdk") or {}).get("key_file")
    if key_file:
        try:
            text = Path(key_file).read_text(encoding="utf-8-sig")
        except OSError:
            return name, None, "key file"
        found = KEY_PATTERN.search(text)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        key = found.group(0) if found else (lines[-1] if lines else "")
        if key:
            return name, key, "the key file named in the configuration"
    return name, None, "none"


def _role_model(cfg, role, header_model):
    spec = (cfg.get("roles") or {}).get(role) or {}
    return spec.get("model") or (header_model or "").split(" ")[0], spec.get("effort")


def _turns(budget_text):
    m = re.search(r"(\d+)\s*turns", budget_text or "", re.IGNORECASE)
    return int(m.group(1)) if m else DEFAULT_TURNS


# ------------------------------------------------------------------ preflight shared by plan and run


class Context:
    """What a lane needs after the checks: provider kind and name, endpoint, credential, price and the cost cap."""

    def __init__(self):
        self.provider = "-"
        self.kind = None
        self.endpoint = None
        self.credential = None
        self.credential_env = None
        self.price = None
        self.max_cost = None
        self.secrets = []


def _preflight(cfg, request, env, *, kind_of_brief, allow_unpriced, report_only):
    """(items, Context). A REFUSED item means the request cannot run."""
    items, ctx = [], Context()
    lane = request["lane"]
    disp = cfg.get("dispatch") or {}
    if lane not in (disp.get("lanes") or ["subagent"]):
        items.append(item("REFUSED", f"lane {lane} is not enabled in dispatch.lanes of the configuration"))
        return items, ctx
    if lane == "subagent":
        return items, ctx
    cap = (cfg.get("caps") or {}).get("max_cost_usd_per_task")
    asked = request.get("max_cost_usd")
    if lane == "sdk":
        ctx.provider, ctx.kind = "anthropic", "anthropic"
        name, key, source = _sdk_key(cfg, env)
        ctx.credential_env, ctx.credential = name, key
        if not key:
            items.append(item("REFUSED", f"the sdk lane has no key: set the environment variable {name} (or dispatch.sdk.key_file)"))
    else:
        pname = lane.split(":", 1)[1]
        pcfg = (disp.get("providers") or {}).get(pname)
        if pcfg is None:
            items.append(item("REFUSED", f"unknown provider {pname!r}: dispatch.providers has {', '.join(sorted(disp.get('providers') or {})) or 'none'}"))
            return items, ctx
        ctx.provider, ctx.kind = pname, pcfg["kind"]
        if ctx.kind not in adapters.ADAPTERS:
            items.append(item("REFUSED", f"provider {pname} has kind {ctx.kind}, which has no tool-less adapter (use the sdk lane for Anthropic)"))
            return items, ctx
        ctx.credential_env = pcfg["credential_env"]
        ctx.credential = _env_value(env, ctx.credential_env)
        if not ctx.credential:
            items.append(item("REFUSED", f"the environment variable {ctx.credential_env} (credential of provider {pname}) is not set or is empty"))
        if pcfg.get("endpoint_env"):
            ctx.endpoint = _env_value(env, pcfg["endpoint_env"])
            if not ctx.endpoint:
                items.append(item("REFUSED", f"the environment variable {pcfg['endpoint_env']} (endpoint of provider {pname}) is not set or is empty"))
        if kind_of_brief in lanes.TOOL_LESS_BLOCKED_KINDS and not report_only:
            items.append(item("REFUSED", f"a brief of kind {kind_of_brief} needs tools and provider lanes are tool-less: "
                                         "use --report-only to get a report only, or the sdk or subagent lane"))
    if ctx.credential:
        ctx.secrets.append(ctx.credential)
    # cost cap
    if asked is None and cap is None:
        items.append(item("REFUSED", "a billed lane needs a cost cap: set caps.max_cost_usd_per_task in the configuration or give --max-cost"))
    elif asked is not None and cap is not None and asked > cap:
        items.append(item("REFUSED", f"the budget of {asked} USD is above the cap of {cap} USD (caps.max_cost_usd_per_task)"))
    ctx.max_cost = asked if asked is not None else cap
    # price
    table = prices.load_prices()
    ctx.price = prices.lookup(ctx.provider, request["model"], kind=ctx.kind, table=table)
    if ctx.price is None:
        if allow_unpriced:
            items.append(item("WARN", f"no verified price for {ctx.provider}/{request['model']}: the cost is recorded as 0 and the cap cannot be enforced"))
        else:
            items.append(item("REFUSED", f"no verified price for {ctx.provider}/{request['model']}; pass --allow-unpriced to run it anyway "
                                         "(the cost cap cannot then be enforced)"))
    return items, ctx


# ------------------------------------------------------------------ plan


def _plan(args):
    out = lambda items, summary: emit(AREA, "plan", items, summary, _wants_json(args))  # noqa: E731
    try:
        root, cfg, warnings = _load(args)
    except config.ConfigError as exc:
        return out([item("FAIL", f"configuration: {exc}")], "dispatch plan failed")
    for line in warnings:
        print(line, file=sys.stderr)
    brief = Path(args.brief)
    try:
        text = delegation.read_text(brief)
    except OSError as exc:
        return out([item("FAIL", f"brief not found or unreadable: {exc}", brief.as_posix())], "dispatch plan failed")
    errors, _warn = delegation.lint_brief(text)
    if errors:
        return out([item("FAIL", f"brief does not pass its lint: {e}", brief.as_posix()) for e in errors], "dispatch plan failed")
    head = delegation.header_fields(text)
    rel_brief, rel_report = _rel(root, brief), _rel(root, head.get("report", ""))
    if rel_brief is None or rel_report is None:
        return out([item("FAIL", "the brief and its report must lie inside the project root: a request holds relative paths")], "dispatch plan failed")
    disp = cfg.get("dispatch") or {}
    lane = args.lane or disp.get("default_lane", "subagent")
    role = head.get("agent", "")
    role_model, effort = _role_model(cfg, role, head.get("model"))
    model = args.model
    if not model:
        if lane.startswith("provider:"):
            return out([item("REFUSED", f"lane {lane} needs --model (the provider's own model id)")], "dispatch plan refused")
        model = prices.resolve("anthropic", role_model) if lane == "sdk" else role_model
    request = {"contract_version": "1.0", "kind": "request", "run_id": head.get("id", ""), "brief": rel_brief, "report": rel_report,
               "lane": lane, "role": role, "model": model, "write_scope": delegation.scope_paths(head.get("write scope", "")),
               "max_turns": args.max_turns or _turns(head.get("budget")), "timeout_s": args.timeout_s or DEFAULT_TIMEOUT_S}
    if effort:
        request["effort"] = effort
    if lane.startswith("provider:"):
        request["provider"] = lane.split(":", 1)[1]
    items, ctx = _preflight(cfg, {**request, **({"max_cost_usd": args.max_cost} if args.max_cost is not None else {})}, os.environ,
                            kind_of_brief=head.get("kind", ""), allow_unpriced=args.allow_unpriced, report_only=args.report_only)
    if any(i["tag"] == "REFUSED" for i in items):
        return out(items, "dispatch plan refused")
    if _is_billed(lane):
        request["max_cost_usd"] = ctx.max_cost
        request["credential_env"] = ctx.credential_env
    problems = _c30_problems(request)
    if problems:
        return out(items + [item("FAIL", f"the request does not satisfy C30: {p}") for p in problems], "dispatch plan failed")
    target = Path(args.out) if args.out else brief.resolve().parent / f"{request['run_id']}.dispatch-request.json"
    items.append(item("OK", f"lane {lane}, model {model}, role {role}, run {request['run_id']}"
                            + (f", cap {ctx.max_cost} USD" if _is_billed(lane) else "")))
    if args.no_write:
        items.append(item("OK", json.dumps(request)))
    else:
        _write_atomic(target, json.dumps(request, indent=2) + "\n")
        items.append(item("NEW", "dispatch request written", target.as_posix()))
    return out(items, f"planned {request['run_id']} on {lane}")


# ------------------------------------------------------------------ run


def _read_request(path):
    try:
        doc = contract.loads_strict(delegation.read_text(path).lstrip("﻿"))
    except (OSError, ValueError) as exc:
        return None, f"request unreadable: {exc}"
    if not isinstance(doc, dict) or doc.get("kind") != "request":
        return None, "the file is not a C30 request (kind must be request)"
    problems = _c30_problems(doc)
    if problems:
        return None, "the request does not satisfy C30: " + "; ".join(problems)
    return doc, None


def _deadline(request, args, clock=time.monotonic):
    limit = float(request["timeout_s"])
    if getattr(args, "hours", None) is not None:
        limit = min(limit, max(0.0, float(args.hours)) * 3600.0)
    return clock() + limit


def _result_doc(request, status, ctx_provider, *, report=None, patch=None, outcome=None, duration=0.0, error=None):
    doc = {"contract_version": "1.0", "kind": "result", "run_id": request["run_id"], "lane": request["lane"], "status": status,
           "provider": ctx_provider, "model": request["model"], "duration_s": round(duration, 3)}
    if report:
        doc["report"] = report
    if patch:
        doc["patch"] = patch
    if outcome is not None and _is_billed(request["lane"]):
        doc.update(tokens_in=int(outcome.tokens_in), tokens_out=int(outcome.tokens_out), cost_usd=float(outcome.cost_usd))
    if error:
        doc["error"] = error
    return doc


def _finish(args, root, cfg, request, result_path, doc, items, secrets, state_path=None):
    """Validate and write the result, record the ledger row, print. Returns the exit code."""
    problems = _c30_problems(doc)
    if problems:
        items.append(item("FAIL", "the result does not satisfy C30: " + "; ".join(problems)))
    else:
        existed = Path(result_path).exists()
        _write_atomic(result_path, json.dumps(doc, indent=2) + "\n")
        items.append(item("CHANGED" if existed else "NEW", "dispatch result written", Path(result_path).as_posix()))
    status = doc["status"]
    try:
        values = {"Model": request["model"], "Status": status}
        if _is_billed(request["lane"]):
            values.update({"Provider": doc["provider"], "Tokens in": doc.get("tokens_in", 0), "Tokens out": doc.get("tokens_out", 0),
                           "Cost USD": doc.get("cost_usd", 0.0)})
        if request["lane"] == "subagent":
            _mark_pending(_ledger_path(root, cfg), request)
        else:
            dledger.record(_ledger_path(root, cfg), request["run_id"], values,
                           defaults={"Agent": request["role"], "Brief": request["brief"], "Report": request["report"]})
            items.append(item("OK", f"ledger row {request['run_id']}: {status}, {doc['provider']}, {doc.get('tokens_in', 0)} in, "
                                    f"{doc.get('tokens_out', 0)} out, {doc.get('cost_usd', 0.0)} USD"))
    except (delegation.LedgerError, OSError) as exc:
        items.append(item("FAIL", f"ledger not written: {exc}"))
    if status == "pending":
        pass
    elif status == "complete":
        items.append(item("OK", f"{request['run_id']} complete: the report passes the gates"))
    elif status == "incomplete":
        items.append(item("WARN", f"{request['run_id']} incomplete: {doc.get('error', '')}"))
    else:
        items.append(item("FAIL", f"{request['run_id']} {status}: {doc.get('error', '')}"))
    items = [dict(i, message=redact(i["message"], secrets)) for i in items]
    return emit(AREA, args.verb_name, items, f"{request['run_id']} on {request['lane']}: {status}", _wants_json(args))


def _mark_pending(ledger, request):
    """A launch specification was returned: the row goes from drafted to pending, never to launched (nothing was launched)."""
    def mutate(text):
        rows = delegation.ledger_rows(text)[1] if text.strip() else []
        row = next((r for r in rows if r["ID"] == request["run_id"]), None)
        if row is None or row.get("Status", "").strip() != "drafted":
            return text
        return delegation.ledger_set_status(text, request["run_id"], "pending")
    if Path(ledger).is_file():
        delegation.update_ledger(ledger, mutate)


def _dry_provider(request, ctx, system_prompt, max_out):
    system, prompt = system_prompt
    url, headers, body = adapters.request_for(ctx.kind, model=request["model"], system=system, prompt=prompt, max_tokens=max_out,
                                              credential=ctx.credential or "", endpoint=ctx.endpoint)
    items = [item("OK", f"would POST {url}")]
    items.extend(item("OK", f"header {k}: {v}") for k, v in headers.items())
    items.append(item("OK", f"body: model {request['model']}, max output tokens {max_out}, {len(body)} bytes, "
                            f"about {lanes.estimate_tokens(system + prompt)} input tokens"))
    return items


def _run_provider(args, root, cfg, request, ctx, brief_text, items, kind):
    system_prompt = lanes.provider_messages(request, brief_text)
    est_in = lanes.estimate_tokens("".join(system_prompt))
    max_out = lanes.plan_output_budget(ctx.price, est_in, ctx.max_cost)
    if not args.apply:
        items.extend(_dry_provider(request, ctx, system_prompt, max_out or lanes.MIN_OUT))
        if max_out == 0:
            items.append(item("WARN", "the projected cost already exceeds the cap: an --apply run would stop before sending"))
        items.append(item("OK", f"dry run: nothing was sent; cap {ctx.max_cost} USD, time limit {request['timeout_s']} s; add --apply to run"))
        return None
    started = time.monotonic()
    outcome = lanes.run_provider(request, brief_text, kind=ctx.kind, endpoint=ctx.endpoint, credential=ctx.credential,
                                 transport=_transport(args), price=ctx.price, max_cost=ctx.max_cost,
                                 deadline=_deadline(request, args), report_only=args.report_only)
    status, error, report_rel, patch_rel = outcome.status, outcome.error, None, None
    for note in outcome.notes:
        items.append(item("WARN", note))
    if status == "ran":
        report_path = root / request["report"]
        _write_atomic(report_path, outcome.report_text if outcome.report_text.endswith("\n") else outcome.report_text + "\n")
        report_rel = request["report"]
        items.append(item("NEW", "report written from the provider answer", report_path.as_posix()))
        verdict = report_area.check(brief_text, delegation.read_text(report_path))
        status = verdict.status
        if status != "complete":
            error = "; ".join(verdict.problems + verdict.open_items)[:1500]
        if outcome.patch_text and status != "defective":
            patch_path = report_path.with_suffix(".patch")
            _write_atomic(patch_path, outcome.patch_text)
            patch_rel = _rel(root, patch_path)
            items.append(item("NEW", "patch written next to the report: apply it only after the gates pass, never before", patch_path.as_posix()))
    doc = _result_doc(request, status, ctx.provider, report=report_rel, patch=patch_rel, outcome=outcome,
                      duration=time.monotonic() - started, error=error or (None if status == "complete" else "the run did not complete"))
    return doc


def _run_sdk(args, root, cfg, request, ctx, brief_text, items, kind, state=None, state_path=None):
    try:
        sdk = _load_sdk()
    except SdkMissing as exc:
        items.append(item("REFUSED" if args.apply else "WARN", f"{exc}: install it with `{SDK_INSTALL}`"))
        if args.apply:
            return None
        sdk = None
    registry = delegation.PLUGIN_ROOT / "hooks" / "hooks.json"
    guard_ids, closed = lanes.guard_ids_from_registry(registry)
    if not args.apply:
        items.append(item("OK", f"would start an Agent SDK session: model {request['model']}, up to {request['max_turns']} turns, "
                                f"cost cap {ctx.max_cost} USD, directory {root.as_posix()}"))
        items.append(item("OK", f"allowed tools: {', '.join(lanes.tools_for(kind))}; PreToolUse guards: {', '.join(guard_ids)}"))
        items.append(item("OK", "the key goes only into the session's own environment; it is never written or printed"))
        items.append(item("OK", f"dry run: nothing was started; time limit {request['timeout_s']} s; add --apply to run"))
        return None
    state = state or {"session_id": None, "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "resumes": 0}
    temp_root = (cfg.get("roots") or {}).get("temp")
    scope = (root, list(request["write_scope"]) + [request["report"]], [temp_root] if temp_root else [])
    policy = lanes.make_policy(guard_ids, _launch_guard, cwd=root, fail_closed=closed, env=dict(os.environ), scope=scope)
    checks = lanes.extract_checks(brief_text)
    report_path = root / request["report"]
    state_file = state_path or _state_path(_result_path(Path(args.request_path)))

    def save(st):
        _write_atomic(state_file, json.dumps({"request": Path(args.request_path).name, **st}, indent=2) + "\n")

    def verify(_outcome):
        failures, status = [], "complete"
        for cid, command in checks:
            code, output = _run_command(command, str(root), CHECK_TIMEOUT_S)
            if code != 0:
                failures.append(f"### {cid}: `{command}` (exit {code})\n{redact(output, ctx.secrets)[-4000:]}")
        if failures:
            status = "incomplete"
        try:
            verdict = report_area.check(brief_text, delegation.read_text(report_path))
        except OSError:
            failures.append(f"the report {request['report']} does not exist")
            return "incomplete", "\n\n".join(failures)
        if verdict.status != "complete":
            failures.append("### report gates\n" + "\n".join(verdict.problems + verdict.open_items))
            if verdict.status == "defective" and status == "complete":
                status = "defective"
            elif status == "complete":
                status = "incomplete"
        return status, "\n\n".join(failures)

    started = time.monotonic()
    outcome = lanes.run_sdk(request, brief_text, sdk=sdk, key=ctx.credential, root=root, policy=policy,
                            deadline=_deadline(request, args), max_cost=ctx.max_cost, state=state, verify=verify, save=save,
                            kind=kind)
    report_rel = request["report"] if report_path.is_file() else None
    status, error = outcome.status, outcome.error
    if status in ("incomplete", "defective") and report_rel is None:
        # C30: these two are verdicts on a report; without one the run did not produce it
        status, error = "error", f"no report was written ({error or status})"
    return _result_doc(request, status, "anthropic", report=report_rel, outcome=outcome, duration=time.monotonic() - started,
                       error=error or (None if status == "complete" else "the run did not complete"))


def _run(args, resume=None):
    args.verb_name = "resume" if resume else "run"
    out = lambda items, summary: emit(AREA, args.verb_name, items, summary, _wants_json(args))  # noqa: E731
    try:
        root, cfg, warnings = _load(args)
    except config.ConfigError as exc:
        return out([item("FAIL", f"configuration: {exc}")], f"dispatch {args.verb_name} failed")
    for line in warnings:
        print(line, file=sys.stderr)
    state, state_path = None, None
    if resume:
        result_path = Path(args.result)
        try:
            prior = contract.loads_strict(delegation.read_text(result_path).lstrip("﻿"))
        except (OSError, ValueError) as exc:
            return out([item("FAIL", f"result unreadable: {exc}", result_path.as_posix())], "dispatch resume failed")
        problems = _c30_problems(prior) if isinstance(prior, dict) else ["not an object"]
        if problems or prior.get("kind") != "result":
            return out([item("FAIL", "not a valid C30 result: " + "; ".join(problems or ["kind must be result"]), result_path.as_posix())],
                       "dispatch resume failed")
        if prior["lane"] != "sdk":
            return out([item("REFUSED", f"only the sdk lane keeps a session to resume (this result is of lane {prior['lane']}); "
                                        "run a provider or subagent lane again")], "dispatch resume refused")
        if prior["status"] == "complete":
            return out([item("REFUSED", f"{prior['run_id']} is complete: there is nothing to resume")], "dispatch resume refused")
        state_path = _state_path(result_path)
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            request_path = result_path.with_name(state["request"])
        except (OSError, ValueError, KeyError) as exc:
            return out([item("FAIL", f"the saved session state is missing or unreadable ({exc.__class__.__name__}): "
                                     "run the request again", state_path.as_posix())], "dispatch resume failed")
        if not state.get("session_id"):
            return out([item("REFUSED", "the saved state holds no session id: run the request again")], "dispatch resume refused")
        args.request_path = str(request_path)
    else:
        args.request_path = args.request
        request_path = Path(args.request)
    request, problem = _read_request(request_path)
    if request is None:
        return out([item("FAIL", problem, Path(request_path).as_posix())], f"dispatch {args.verb_name} failed")
    if resume:
        spent = float(state.get("cost_usd", 0.0))
        cap = request.get("max_cost_usd")
        if cap is not None and spent >= cap - 1e-9:
            return out([item("REFUSED", f"the cost cap of {cap} USD is already spent ({spent} USD): resume would exceed the cap")],
                       "dispatch resume refused")
    try:
        brief_text = delegation.read_text(root / request["brief"])
    except OSError as exc:
        return out([item("FAIL", f"brief unreadable: {exc}", request["brief"])], f"dispatch {args.verb_name} failed")
    head = delegation.header_fields(brief_text)
    kind = head.get("kind", "")
    env = dict(os.environ)
    items, ctx = _preflight(cfg, request, env, kind_of_brief=kind, allow_unpriced=args.allow_unpriced, report_only=args.report_only)
    secrets = list(ctx.secrets)
    if any(i["tag"] == "REFUSED" for i in items):
        return out([dict(i, message=redact(i["message"], secrets)) for i in items], f"dispatch {args.verb_name} refused")
    result_path = result_path if resume else _result_path(request_path)
    lane = request["lane"]
    if lane == "subagent":
        spec = lanes.subagent_spec(request)
        items.append(item("OK", "launch specification for the main session (not launched): " + json.dumps(spec)))
        if not args.apply:
            items.append(item("OK", "dry run: nothing was written; add --apply to write the pending result"))
            return emit(AREA, args.verb_name, items, f"{request['run_id']} on subagent: specification only", _wants_json(args))
        doc = _result_doc(request, "pending", "anthropic")
    elif lane == "sdk":
        doc = _run_sdk(args, root, cfg, request, ctx, brief_text, items, kind, state=state, state_path=state_path)
    else:
        doc = _run_provider(args, root, cfg, request, ctx, brief_text, items, kind)
    if doc is None:
        secrets = list(ctx.secrets)
        tag_refused = any(i["tag"] == "REFUSED" for i in items)
        return emit(AREA, args.verb_name, [dict(i, message=redact(i["message"], secrets)) for i in items],
                    f"{request['run_id']} on {lane}: " + ("refused" if tag_refused else "dry run"), _wants_json(args))
    return _finish(args, root, cfg, request, result_path, doc, items, secrets)


def _run_cmd(args):
    return _run(args)


def _resume_cmd(args):
    return _run(args, resume=True)


# ------------------------------------------------------------------ registration


def register(subparsers):
    plan = subparsers.add_parser("plan", help="validate a brief and a lane, write the C30 request")
    plan.add_argument("--brief", required=True, help="the brief file (C02)")
    plan.add_argument("--lane", help="subagent, sdk or provider:<name> (default: dispatch.default_lane)")
    plan.add_argument("--model", help="the model id (required for a provider lane; default: the role's model)")
    plan.add_argument("--max-cost", type=float, dest="max_cost", help="the cost budget in USD (never above caps.max_cost_usd_per_task)")
    plan.add_argument("--max-turns", type=int, dest="max_turns", help="turn limit (default: from the brief's budget line)")
    plan.add_argument("--timeout-s", type=int, dest="timeout_s", help=f"time limit in seconds (default {DEFAULT_TIMEOUT_S})")
    plan.add_argument("--report-only", action="store_true", help="a tool-less lane returns a report only, never a patch")
    plan.add_argument("--allow-unpriced", action="store_true", help="run a model without a verified price (the cap cannot be enforced)")
    plan.add_argument("--out", help="where to write the request (default: next to the brief)")
    plan.add_argument("--no-write", action="store_true", help="print the request without writing it")
    plan.add_argument("--root", default=".", help="project root (default: the current folder)")
    plan.set_defaults(func=_plan)

    run = subparsers.add_parser("run", help="run a request (dry run by default, --apply executes the lane)")
    run.add_argument("--request", required=True, help="the C30 request file")
    run.add_argument("--apply", action="store_true", help="execute the lane (default: print what would be sent)")
    run.add_argument("--hours", type=float, help="time limit in hours (never above the request's timeout_s)")
    run.add_argument("--report-only", action="store_true", help="a tool-less lane returns a report only, never a patch")
    run.add_argument("--allow-unpriced", action="store_true", help="run a model without a verified price (the cap cannot be enforced)")
    run.add_argument("--transport-fixture", dest="transport_fixture", help="answer provider calls from this JSON file (offline replay)")
    run.add_argument("--root", default=".", help="project root (default: the current folder)")
    run.set_defaults(func=_run_cmd)

    resume = subparsers.add_parser("resume", help="continue the saved Agent SDK session of an unfinished result")
    resume.add_argument("--result", required=True, help="the C30 result file of the unfinished sdk run")
    resume.add_argument("--apply", action="store_true", help="execute (default: print what would run)")
    resume.add_argument("--hours", type=float, help="time limit in hours (never above the request's timeout_s)")
    resume.add_argument("--report-only", action="store_true", help=argparse.SUPPRESS)
    resume.add_argument("--allow-unpriced", action="store_true", help="run a model without a verified price")
    resume.add_argument("--root", default=".", help="project root (default: the current folder)")
    resume.set_defaults(func=_resume_cmd)

