"""HTTP transport: the standard library over HTTPS with timeouts and bounded retries, behind a pluggable `send`.

A transport is any object with `send(method, url, headers, body, timeout) -> Response`; tests and the replay transport
never touch the network. `UrllibTransport` speaks HTTP through `http.client` (the layer `urllib.request` is built on) so it
holds the socket: a watchdog timer closes it at the call's total time budget, whatever a slow server trickles, and the
response headers are bounded in size.

`send_with_retries` retries 429, 5xx and connection errors with exponential backoff and jitter, at most `MAX_RETRIES` times,
never past the deadline, and honours `Retry-After` up to `MAX_DELAY` seconds. It also tells the caller which attempts may have
billed: an error after the request was sent (a read timeout, a reset) and a 5xx or 408 answer are billable; a 429 answer and an
error before the send (connection refused, DNS, TLS handshake) are not. The optional `prepare(attempt)` rebuilds the request
before each attempt and `charge(attempt, why)` is called after each billable attempt; either may raise `StopRetries`.
"""
from __future__ import annotations

import http.client
import json
import random
import socket
import threading
import time
import urllib.parse
from dataclasses import dataclass, field

MAX_RETRIES = 4
BASE_DELAY = 1.0
MAX_DELAY = 60.0
MAX_HEADER_BYTES = 65536
RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504, 529})
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


class TransportError(Exception):
    """The request could not be made or completed (connection, DNS, TLS, timeout).

    `sent` is False only when the error proves the request was never sent (connection refused, DNS failure, a failure while
    connecting); any error after that point may have reached the provider, which may have billed for it."""

    def __init__(self, message="", sent=True):
        super().__init__(message)
        self.sent = sent


class TransportFailure(Exception):
    """Retries ended without a usable answer; the message says why and after how many attempts.

    `ambiguous` is True when a request may have reached the provider without an answer (a timeout, a cut connection)."""

    def __init__(self, message, ambiguous=False):
        super().__init__(message)
        self.ambiguous = ambiguous


class StopRetries(Exception):
    """Raised by the `prepare` or `charge` callbacks: no further attempt may be made (the message says why)."""


def before_send(exc):
    """True when `exc` proves that no request was sent: the connection was refused or the host name did not resolve."""
    return isinstance(exc, (ConnectionRefusedError, socket.gaierror))


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


def _read_bounded(resp, started, budget):
    """Read the whole body in chunks, checking the call's time budget between reads."""
    chunks = []
    while True:
        if time.monotonic() - started > budget:
            raise TransportError("the call exceeded its time budget while reading the answer")
        chunk = resp.read(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


class UrllibTransport:
    """HTTPS through the standard library. Plain HTTP is allowed only for the local host (Ollama, vLLM on this machine)."""

    def send(self, method, url, headers, body, timeout):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" and not (parts.scheme == "http" and (parts.hostname or "") in LOCAL_HOSTS):
            raise TransportError("only https URLs are allowed (plain http only for the local host)", sent=False)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        started = time.monotonic()
        conn = cls(parts.hostname, parts.port, timeout=timeout)
        fired = []

        def cut():
            fired.append(True)
            conn.close()

        timer = threading.Timer(timeout, cut)   # the watchdog: closes the socket at the total time budget
        timer.start()
        try:
            try:
                conn.connect()
            except (OSError, http.client.HTTPException, ValueError) as exc:
                text = "the call exceeded its time budget while connecting" if fired else f"{type(exc).__name__}: {exc}"
                raise TransportError(text, sent=False) from exc    # nothing was sent before the connection stood
            try:
                conn.request(method, target, body=body, headers=dict(headers))
                resp = conn.getresponse()
                header_list = list(resp.getheaders())
                if sum(len(str(k)) + len(str(v)) for k, v in header_list) > MAX_HEADER_BYTES:
                    raise TransportError(f"the response headers exceed {MAX_HEADER_BYTES} bytes")
                data = _read_bounded(resp, started, timeout)
                return Response(resp.status, dict(header_list), data)
            except TransportError:
                raise
            except (OSError, http.client.HTTPException, ValueError) as exc:
                text = "the call exceeded its time budget" if fired else f"{type(exc).__name__}: {exc}"
                raise TransportError(text, sent=True) from exc
        finally:
            timer.cancel()
            conn.close()


class ReplayTransport:
    """Answers from a JSON file (a list of {status, body, headers}) in order; used for offline runs and checks."""

    def __init__(self, path):
        with open(path, encoding="utf-8-sig") as fh:
            self.items = json.load(fh)
        self.requests = []

    def send(self, method, url, headers, body, timeout):
        self.requests.append({"method": method, "url": url})
        if not self.items:
            raise TransportError("the replay file has no more answers", sent=False)
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
                      rng=random.random, deadline=None, clock=time.monotonic, prepare=None, charge=None):
    """The final Response (any status that is not retryable, including 4xx). Raises TransportFailure after the retries
    or when the deadline (a `clock()` value) would be passed; StopRetries comes from the callbacks."""
    last = "no attempt was made"
    ambiguous = False
    for attempt in range(max_retries + 1):
        if deadline is not None and clock() >= deadline:
            raise TransportFailure(f"the time limit ended before attempt {attempt + 1}; last: {last}", ambiguous)
        if prepare is not None:
            headers, body = prepare(attempt)
        budget = timeout if deadline is None else max(0.001, min(timeout, deadline - clock()))
        retry_after = None
        billable = False
        try:
            resp = tr.send(method, url, headers, body, budget)
            if resp.status not in RETRY_STATUS:
                return resp
            last = f"HTTP {resp.status}"
            retry_after = {str(k).lower(): v for k, v in (resp.headers or {}).items()}.get("retry-after")
            billable = resp.status != 429
        except TransportError as exc:
            last = f"transport error: {exc}"
            ambiguous = ambiguous or exc.sent
            billable = exc.sent
        if billable and charge is not None:
            charge(attempt, last)
        if attempt == max_retries:
            break
        wait = _delay(attempt, retry_after, base_delay, rng)
        if deadline is not None and clock() + wait >= deadline:
            raise TransportFailure(f"the time limit would pass during the backoff after attempt {attempt + 1}; last: {last}", ambiguous)
        time.sleep(wait)
    raise TransportFailure(f"gave up after {max_retries + 1} attempts; last: {last}", ambiguous)
