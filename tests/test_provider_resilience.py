"""Offline resilience and schema tests; all provider traffic is mocked."""
from __future__ import annotations
import os
import sys
import unittest
import io
import urllib.error
import email.utils
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import ai_providers as ai


class TestProviderErrorClassification(unittest.TestCase):
    def test_http_status_categories(self):
        cases = {
            401: ("authentication", False),
            403: ("authentication", False),
            400: ("invalid_request", False),
            408: ("timeout", True),
            429: ("rate_limit", True),
            500: ("service_unavailable", True),
            503: ("service_unavailable", True),
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                error = ai.classify_provider_error(status, "temporary", {})
                self.assertEqual((error.category, error.transient), expected)
                self.assertNotIn("temporary", str(error))

    def test_quota_error_is_permanent(self):
        error = ai.classify_provider_error(429, '{"error":"quota exceeded"}', {})
        self.assertEqual(error.category, "quota_exceeded")
        self.assertFalse(error.transient)

    def test_retry_after_seconds_http_date_and_invalid_values(self):
        self.assertEqual(ai._parse_retry_after("2"), 2.0)
        future = email.utils.format_datetime(datetime.now(timezone.utc) + timedelta(seconds=3), usegmt=True)
        parsed = ai._parse_retry_after(future)
        self.assertIsNotNone(parsed)
        self.assertGreater(parsed, 0)
        self.assertLessEqual(parsed, 3.1)
        self.assertIsNone(ai._parse_retry_after("not-a-time"))

    def test_http_failures_are_categorized_without_logging_response_body(self):
        for status, category in ((401, "authentication"), (429, "rate_limit"), (503, "service_unavailable")):
            response = urllib.error.HTTPError(
                "https://provider.invalid", status, "error", {"Content-Type": "application/json"},
                io.BytesIO(b'{"error":{"message":"private conversation text"}}'),
            )
            with self.subTest(status=status), \
                 patch.object(ai.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), \
                 patch.object(ai.urllib.request, "urlopen", side_effect=response):
                with self.assertRaises(ai.ProviderError) as caught:
                    ai._request_json("https://provider.invalid", {}, {})
                self.assertEqual(caught.exception.category, category)
                self.assertNotIn("private conversation", str(caught.exception))

    def test_timeout_and_connection_failures_have_safe_categories(self):
        with patch.object(ai.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), \
             patch.object(ai.urllib.request, "urlopen", side_effect=TimeoutError("secret timeout detail")):
            with self.assertRaises(ai.ProviderError) as caught:
                ai._request_json("https://provider.invalid", {}, {})
        self.assertEqual(caught.exception.category, "timeout")
        self.assertNotIn("secret timeout detail", str(caught.exception))
        with patch.object(ai.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), \
             patch.object(ai.urllib.request, "urlopen", side_effect=urllib.error.URLError("private network detail")):
            with self.assertRaises(ai.ProviderError) as caught:
                ai._request_json("https://provider.invalid", {}, {})
        self.assertEqual(caught.exception.category, "connection_error")
        self.assertNotIn("private network detail", str(caught.exception))


class TestOpenAICompatibleErrorPayload(unittest.TestCase):
    def test_http_200_error_object_is_classified_without_leaking_payload(self):
        payload = {"error": {"message": "private prompt leaked", "code": "rate_limit_exceeded"}}
        with patch.object(ai, "_with_retry", return_value=payload):
            with self.assertRaises(ai.ProviderError) as caught:
                ai._openai_compatible("https://openrouter.ai/api/v1/chat/completions", "key", "model", "prompt", "text")
        self.assertEqual(caught.exception.category, "rate_limit")
        self.assertTrue(caught.exception.transient)
        self.assertNotIn("private prompt", str(caught.exception))

    def test_auth_error_object_is_not_transient(self):
        payload = {"error": {"message": "secret", "code": "invalid_api_key"}}
        with patch.object(ai, "_with_retry", return_value=payload):
            with self.assertRaises(ai.ProviderError) as caught:
                ai._openai_compatible("https://api.groq.com/openai/v1/chat/completions", "key", "model", "prompt", "text")
        self.assertEqual(caught.exception.category, "authentication")
        self.assertFalse(caught.exception.transient)


class TestStrictReplySchema(unittest.TestCase):
    def test_rejects_non_string_and_extra_fields(self):
        with self.assertRaises(ValueError):
            ai.validate_reply_schema({"reply": ["not text"], "alternative": "Otra respuesta"})
        with self.assertRaises(ValueError):
            ai.validate_reply_schema({"reply": "Respuesta uno", "alternative": "Respuesta dos", "debug": "extra"})

    def test_rejects_oversized_and_near_duplicate_replies(self):
        with self.assertRaises(ValueError):
            ai.validate_reply_schema({"reply": "a" * 1201, "alternative": "Otra opción válida"})
        with self.assertRaises(ValueError):
            ai.validate_reply_schema({"reply": "Podemos hablar un rato hoy", "alternative": "Podemos hablar un rato hoy."})

    def test_accepts_distinct_reply_pair(self):
        self.assertEqual(ai.validate_reply_schema({
            "reply": "Podemos hablar un rato.",
            "alternative": "¿Tienes algún plan para hoy?",
        }), {
            "reply": "Podemos hablar un rato.",
            "alternative": "¿Tienes algún plan para hoy?",
        })


class TestRetryDeadlineAndTelemetry(unittest.TestCase):
    def test_exponential_retry_is_bounded_and_eventually_succeeds(self):
        outcomes = [ai.ProviderError("busy", True), ai.ProviderError("busy", True), "ok"]
        def call():
            value = outcomes.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        with patch.object(ai.random, "uniform", return_value=0.0), patch.object(ai.time, "sleep") as sleep:
            self.assertEqual(ai._with_retry(call, max_attempts=3), "ok")
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.0, 0.0])

    def test_provider_health_is_per_provider_model_and_sanitized(self):
        ai._set_provider_health("test-provider", "test-model", False, "rate_limit")
        health = ai.get_provider_health()["test-provider:test-model"]
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["last_error_category"], "rate_limit")
        self.assertNotIn("api_key", str(health).lower())

    def test_retry_does_not_start_after_deadline(self):
        called = []
        with patch.object(ai, "remaining_provider_budget", return_value=0.0):
            with self.assertRaises(ai.ProviderError) as caught:
                ai._with_retry(lambda: called.append(True) or "ok")
        self.assertEqual(called, [])
        self.assertEqual(caught.exception.category, "timeout")

    def test_token_usage_is_only_recorded_when_provider_reports_it(self):
        timings = {}
        with ai.collect_timings(timings):
            ai.record_token_usage("groq", "test-model", 10, 5)
            ai.record_token_usage("groq", "test-model", None, None)
        self.assertEqual(len(timings["token_usage"]), 1)
        self.assertEqual(timings["token_usage"][0]["input_tokens"], 10)
        self.assertEqual(timings["token_usage"][0]["source"], "provider_reported")

    def test_configuration_report_never_returns_api_keys(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "do-not-return-this", "GROQ_MODEL": "test-model"}, clear=False):
            result = ai.validate_provider_configuration()
        self.assertTrue(result["groq"]["configured"])
        self.assertEqual(result["groq"]["model"], "test-model")
        self.assertNotIn("api_key", str(result).lower())
        self.assertNotIn("do-not-return-this", str(result))
        self.assertEqual(result["groq"]["model"], "test-model")
        self.assertFalse(result["groq"]["vision_compatibility_verified"])


PUBLIC_DNS = [(2, 1, 6, "", ("93.184.216.34", 443))]
PRIVATE_DNS = [(2, 1, 6, "", ("10.0.0.5", 443))]



class TestProviderDestinationValidation(unittest.TestCase):
    def test_public_dns_name_is_accepted(self):
        with patch.object(ai.socket, "getaddrinfo", return_value=PUBLIC_DNS) as resolver:
            endpoint = ai.normalize_compatible_endpoint("https://api.example.com/v1")
        self.assertEqual(endpoint, "https://api.example.com/v1/chat/completions")
        self.assertTrue(resolver.called)

    def test_name_resolving_to_private_address_is_rejected(self):
        with patch.object(ai.socket, "getaddrinfo", return_value=PRIVATE_DNS):
            with self.assertRaisesRegex(ValueError, "privada"):
                ai.normalize_compatible_endpoint("https://looks-public.example.com/v1")

    def test_private_and_loopback_literals_are_rejected(self):
        for url in ("https://127.0.0.1/v1", "https://10.1.2.3/v1", "https://localhost/v1",
                    "https://[::1]/v1", "https://169.254.169.254/v1", "http://api.example.com/v1"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    ai.normalize_compatible_endpoint(url)

    def test_unresolvable_host_is_rejected_without_network(self):
        with patch.object(ai.socket, "getaddrinfo", side_effect=ai.socket.gaierror("nx")):
            with self.assertRaises(ValueError):
                ai.normalize_compatible_endpoint("https://missing.example.com/v1")

    def test_ipv4_mapped_private_ipv6_is_rejected(self):
        with self.assertRaises(ValueError):
            ai.normalize_compatible_endpoint("https://[::ffff:10.0.0.1]/v1")

    def test_redirect_request_is_refused(self):
        handler = ai._NoRedirectHandler()
        with self.assertRaises(ai.ProviderError) as raised:
            handler.redirect_request(None, None, 302, "Found", {}, "https://127.0.0.1/internal")
        self.assertEqual(raised.exception.category, "redirect_not_allowed")

    def test_request_json_validates_target_before_connecting(self):
        opened = []
        with patch.object(ai.socket, "getaddrinfo", return_value=PRIVATE_DNS), \
             patch.object(ai.urllib.request, "urlopen", side_effect=lambda *a, **k: opened.append(a)):
            with self.assertRaises(ai.ProviderError) as raised:
                ai._request_json("https://looks-public.example.com/v1/chat/completions", {}, {})
        self.assertEqual(raised.exception.category, "blocked_destination")
        self.assertEqual(opened, [])

    def test_request_json_still_posts_to_public_provider(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return FakeResponse()

        with patch.object(ai.socket, "getaddrinfo", return_value=PUBLIC_DNS), \
             patch.object(ai.urllib.request, "urlopen", side_effect=fake_urlopen):
            result = ai._request_json("https://api.example.com/v1/chat/completions", {}, {})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["url"], "https://api.example.com/v1/chat/completions")

    def test_redirect_handler_is_installed_for_requests(self):
        opener = ai._public_url_opener()
        types = [type(handler) for handler in opener.handlers]
        self.assertIn(ai._NoRedirectHandler, types)


STRUCTURED_REPLY = '{"reply":"Hola, ¿cómo estás?","alternative":"¿Qué tal tu día?"}'


class TestProviderFallbackChain(unittest.TestCase):
    def _config(self, provider_id: str, priority: int, model: str) -> dict:
        return {
            "provider_id": provider_id,
            "base_url": "https://api.example.com/v1",
            "model": model,
            "api_key": "test-key",
            "supports_text": 1,
            "supports_image": 0,
            "priority": priority,
        }

    def test_invalid_priority_configuration_uses_default(self):
        with patch.dict(os.environ, {"AI_PRIORITY_GEMINI": "not-a-number"}):
            self.assertEqual(ai._priority("AI_PRIORITY_GEMINI", 10), 10)
        self.assertEqual(ai._priority("AI_PRIORITY_MISSING", 20), 20)
        self.assertEqual(ai._coerce_priority("bad", 50), 50)
        self.assertEqual(ai._coerce_priority(None, 50), 50)

    def test_unexpected_adapter_error_falls_through_to_the_next_provider(self):
        configs = [
            self._config("broken", 10, "broken-model"),
            self._config("good", 20, "good-model"),
        ]

        def fake_openai(url, key, model, prompt, content):
            if model == "broken-model":
                raise RuntimeError("unexpected adapter failure")
            return STRUCTURED_REPLY

        with patch.dict(os.environ, {}, clear=True), \
             patch.object(ai, "load_custom_provider_configs", return_value=configs), \
             patch.object(ai.socket, "getaddrinfo", return_value=PUBLIC_DNS), \
             patch.object(ai, "_openai_compatible", side_effect=fake_openai):
            result = ai._generate_reply_impl("hola", "coquetear", "chat")

        self.assertEqual(result["provider"], "custom:good")
        self.assertEqual(result["reply"], "Hola, ¿cómo estás?")

    def test_empty_response_falls_through_to_the_next_provider(self):
        configs = [
            self._config("empty", 10, "empty-model"),
            self._config("good", 20, "good-model"),
        ]

        def fake_openai(url, key, model, prompt, content):
            return "" if model == "empty-model" else STRUCTURED_REPLY

        with patch.dict(os.environ, {}, clear=True), \
             patch.object(ai, "load_custom_provider_configs", return_value=configs), \
             patch.object(ai.socket, "getaddrinfo", return_value=PUBLIC_DNS), \
             patch.object(ai, "_openai_compatible", side_effect=fake_openai):
            result = ai._generate_reply_impl("hola", "gracioso", "chat")

        self.assertEqual(result["provider"], "custom:good")

    def test_all_providers_failing_raises_provider_error_without_secrets(self):
        configs = [self._config("only", 10, "only-model")]
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(ai, "load_custom_provider_configs", return_value=configs), \
             patch.object(ai.socket, "getaddrinfo", return_value=PUBLIC_DNS), \
             patch.object(ai, "_openai_compatible", side_effect=ai.ProviderError("secret-free failure")):
            with self.assertRaises(ai.ProviderError) as raised:
                ai._generate_reply_impl("hola", "coquetear", "chat")
        self.assertNotIn("test-key", str(raised.exception))
        self.assertEqual(raised.exception.provider_failures[0]["provider"], "custom:only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
