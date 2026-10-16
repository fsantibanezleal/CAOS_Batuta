"""Redaction: every log line, report, result and error message passes through here before it is printed or written.

Two layers: the known secret values of the run (and their JSON-escaped and URL-encoded forms), and patterns of common
token shapes, so a key echoed by a provider is masked even when the run never held it.
"""
from __future__ import annotations

import json
import re
import urllib.parse

MASK = "[REDACTED]"
MIN_SECRET = 6    # a shorter value would wipe ordinary words from the text
PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,256}"),
    re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,256}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,255}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,255}"),
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,60}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,100}"),
    re.compile(r"ya29\.[A-Za-z0-9._-]{20,512}"),
    re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z]+ )*PRIVATE KEY-----|$)"),
]
HEADER = re.compile(r"(?i)((?:authorization|x-api-key|api-key|x-goog-api-key)\s*[:=]\s*(?:bearer\s+)?)([^\s\"',;]{6,})")
BEARER = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/=-]{10,})")
QUERY_KEY = re.compile(r"(?i)([?&](?:key|api_key|apikey|access_token|token)=)([^&\s\"']+)")


def _forms(secret):
    forms = {secret, json.dumps(secret)[1:-1], urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)}
    return sorted((f for f in forms if len(f) >= MIN_SECRET), key=len, reverse=True)


def redact(text, secrets=()):
    """The text with every secret value, token pattern, credential header and key query parameter masked."""
    if not isinstance(text, str):
        text = str(text)
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= MIN_SECRET:
            for form in _forms(secret):
                text = text.replace(form, MASK)
    for pattern in PATTERNS:
        text = pattern.sub(MASK, text)
    text = HEADER.sub(lambda m: m.group(1) + MASK, text)
    text = BEARER.sub(lambda m: m.group(1) + MASK, text)
    return QUERY_KEY.sub(lambda m: m.group(1) + MASK, text)


def redact_obj(value, secrets=()):
    """The same for every string inside lists and dicts (keys included)."""
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, list):
        return [redact_obj(v, secrets) for v in value]
    if isinstance(value, dict):
        return {redact(str(k), secrets): redact_obj(v, secrets) for k, v in value.items()}
    return value
