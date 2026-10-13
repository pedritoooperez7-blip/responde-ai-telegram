"""One-shot, isolated live provider smoke runner for a dedicated Railway staging service."""
from __future__ import annotations
import os
import sys

REQUIRED_KEYS = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "COHERE_API_KEY")
missing = [name for name in REQUIRED_KEYS if not os.getenv(name, "").strip()]
if missing:
    print("LIVE PROVIDER TESTS ABORTED: missing required secret variable(s): " + ", ".join(missing))
    print("No provider requests were made. Configure these variables only in the isolated test service.")
    raise SystemExit(2)

os.environ["RUN_REAL_PROVIDER_TESTS"] = "1"
import pytest
raise SystemExit(pytest.main(["-q", "tests/test_provider_integration.py", "--disable-warnings"]))
