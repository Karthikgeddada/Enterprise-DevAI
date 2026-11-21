"""OpenRouter LLM provider.

OpenRouter (https://openrouter.ai) gives unified access to many models
(GPT, Claude, Llama, DeepSeek, ...) through an OpenAI-compatible API.
Set OPENROUTER_API_KEY to enable. Optionally set OPENROUTER_MODEL to pick
a specific model id from https://openrouter.ai/models.
"""
import os
from typing import List

from providers.base import ModelInfo
from providers.deepseek_provider import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter provider - one API key, many models."""

    _provider_name = "openrouter"
    _display_name = "OpenRouter"
    _api_key_env = "OPENROUTER_API_KEY"
    _base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    _default_model = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4.1-flash-1017")
    # Model ids + pricing verified against the live OpenRouter catalog (Nov 2026);
    # ids retire often - re-check https://openrouter.ai/api/v1/models when changing.
    _models = [
        ModelInfo(
            id="deepseek/deepseek-v4.1-flash-1017", name="DeepSeek V4.1 Flash (default)",
            provider="openrouter", context_window=1048576,
            supports_streaming=True, supports_structured=True, max_output_tokens=8192,
            pricing_per_1m_input=0.15, pricing_per_1m_output=0.60,
        ),
        ModelInfo(
            id="nvidia/nemotron-3-ultra-550b-a55b:free", name="Nemotron 3 Ultra 550B (free)",
            provider="openrouter", context_window=1000000,
            supports_streaming=True, supports_structured=True, max_output_tokens=8192,
            pricing_per_1m_input=0.0, pricing_per_1m_output=0.0,
        ),
        ModelInfo(
            id="openai/gpt-5-nano", name="GPT-5 nano",
            provider="openrouter", context_window=400000,
            supports_streaming=True, supports_structured=True, max_output_tokens=16384,
            pricing_per_1m_input=0.05, pricing_per_1m_output=0.40,
        ),
        ModelInfo(
            id="openai/gpt-4o-mini", name="GPT-4o mini",
            provider="openrouter", context_window=128000,
            supports_streaming=True, supports_structured=True, max_output_tokens=16384,
            pricing_per_1m_input=0.15, pricing_per_1m_output=0.60,
        ),
        ModelInfo(
            id="anthropic/claude-sonnet-4.5", name="Claude Sonnet 4.5",
            provider="openrouter", context_window=1000000,
            supports_streaming=True, supports_structured=True, max_output_tokens=8192,
            pricing_per_1m_input=3.00, pricing_per_1m_output=15.00,
        ),
    ]
