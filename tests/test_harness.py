"""Checks for the small, dependency-only M00 harness."""

from __future__ import annotations

import importlib.metadata
import os

import pytest

from c1 import __version__

NO_AI_ENVIRONMENT_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "HF_TOKEN",
    "AZURE_OPENAI_API_KEY",
)


def test_package_version_is_the_declared_harness_version() -> None:
    assert __version__ == "0.1.0rc2"
    assert importlib.metadata.version("c1") == __version__


def test_canary() -> None:
    if os.environ.get("C1_HARNESS_CANARY_FAIL") == "1":
        pytest.fail("intentional M00 harness canary failure")


def test_no_ai_env_required() -> None:
    configured = [key for key in NO_AI_ENVIRONMENT_KEYS if key in os.environ]
    assert configured == []
