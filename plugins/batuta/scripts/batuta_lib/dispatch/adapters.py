"""Provider adapters: one request builder and one answer parser per provider kind, over the pluggable transport.

Kinds: `openai-compatible` (chat completions: OpenAI, Azure OpenAI, vLLM, a LiteLLM gateway, Ollama), `gemini`
(generateContent), `bedrock` (Converse, with an API key as bearer token) and `vertex` (Claude `rawPredict`, with an access
token as bearer token). The credential goes only into a header, never into a URL, and an adapter never prints it.
Every adapter is tool-less: it returns text and token counts, nothing else.

Provider facts (read on 2026-10-15): Azure OpenAI takes the key in the `api-key` header (Microsoft Learn, "Azure OpenAI REST API
reference", Authentication: https://learn.microsoft.com/en-us/azure/ai-services/openai/reference); the Gemini key goes in
`x-goog-api-key` (https://ai.google.dev/gemini-api/docs/api-key); a Bedrock API key goes in `Authorization: Bearer`
(https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html). The Bedrock model in the request is the id of an
inference profile, `global.anthropic.claude-<model>` or `us.anthropic.claude-<model>` (the bare `anthropic.claude-...` id is not
shown working on the model cards); the configuration names the profile id and the adapter sends it unchanged.
"""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass

from batuta_lib.dispatch import transport as tr

DEFAULT_OPENAI = "https://api.openai.com/v1"
DEFAULT_GEMINI = "https://generativelanguage.googleapis.com"
VERTEX_VERSION = "vertex-2023-10-16"
ERROR_TEXT_LIMIT = 600


class AdapterError(Exception):
    """The provider refused the call or answered in a shape this adapter cannot use; the message is not yet redacted.

    `billed` is True when the provider accepted the call (a 2xx answer) and the answer was unusable: the call may have billed.
    `usage` is then the (tokens in, tokens out) the answer carries, or None when it carries none."""

    billed = False
    usage = None


@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int


def _json(headers=None):
    out = {"Content-Type": "application/json", "Accept": "application/json"}
    out.update(headers or {})
    return out


def _join(base, tail):
    parts = urllib.parse.urlsplit(base)
    path = parts.path.rstrip("/") + tail
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def _need_endpoint(kind, endpoint):
    if not endpoint:
        raise AdapterError(f"the {kind} adapter needs an endpoint (set the variable named by endpoint_env)")
    return endpoint


def _int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterError(f"the answer has no usable {what} (usage missing or malformed)")
    return value


# --------------------------------------------------------------- builders: (url, headers, body)


def build_openai(model, system, prompt, max_tokens, credential, endpoint):
    base = endpoint or DEFAULT_OPENAI
    headers = _json({"Authorization": f"Bearer {credential}"})
    if "openai.azure.com" in (urllib.parse.urlsplit(base).hostname or ""):
        headers["api-key"] = credential
    body = {"model": model, "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    return _join(base, "/chat/completions"), headers, body


def build_gemini(model, system, prompt, max_tokens, credential, endpoint):
    base = endpoint or DEFAULT_GEMINI
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens}}
    return _join(base, f"/v1beta/models/{urllib.parse.quote(model, safe='.-_')}:generateContent"), \
        _json({"x-goog-api-key": credential}), body


def build_bedrock(model, system, prompt, max_tokens, credential, endpoint):
    base = _need_endpoint("bedrock", endpoint)
    body = {"system": [{"text": system}], "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": max_tokens}}
    return _join(base, f"/model/{urllib.parse.quote(model, safe='.-_:')}/converse"), \
        _json({"Authorization": f"Bearer {credential}"}), body


def build_vertex(model, system, prompt, max_tokens, credential, endpoint):
    base = _need_endpoint("vertex", endpoint)
    body = {"anthropic_version": VERTEX_VERSION, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": prompt}]}
    return _join(base, f"/{urllib.parse.quote(model, safe='.-_@')}:rawPredict"), \
        _json({"Authorization": f"Bearer {credential}"}), body


# --------------------------------------------------------------- parsers: JSON -> Completion


def parse_openai(data):
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AdapterError("the answer has no choices[0].message.content") from exc
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        raise AdapterError("the answer has no usage block")
    return Completion(text or "", _int(usage.get("prompt_tokens"), "prompt_tokens"), _int(usage.get("completion_tokens"), "completion_tokens"))


def parse_gemini(data):
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise AdapterError("the answer has no candidates[0].content.parts") from exc
    usage = data.get("usageMetadata")
    if not isinstance(usage, dict):
        raise AdapterError("the answer has no usageMetadata block")
    out = _int(usage.get("candidatesTokenCount", 0), "candidatesTokenCount") + _int(usage.get("thoughtsTokenCount", 0), "thoughtsTokenCount")
    return Completion(text, _int(usage.get("promptTokenCount"), "promptTokenCount"), out)


def parse_bedrock(data):
    try:
        text = "".join(b.get("text", "") for b in data["output"]["message"]["content"])
    except (KeyError, TypeError, AttributeError) as exc:
        raise AdapterError("the answer has no output.message.content") from exc
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise AdapterError("the answer has no usage block")
    return Completion(text, _int(usage.get("inputTokens"), "inputTokens"), _int(usage.get("outputTokens"), "outputTokens"))


def parse_vertex(data):
    try:
        text = "".join(b.get("text", "") for b in data["content"] if b.get("type", "text") == "text")
    except (KeyError, TypeError, AttributeError) as exc:
        raise AdapterError("the answer has no content blocks") from exc
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise AdapterError("the answer has no usage block")
    return Completion(text, _int(usage.get("input_tokens"), "input_tokens"), _int(usage.get("output_tokens"), "output_tokens"))


def _salvage_pair(usage, in_key, out_key, extra_out=()):
    if not isinstance(usage, dict):
        return None
    try:
        tin = _int(usage.get(in_key), in_key)
        tout = _int(usage.get(out_key, 0), out_key) + sum(_int(usage.get(k, 0), k) for k in extra_out)
    except AdapterError:
        return None
    return tin, tout


def salvage_usage(kind, data):
    """(tokens in, tokens out) of an answer that could not be parsed otherwise, or None when it carries no usage figures."""
    if not isinstance(data, dict):
        return None
    if kind == "openai-compatible":
        return _salvage_pair(data.get("usage"), "prompt_tokens", "completion_tokens")
    if kind == "gemini":
        return _salvage_pair(data.get("usageMetadata"), "promptTokenCount", "candidatesTokenCount", ("thoughtsTokenCount",))
    if kind == "bedrock":
        return _salvage_pair(data.get("usage"), "inputTokens", "outputTokens")
    if kind == "vertex":
        return _salvage_pair(data.get("usage"), "input_tokens", "output_tokens")
    return None


ADAPTERS = {
    "openai-compatible": (build_openai, parse_openai),
    "gemini": (build_gemini, parse_gemini),
    "bedrock": (build_bedrock, parse_bedrock),
    "vertex": (build_vertex, parse_vertex),
}


def request_for(kind, *, model, system, prompt, max_tokens, credential, endpoint):
    """(url, headers, body bytes) of the call for a provider kind, without sending it."""
    if kind not in ADAPTERS:
        raise AdapterError(f"unknown provider kind {kind!r}; expected one of {', '.join(sorted(ADAPTERS))}")
    url, headers, body = ADAPTERS[kind][0](model, system, prompt, max_tokens, credential, endpoint)
    return url, headers, json.dumps(body).encode("utf-8")


def _error_text(resp):
    text = resp.body.decode("utf-8", errors="replace").strip()
    return text[:ERROR_TEXT_LIMIT]


def complete(kind, transport, *, model, system, prompt, max_tokens, credential, endpoint, timeout, deadline=None,
             prepare=None, charge=None, **retry):
    """Send one call through `transport` (with the bounded retries) and return a Completion.

    Raises AdapterError (provider answer unusable or a client error status) or transport.TransportFailure (retries
    ended). Messages may echo what the provider sent, so the caller redacts them."""
    url, headers, body = request_for(kind, model=model, system=system, prompt=prompt, max_tokens=max_tokens or 1,
                                     credential=credential, endpoint=endpoint)
    rebuild = None
    if prepare is not None:
        def rebuild(attempt):
            # the caller sizes every attempt (`prepare` returns its max tokens), so a retry never asks for more than is left
            _url, h, b = request_for(kind, model=model, system=system, prompt=prompt, max_tokens=prepare(attempt),
                                     credential=credential, endpoint=endpoint)
            return h, b
    resp = tr.send_with_retries(transport, "POST", url, headers, body, timeout=timeout, deadline=deadline,
                                prepare=rebuild, charge=charge, **retry)
    if resp.status < 200 or resp.status >= 300:
        raise AdapterError(f"the provider answered HTTP {resp.status}: {_error_text(resp)}")
    try:
        data = json.loads(resp.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        err = AdapterError("the provider answer is not JSON")
        err.billed = True
        raise err from exc
    try:
        if not isinstance(data, dict):
            raise AdapterError("the provider answer is not a JSON object")
        return ADAPTERS[kind][1](data)
    except AdapterError as exc:
        exc.billed, exc.usage = True, salvage_usage(kind, data)
        raise
