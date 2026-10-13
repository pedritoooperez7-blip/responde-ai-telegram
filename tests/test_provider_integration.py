"""Opt-in live smoke tests for AI providers.

These tests make real external API calls and may incur charges. They are skipped
unless RUN_REAL_PROVIDER_TESTS=1 and the provider's key is present. Never commit
keys or print them in test output.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import ai_providers


PROVIDERS = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "cohere": "COHERE_API_KEY",
}


@unittest.skipUnless(
    os.getenv("RUN_REAL_PROVIDER_TESTS") == "1",
    "Live provider tests disabled; set RUN_REAL_PROVIDER_TESTS=1 explicitly.",
)
class TestLiveAIProviders(unittest.TestCase):
    def _run_provider(self, provider: str, key_name: str) -> None:
        if not os.getenv(key_name):
            self.skipTest(f"{key_name} is not configured in this test environment")

        # Force exactly one provider so a fallback cannot make a broken adapter
        # appear healthy. Existing credentials are read but never printed.
        key = os.environ[key_name]
        env = {name: "" for name in PROVIDERS.values()}
        env[key_name] = key
        model_var = f"{provider.upper()}_MODEL"
        if os.getenv(model_var):
            env[model_var] = os.environ[model_var]
        with patch.dict(os.environ, env, clear=False):
            for other_key in PROVIDERS.values():
                if other_key != key_name:
                    os.environ.pop(other_key, None)
            result = ai_providers.generate_reply(
                "La otra persona escribió: ¿Qué planes tienes para hoy?",
                mode="natural",
                module="chat",
            )

        self.assertIsInstance(result, dict, f"{provider} did not return structured replies")
        self.assertEqual(result.get("provider"), provider)
        self.assertTrue(result.get("reply", "").strip())
        self.assertTrue(result.get("alternative", "").strip())
        self.assertNotEqual(
            result["reply"].strip().casefold(), result["alternative"].strip().casefold()
        )

    def test_gemini_live(self):
        self._run_provider("gemini", "GEMINI_API_KEY")

    def test_groq_live(self):
        self._run_provider("groq", "GROQ_API_KEY")

    def test_openrouter_live(self):
        self._run_provider("openrouter", "OPENROUTER_API_KEY")

    def test_cohere_live(self):
        self._run_provider("cohere", "COHERE_API_KEY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
