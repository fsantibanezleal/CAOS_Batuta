"""HTTP transport: the standard library over HTTPS with timeouts and bounded retries, behind a pluggable `send`.

A transport is any object with `send(method, url, headers, body, timeout) -> Response`; tests and the replay transport
never touch the network. `send_with_retries` retries 429, 5xx and connection errors with exponential backoff and jitter,
at most `MAX_RETRIES` times, never past the deadline, and honours `Retry-After` up to `MAX_DELAY` seconds.
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

MAX_RETRIES = 4
BASE_DELAY = 1.0
MAX_DELAY = 60.0
RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504, 529})
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


class TransportError(Exception):
    """The request could not be made (connection, DNS, TLS, timeout)."""


class TransportFailure(Exception):
    """Retries ended without a usable answer; the message says why and after how many attempts.

    `ambiguous` is True when a request may have reached the provider without an answer (a timeout, a cut connection): such a
    call may have billed, so the caller charges its allowed budget. False when the provider refused every attempt with a
    status (429, 5xx), which bills nothing."""

    def __init__(self, message, ambiguous=False):
        super().__init__(message)
        self.ambiguous = ambiguous


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


class UrllibTransport:
    """HTTPS through `urllib.request`. Plain HTTP is allowed only for the local host (Ollama, vLLM on this machine)."""

    def send(self, method, url, headers, body, timeout):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" and not (parts.scheme == "http" and (parts.hostname or "") in LOCAL_HOSTS):
            raise TransportError("only https URLs are allowed (plain http only for the local host)")
        req = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 (scheme checked above)
                return Response(resp.status, dict(resp.headers.items()), _read_bounded(resp, started, timeout))
        except urllib.error.HTTPError as exc:
            try:
                data = _read_bounded(exc, started, timeout)
            except TransportError:
                raise
            except Exception:  # noqa: BLE001
                data = b""
            return Response(exc.code, dict(exc.headers.items()) if exc.headers else {}, data)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc


def _read_bounded(resp, started, budget):
    """Read the whole body in chunks, checking the call's time budget between reads: the socket timeout bounds one read, so a
    server that trickles bytes could otherwise hold the call past its deadline."""
    chunks = []
    while True:
        if time.monotonic() - started > budget:
            raise TransportError("the call exceeded its time budget while reading the answer")
        chunk = resp.read(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


class ReplayTransport:
    """Answers from a JSON file (a list of {status, body, headers}) in order; used for offline runs and checks."""

    def __init__(self, path):
        with open(path, encoding="utf-8-sig") as fh:
            self.items = json.load(fh)
        self.requests = []

    def send(self, method, url, headers, body, timeout):
        self.requests.append({"method": method, "url": url})
        if not self.items:
            raise TransportError("the replay file has no more answers")
        item = self.items.pop(0)
        raw = item.get("body", {})
        return Response(int(item.get("status", 200)), dict(item.get("headers", {})),
                        raw if isinstance(raw, bytes) else json.dumps(raw).encode("utf-8"))


def _delay(attempt, retry_after, base_delay, rng):
    wait = base_delay * (2 ** attempt)
    wait += rng() * base_delay
    if retry_after:
        try:
            wait = max(wait, float(retry_after))
        except ValueError:
            pass
    return min(wait, MAX_DELAY)


def send_with_retries(tr, method, url, headers, body, *, timeout, max_retries=MAX_RETRIES, base_delay=BASE_DELAY,
                      rng=random.random, deadline=None, clock=time.monotonic):
    """The final Response (any status that is not retryable, including 4xx). Raises TransportFailure after the retries
    or when the deadline (a `clock()` value) would be passed."""
    last = "no attempt was made"
    ambiguous = False
    for attempt in range(max_retries + 1):
        if deadline is not None and clock() >= deadline:
            raise TransportFailure(f"the time limit ended before attempt {attempt + 1}; last: {last}", ambiguous)
        budget = timeout if deadline is None else max(0.001, min(timeout, deadline - clock()))
        retry_after = None
        try:
            resp = tr.send(method, url, headers, body, budget)
            if resp.status not in RETRY_STATUS:
                return resp
            last = f"HTTP {resp.status}"
            retry_after = {str(k).lower(): v for k, v in (resp.headers or {}).items()}.get("retry-after")
        except TransportError as exc:
            last = f"transport error: {exc}"
            ambiguous = True
        if attempt == max_retries:
            break
        wait = _delay(attempt, retry_after, base_delay, rng)
        if deadline is not None and clock() + wait >= deadline:
            raise TransportFailure(f"the time limit would pass during the backoff after attempt {attempt + 1}; last: {last}", ambiguous)
        time.sleep(wait)
    raise TransportFailure(f"gave up after {max_retries + 1} attempts; last: {last}", ambiguous)
