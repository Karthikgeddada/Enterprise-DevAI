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
    _default_model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    _models = [
        ModelInfo(
            id="meta-llama/llama-3.3-70b-instruct:free", name="Llama 3.3 70B (free)",
            provider="openrouter", context_window=131072,
            supports_streaming=True, supports_structured=True, max_output_tokens=8192,
            pricing_per_1m_input=0.0, pricing_per_1m_output=0.0,
        ),
        ModelInfo(
            id="deepseek/deepseek-chat-v3-0324:free", name="DeepSeek V3 (free)",
            provider="openrouter", context_window=163840,
            supports_streaming=True, supports_structured=True, max_output_tokens=8192,
            pricing_per_1m_input=0.0, pricing_per_1m_output=0.0,
        ),
        ModelInfo(
            id="openai/gpt-4o-mini", name="GPT-4o mini",
            provider="openrouter", context_window=128000,
            supports_streaming=True, supports_structured=True, max_output_tokens=16384,
            pricing_per_1m_input=0.15, pricing_per_1m_output=0.60,
        ),
        ModelInfo(
            id="anthropic/claude-3.5-sonnet", name="Claude 3.5 Sonnet",
            provider="openrouter", context_window=200000,
            supports_streaming=True, supports_structured=True, max_output_tokens=8192,
            pricing_per_1m_input=3.00, pricing_per_1m_output=15.00,
        ),
    ]
