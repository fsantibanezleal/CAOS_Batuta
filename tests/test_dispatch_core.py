"""dispatch core: redaction, price table, transport with bounded retries, provider adapters (unit U13, D3 and D4)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dispatch_support import (FakeResponse, FakeTransport, REPLIES, fake_key, openai_reply, vertex_reply)  # noqa: E402

from batuta_lib.dispatch import adapters, prices, redact, transport  # noqa: E402


class Redaction(unittest.TestCase):
    def test_masks_the_secret_value_wherever_it_appears(self):
        key = fake_key("g")
        out = redact.redact(f"error: bad key {key} and again {key}", [key])
        self.assertNotIn(key, out)
        self.assertIn(redact.MASK, out)

    def test_masks_token_patterns_without_knowing_the_value(self):
        for key in (fake_key("anthropic"), fake_key("openai")):
            self.assertNotIn(key, redact.redact(f"Authorization failed for {key}."))

    def test_masks_bearer_and_key_headers(self):
        out = redact.redact("Authorization: Bearer abcdef1234567890abcdef\nx-goog-api-key: abcdef1234567890")
        self.assertNotIn("abcdef1234567890", out)

    def test_masks_json_escaped_and_url_encoded_forms_of_the_value(self):
        key = "pa/ss+word=" + "x" * 8
        text = json.dumps({"k": key}) + " https://h/?k=" + __import__("urllib.parse").parse.quote(key, safe="")
        out = redact.redact(text, [key])
        self.assertNotIn("x" * 8, out)

    def test_short_or_empty_secrets_do_not_wipe_the_text(self):
        self.assertEqual(redact.redact("hello world", ["", "a"]), "hello world")

    def test_deep_structures_are_redacted(self):
        key = fake_key("g")
        out = redact.redact_obj({"a": [f"x {key}", {"b": key}]}, [key])
        self.assertNotIn(key, json.dumps(out))


class PriceTable(unittest.TestCase):
    def test_every_entry_has_a_source_url_and_a_date_read(self):
        table = prices.load_prices()
        self.assertTrue(table["prices"])
        for provider, models in table["prices"].items():
            for model, entry in models.items():
                self.assertRegex(entry["source"], r"^https://", (provider, model))
                self.assertRegex(entry["read"], r"^\d{4}-\d{2}-\d{2}$", (provider, model))
                self.assertIn(entry["status"], ("verified", "unverified"))

    def test_lookup_returns_the_price_for_a_verified_entry(self):
        price = prices.lookup("anthropic", "claude-sonnet-5-5")
        self.assertEqual((price.input, price.output), (2.0, 10.0))

    def test_alias_resolves_to_the_model_id(self):
        self.assertEqual(prices.lookup("anthropic", "sonnet").model, "claude-sonnet-5-5")

    def test_unknown_model_and_unverified_entries_are_unknown(self):
        table = {"version": 1, "aliases": {}, "prices": {"p": {"m": {"input": 1, "output": 2, "source": "https://x.example",
                                                                    "read": "2026-10-15", "status": "unverified"}}}}
        self.assertIsNone(prices.lookup("p", "m", table=table))
        self.assertIsNone(prices.lookup("nobody", "nothing"))

    def test_cost_is_per_million_tokens(self):
        price = prices.Price("m", 2.0, 10.0)
        self.assertAlmostEqual(prices.cost_usd(price, 500_000, 100_000), 2.0)

    def test_unverified_entries_exist_for_what_was_not_confirmed(self):
        # the Bedrock rate was not read on the AWS pricing page: it stays out of the verified set
        self.assertIsNone(prices.lookup("bedrock", "anthropic.claude-sonnet-5-5"))
        # the Vertex rows stay unknown until a Google page confirms them (the lookup found no readable price table)
        self.assertIsNone(prices.lookup("vertex", "claude-sonnet-5-5"))


class Retries(unittest.TestCase):
    def send(self, script, **kw):
        t = FakeTransport(script)
        with mock.patch("time.sleep") as sleep:
            try:
                resp = transport.send_with_retries(t, "POST", "https://h.example/x", {}, b"{}", timeout=5, **kw)
                return t, resp, None, sleep
            except transport.TransportFailure as exc:
                return t, None, exc, sleep

    def test_a_good_answer_is_returned_at_once(self):
        t, resp, exc, _ = self.send([FakeResponse(200, {"ok": 1})])
        self.assertEqual((resp.status, len(t.requests)), (200, 1))

    def test_429_and_5xx_are_retried_with_backoff_then_succeed(self):
        t, resp, exc, sleep = self.send([FakeResponse(429), FakeResponse(503), FakeResponse(200, {})])
        self.assertEqual((resp.status, len(t.requests)), (200, 3))
        self.assertEqual(sleep.call_count, 2)

    def test_a_429_storm_is_bounded_and_fails_with_the_attempt_count(self):
        t, resp, exc, _ = self.send([FakeResponse(429)] * 10, max_retries=3)
        self.assertIsNotNone(exc)
        self.assertEqual(len(t.requests), 4)       # the first try and three retries, never more
        self.assertIn("429", str(exc))

    def test_a_client_error_is_not_retried(self):
        t, resp, exc, _ = self.send([FakeResponse(401, {"error": "no"})])
        self.assertEqual((resp.status, len(t.requests)), (401, 1))

    def test_connection_errors_are_retried_then_reported(self):
        t, resp, exc, _ = self.send([transport.TransportError("boom")] * 6, max_retries=2)
        self.assertEqual(len(t.requests), 3)
        self.assertIn("boom", str(exc))

    def test_retry_after_is_honoured_but_capped(self):
        _t, _r, _e, sleep = self.send([FakeResponse(429, headers={"Retry-After": "9999"}), FakeResponse(200, {})])
        self.assertLessEqual(sleep.call_args[0][0], transport.MAX_DELAY)

    def test_jitter_comes_from_the_injected_source(self):
        t = FakeTransport([FakeResponse(500), FakeResponse(200, {})])
        with mock.patch("time.sleep") as sleep:
            transport.send_with_retries(t, "POST", "u", {}, b"", timeout=5, rng=lambda: 0.0, base_delay=2.0)
        self.assertEqual(sleep.call_args[0][0], 2.0)

    def test_no_retry_runs_past_the_deadline(self):
        t = FakeTransport([FakeResponse(503)] * 10)
        clock = iter([0.0, 0.0, 100.0, 100.0, 100.0, 100.0])
        with mock.patch("time.sleep"):
            with self.assertRaises(transport.TransportFailure) as cm:
                transport.send_with_retries(t, "POST", "u", {}, b"", timeout=5, max_retries=8, deadline=10.0,
                                            clock=lambda: next(clock))
        self.assertIn("time limit", str(cm.exception))
        self.assertLess(len(t.requests), 3)

    def test_the_timeout_never_exceeds_the_time_left(self):
        t = FakeTransport([FakeResponse(200, {})])
        transport.send_with_retries(t, "POST", "u", {}, b"", timeout=300, deadline=12.0, clock=lambda: 10.0)
        self.assertLessEqual(t.requests[0]["timeout"], 2.0 + 1e-9)


class Adapters(unittest.TestCase):
    def call(self, kind, reply, **kw):
        t = FakeTransport([reply])
        env = {"endpoint": {"openai-compatible": "https://llm.example.org/v1", "bedrock": "https://bedrock-runtime.eu-west-1.example.org",
                            "vertex": "https://eu-aiplatform.example.org/v1/projects/p/locations/l/publishers/anthropic/models",
                            "gemini": None}[kind]}
        done = adapters.complete(kind, t, model=kw.get("model", "m1"), system="SYS", prompt="PROMPT", max_tokens=777,
                                 credential="CRED-VALUE-123456", endpoint=env["endpoint"], timeout=30)
        return t.requests[0], done

    def test_openai_compatible(self):
        req, done = self.call("openai-compatible", openai_reply("hi", 11, 7))
        self.assertEqual(req["url"], "https://llm.example.org/v1/chat/completions")
        self.assertEqual(req["headers"]["Authorization"], "Bearer CRED-VALUE-123456")
        body = json.loads(req["body"])
        self.assertEqual((body["model"], body["max_completion_tokens"]), ("m1", 777))
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual((done.text, done.tokens_in, done.tokens_out), ("hi", 11, 7))

    def test_openai_compatible_default_endpoint_and_azure_header(self):
        t = FakeTransport([openai_reply("a")])
        adapters.complete("openai-compatible", t, model="m", system="s", prompt="p", max_tokens=5, credential="K" * 12,
                          endpoint="https://res.openai.azure.com/openai/deployments/d?api-version=2025-01-01", timeout=5)
        self.assertEqual(t.requests[0]["headers"]["api-key"], "K" * 12)
        self.assertIn("/chat/completions", t.requests[0]["url"])
        self.assertIn("api-version=2025-01-01", t.requests[0]["url"])
        t2 = FakeTransport([openai_reply("a")])
        adapters.complete("openai-compatible", t2, model="m", system="s", prompt="p", max_tokens=5, credential="K" * 12,
                          endpoint=None, timeout=5)
        self.assertTrue(t2.requests[0]["url"].startswith("https://api.openai.com/v1/"))

    def test_gemini(self):
        req, done = self.call("gemini", REPLIES["gemini"]("hello", 20, 9), model="gemini-2.5-pro")
        self.assertEqual(req["url"], "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent")
        self.assertEqual(req["headers"]["x-goog-api-key"], "CRED-VALUE-123456")
        self.assertNotIn("CRED-VALUE", req["url"])
        body = json.loads(req["body"])
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 777)
        self.assertEqual((done.text, done.tokens_in, done.tokens_out), ("hello", 20, 9))

    def test_gemini_thinking_tokens_count_as_output(self):
        reply = FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "x"}]}}],
                                   "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2, "thoughtsTokenCount": 30}})
        _req, done = self.call("gemini", reply)
        self.assertEqual(done.tokens_out, 32)

    def test_bedrock_converse(self):
        req, done = self.call("bedrock", REPLIES["bedrock"]("ok", 4, 3), model="anthropic.claude-sonnet-5-5")
        self.assertEqual(req["url"], "https://bedrock-runtime.eu-west-1.example.org/model/anthropic.claude-sonnet-5-5/converse")
        self.assertEqual(req["headers"]["Authorization"], "Bearer CRED-VALUE-123456")
        body = json.loads(req["body"])
        self.assertEqual(body["inferenceConfig"]["maxTokens"], 777)
        self.assertEqual((done.text, done.tokens_in, done.tokens_out), ("ok", 4, 3))

    def test_vertex_claude(self):
        req, done = self.call("vertex", vertex_reply("fine", 6, 2), model="claude-sonnet-5-5")
        self.assertTrue(req["url"].endswith("/publishers/anthropic/models/claude-sonnet-5-5:rawPredict"))
        body = json.loads(req["body"])
        self.assertEqual((body["anthropic_version"], body["max_tokens"]), ("vertex-2023-10-16", 777))
        self.assertEqual((done.text, done.tokens_in, done.tokens_out), ("fine", 6, 2))

    def test_a_provider_error_status_raises_with_the_provider_message(self):
        t = FakeTransport([FakeResponse(401, {"error": {"message": "Incorrect API key provided: CRED-VALUE-123456"}})])
        with self.assertRaises(adapters.AdapterError) as cm:
            adapters.complete("openai-compatible", t, model="m", system="s", prompt="p", max_tokens=5,
                              credential="CRED-VALUE-123456", endpoint="https://h.example/v1", timeout=5)
        self.assertIn("401", str(cm.exception))

    def test_a_malformed_answer_is_an_adapter_error(self):
        t = FakeTransport([FakeResponse(200, b"<html>not json</html>")])
        with self.assertRaises(adapters.AdapterError):
            adapters.complete("gemini", t, model="m", system="s", prompt="p", max_tokens=5, credential="K" * 12, endpoint=None, timeout=5)

    def test_missing_usage_is_an_adapter_error_not_zero_cost(self):
        t = FakeTransport([FakeResponse(200, {"choices": [{"message": {"content": "x"}}]})])
        with self.assertRaises(adapters.AdapterError) as cm:
            adapters.complete("openai-compatible", t, model="m", system="s", prompt="p", max_tokens=5, credential="K" * 12,
                              endpoint="https://h.example/v1", timeout=5)
        self.assertIn("usage", str(cm.exception))

    def test_bedrock_and_vertex_need_an_endpoint(self):
        for kind in ("bedrock", "vertex"):
            with self.assertRaises(adapters.AdapterError):
                adapters.complete(kind, FakeTransport([]), model="m", system="s", prompt="p", max_tokens=5, credential="K" * 12,
                                  endpoint=None, timeout=5)

    def test_unknown_kind(self):
        with self.assertRaises(adapters.AdapterError):
            adapters.complete("telepathy", FakeTransport([]), model="m", system="s", prompt="p", max_tokens=5,
                              credential="K" * 12, endpoint=None, timeout=5)

    def test_the_standard_library_transport_refuses_plain_http_to_non_local_hosts(self):
        with self.assertRaises(transport.TransportError):
            transport.UrllibTransport().send("POST", "http://remote.example.org/v1", {}, b"", 5)


if __name__ == "__main__":
    unittest.main()
