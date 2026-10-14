"""Offline contract tests for each provider adapter. No network calls or secrets required."""
from __future__ import annotations
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import ai_providers

STRUCTURED = json.dumps({"reply": "Podemos hablar un rato.", "alternative": "¿Tienes algún plan para hoy?"}, ensure_ascii=False)


class TestProviderAdapterContracts(unittest.TestCase):
    def test_gemini_response_contract_and_endpoint(self):
        response = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": STRUCTURED}]}]}
        with patch.object(ai_providers, "_request_json", return_value=response) as request:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret", "GEMINI_MODEL": "gemini-3.8-flash"}):
                answer = ai_providers._gemini("system", "hello")
        self.assertEqual(answer, STRUCTURED)
        self.assertEqual(request.call_args.args[0], "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(request.call_args.args[1]["x-goog-api-key"], "test-secret")

    def test_gemini_inline_image_payload_contract(self):
        import base64
        response = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": STRUCTURED}]}]}
        image_data = base64.b64encode(b"test-image-bytes").decode("ascii")
        content = [
            {"type": "text", "text": "Analiza esta captura"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_data}},
        ]
        with patch.object(ai_providers, "_request_json", return_value=response) as request:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret", "GEMINI_MODEL": "gemini-3.8-flash"}):
                answer = ai_providers._gemini("system", content)
        self.assertEqual(answer, STRUCTURED)
        payload = request.call_args.args[2]
        self.assertEqual(payload["input"][1], {"type": "text", "text": "Analiza esta captura"})
        self.assertEqual(payload["input"][2], {"type": "image", "mime_type": "image/png", "data": image_data})

    def test_groq_and_openrouter_openai_compatible_contracts(self):
        response = {"choices": [{"message": {"content": STRUCTURED}}]}
        for provider_url in (
            "https://api.groq.com/openai/v1/chat/completions",
            "https://openrouter.ai/api/v1/chat/completions",
        ):
            with self.subTest(url=provider_url), patch.object(ai_providers, "_request_json", return_value=response) as request:
                answer = ai_providers._openai_compatible(provider_url, "test-secret", "test-model", "system", "hello")
                self.assertEqual(answer, STRUCTURED)
                self.assertEqual(request.call_args.args[0], provider_url)
                self.assertEqual(request.call_args.args[1]["Authorization"], "Bearer test-secret")

    def test_cohere_v2_response_contract(self):
        response = {"message": {"content": [{"type": "text", "text": STRUCTURED}]}}
        with patch.object(ai_providers, "_request_json", return_value=response) as request:
            with patch.dict(os.environ, {"COHERE_API_KEY": "test-secret", "COHERE_MODEL": "command-r7b-12-2024"}):
                answer = ai_providers._cohere("system", "hello")
        self.assertEqual(answer, STRUCTURED)
        self.assertEqual(request.call_args.args[0], "https://api.cohere.com/v2/chat")
        self.assertEqual(request.call_args.args[1]["Authorization"], "Bearer test-secret")

    def test_provider_output_must_parse_to_two_distinct_replies(self):
        self.assertEqual(ai_providers._parse_replies(STRUCTURED), {
            "reply": "Podemos hablar un rato.", "alternative": "¿Tienes algún plan para hoy?"
        })
        self.assertIsNone(ai_providers._parse_replies('{"reply":"hola","alternative":"HOLA"}'))
        self.assertIsNone(ai_providers._parse_replies("not json"))

    def test_provider_failure_does_not_log_secret_or_raw_body(self):
        import urllib.error
        import io
        error = urllib.error.HTTPError(
            "https://provider.invalid", 401, "Unauthorized", {"Content-Type": "application/json"},
            io.BytesIO(b'{"error":{"message":"api_key=super-secret-value invalid"}}'),
        )
        with patch.object(ai_providers.urllib.request, "urlopen", side_effect=error), self.assertLogs("ai_providers", level="WARNING") as logs:
            with self.assertRaises(ai_providers.ProviderError):
                ai_providers._request_json("https://provider.invalid", {"Authorization": "Bearer super-secret-value"}, {})
        joined = " ".join(logs.output)
        self.assertNotIn("super-secret-value", joined)
        # Provider bodies are not logged at all: even sanitized text can contain private data.
        self.assertNotIn("api_key=", joined)
        self.assertIn("category=authentication", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
