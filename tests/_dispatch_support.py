"""Shared helpers of the dispatch tests (unit U13): a scripted transport, a fake Agent SDK module, fake keys assembled at
run time (a literal key would trip the leak scanner and is never a real one), and a project with a brief."""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import TempCase, fill, report_text, write_config  # noqa: E402,F401


def fake_key(kind="anthropic"):
    """A string shaped like a provider key, built from parts so no literal token sits in the repository."""
    if kind == "anthropic":
        return "sk" + "-ant-" + "Zq7" * 12
    if kind == "openai":
        return "sk" + "-proj-" + "Qw3" * 14
    return "key" + "-" + "Rt5" * 10


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status = status
        self.headers = headers or {}
        self.body = body if isinstance(body, bytes) else json.dumps(body if body is not None else {}).encode()


class FakeTransport:
    """Answers from a script (a list of FakeResponse or exceptions) and records every request."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def send(self, method, url, headers, body, timeout):
        self.requests.append({"method": method, "url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        if not self.script:
            raise AssertionError("the transport was called more often than scripted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def openai_reply(text, tin=100, tout=50):
    return FakeResponse(200, {"choices": [{"message": {"role": "assistant", "content": text}}],
                              "usage": {"prompt_tokens": tin, "completion_tokens": tout}})


def gemini_reply(text, tin=100, tout=50):
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}}],
                              "usageMetadata": {"promptTokenCount": tin, "candidatesTokenCount": tout}})


def bedrock_reply(text, tin=100, tout=50):
    return FakeResponse(200, {"output": {"message": {"role": "assistant", "content": [{"text": text}]}},
                              "usage": {"inputTokens": tin, "outputTokens": tout}})


def vertex_reply(text, tin=100, tout=50):
    return FakeResponse(200, {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": tin, "output_tokens": tout}})


REPLIES = {"openai": openai_reply, "gemini": gemini_reply, "bedrock": bedrock_reply, "vertex": vertex_reply}


def good_report(ids=("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8")):
    extra = ("\n## Red run\n`python -m unittest` exit 1\n\n## Green run\n`python -m unittest` exit 0\n\n"
             "## Production path\n`python run.py` exit 0, output attached\n")
    return report_text([(i, "DONE", "`a`") for i in ids], extra=extra)


def partial_report(ids=("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8")):
    return report_text([(i, "PARTIAL", "half done") for i in ids])


def make_fake_sdk(calls):
    """A module shaped like claude_agent_sdk. `calls` is a list with one step list per query() call. A step is
    ("init", session_id), ("text", str), ("tool", name, input) (runs the PreToolUse policy, decision kept in module.decisions),
    ("write", path, text), ("result", dict of ResultMessage fields) or ("raise", exception)."""
    mod = types.ModuleType("claude_agent_sdk")
    mod.calls, mod.decisions, mod.script = [], [], list(calls)

    class ClaudeAgentOptions:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class HookMatcher:
        def __init__(self, matcher=None, hooks=None):
            self.matcher, self.hooks = matcher, hooks or []

    class SystemMessage:
        def __init__(self, subtype, data):
            self.subtype, self.data = subtype, data

    class TextBlock:
        def __init__(self, text):
            self.text = text

    class ToolUseBlock:
        def __init__(self, name, input):
            self.name, self.input = name, input

    class AssistantMessage:
        def __init__(self, content):
            self.content = content

    class ResultMessage:
        def __init__(self, **kw):
            base = dict(subtype="success", is_error=False, result="DONE: finished", total_cost_usd=0.5, num_turns=3,
                        session_id="sess-1", api_error_status=None, usage={"input_tokens": 1000, "output_tokens": 200})
            base.update(kw)
            self.__dict__.update(base)

    async def query(prompt, options):
        mod.calls.append({"prompt": prompt, "options": options})
        for step in mod.script.pop(0):
            kind = step[0]
            if kind == "init":
                yield SystemMessage("init", {"session_id": step[1], "apiKeySource": "ANTHROPIC_API_KEY"})
            elif kind == "text":
                yield AssistantMessage([TextBlock(step[1])])
            elif kind == "tool":
                hook = options.hooks["PreToolUse"][0].hooks[0]
                mod.decisions.append(await hook({"tool_name": step[1], "tool_input": step[2], "hook_event_name": "PreToolUse"}, "t1", None))
                yield AssistantMessage([ToolUseBlock(step[1], step[2])])
            elif kind == "write":
                Path(step[1]).write_text(step[2], encoding="utf-8")
            elif kind == "result":
                yield ResultMessage(**step[1])
            elif kind == "raise":
                raise step[1]

    mod.ClaudeAgentOptions, mod.HookMatcher, mod.SystemMessage = ClaudeAgentOptions, HookMatcher, SystemMessage
    mod.TextBlock, mod.ToolUseBlock, mod.AssistantMessage, mod.ResultMessage = TextBlock, ToolUseBlock, AssistantMessage, ResultMessage
    mod.query = query
    return mod


PROVIDERS = {
    "openai": {"kind": "openai-compatible", "credential_env": "OPENAI_API_KEY", "endpoint_env": "OPENAI_BASE_URL"},
    "gemini": {"kind": "gemini", "credential_env": "GEMINI_API_KEY"},
    "bedrock": {"kind": "bedrock", "credential_env": "BEDROCK_API_KEY", "endpoint_env": "BEDROCK_ENDPOINT"},
    "vertex": {"kind": "vertex", "credential_env": "VERTEX_TOKEN", "endpoint_env": "VERTEX_ENDPOINT"},
    "anthropic": {"kind": "anthropic", "credential_env": "ANTHROPIC_API_KEY"},
}
ENV = {"OPENAI_API_KEY": fake_key("openai"), "OPENAI_BASE_URL": "https://llm.example.org/v1", "GEMINI_API_KEY": fake_key("g"),
       "BEDROCK_API_KEY": fake_key("b"), "BEDROCK_ENDPOINT": "https://bedrock-runtime.eu-west-1.example.org",
       "VERTEX_TOKEN": fake_key("v"),
       "VERTEX_ENDPOINT": "https://europe-west1-aiplatform.example.org/v1/projects/p/locations/europe-west1/publishers/anthropic/models",
       "ANTHROPIC_API_KEY": fake_key("anthropic")}
MODELS = {"openai": "gpt-5", "gemini": "gemini-2.5-pro", "bedrock": "anthropic.claude-sonnet-5-5", "vertex": "claude-sonnet-5-5"}


class DispatchCase(TempCase):
    """A project root with a dispatch configuration and helpers to make a brief and a request."""

    def config(self, cap=5.0, lanes=("subagent", "sdk", "provider:openai", "provider:gemini", "provider:bedrock", "provider:vertex"),
               providers=None, **extra_dispatch):
        from batuta_lib import config
        caps = config.default_config({})["caps"]
        if cap is not None:
            caps["max_cost_usd_per_task"] = cap
        dispatch = {"default_lane": "subagent", "lanes": list(lanes), "providers": providers or PROVIDERS}
        dispatch.update(extra_dispatch)
        return write_config(self.root, caps=caps, dispatch=dispatch)

    def brief(self, topic="alpha", agent="implementer", kind=None, checks=None):
        path = self.filled_brief(topic, agent)
        text = path.read_text(encoding="utf-8")
        if kind:
            text = re.sub(r"^- kind: .*$", f"- kind: {kind}", text, count=1, flags=re.M)
        if checks:
            body = chr(10).join(f"- C{n}: `{c}` exits 0" for n, c in enumerate(checks, 1))
            text = re.sub(r"^## Checks.*?(?=^## |\Z)", lambda _m: "## Checks" + chr(10) + body + chr(10) + chr(10), text, count=1, flags=re.M | re.S)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def report_path(self, brief):
        from batuta_lib import delegation
        return Path(delegation.header_fields(brief.read_text(encoding="utf-8"))["report"])

    def request_file(self, brief, lane="subagent", **over):
        from batuta_lib import delegation
        head = delegation.header_fields(brief.read_text(encoding="utf-8"))
        req = {"contract_version": "1.0", "kind": "request", "run_id": head["id"],
               "brief": brief.relative_to(self.root).as_posix(),
               "report": Path(head["report"]).relative_to(self.root).as_posix(),
               "lane": lane, "role": head["agent"], "model": head["model"].split()[0], "write_scope": ["src/area/", "tests/area/"],
               "max_turns": 20, "timeout_s": 3600}
        if lane.startswith("provider:"):
            name = lane.split(":", 1)[1]
            req.update(provider=name, credential_env=PROVIDERS[name]["credential_env"], model=MODELS[name])
        elif lane == "sdk":
            req.update(model="claude-sonnet-5-5", credential_env="ANTHROPIC_API_KEY")
        req.update(over)
        path = self.root / ".batuta" / "delegation" / f"{head['id']}.dispatch-request.json"
        path.write_text(json.dumps(req), encoding="utf-8")
        return path

    def result_of(self, request_path):
        res = request_path.with_name(request_path.name.replace("-request", "-result"))
        return json.loads(res.read_text(encoding="utf-8"))
