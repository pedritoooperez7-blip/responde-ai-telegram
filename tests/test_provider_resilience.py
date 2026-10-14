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
            with self.subTest(status=status), patch.object(ai.urllib.request, "urlopen", side_effect=response):
                with self.assertRaises(ai.ProviderError) as caught:
                    ai._request_json("https://provider.invalid", {}, {})
                self.assertEqual(caught.exception.category, category)
                self.assertNotIn("private conversation", str(caught.exception))

    def test_timeout_and_connection_failures_have_safe_categories(self):
        with patch.object(ai.urllib.request, "urlopen", side_effect=TimeoutError("secret timeout detail")):
            with self.assertRaises(ai.ProviderError) as caught:
                ai._request_json("https://provider.invalid", {}, {})
        self.assertEqual(caught.exception.category, "timeout")
        self.assertNotIn("secret timeout detail", str(caught.exception))
        with patch.object(ai.urllib.request, "urlopen", side_effect=urllib.error.URLError("private network detail")):
            with self.assertRaises(ai.ProviderError) as caught:
                ai._request_json("https://provider.invalid", {}, {})
        self.assertEqual(caught.exception.category, "connection_error")
        self.assertNotIn("private network detail", str(caught.exception))


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
