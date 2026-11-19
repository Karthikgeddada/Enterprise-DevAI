import os
from typing import List, Optional

from providers.base import ModelInfo
from providers.deepseek_provider import OpenAICompatibleProvider


class QwenProvider(OpenAICompatibleProvider):
    """Qwen-compatible hosted API provider (DashScope / OpenAI-compatible endpoint)."""

    _provider_name = "qwen"
    _display_name = "Qwen (Alibaba)"
    _api_key_env = "QWEN_API_KEY"
    _base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    _default_model = os.getenv("QWEN_MODEL", "qwen-plus")
    _models = [
        ModelInfo(id="qwen-plus", name="Qwen Plus", provider="qwen",
                  context_window=131072, supports_streaming=True, supports_structured=True,
                  max_output_tokens=8192, pricing_per_1m_input=0.40, pricing_per_1m_output=1.20),
        ModelInfo(id="qwen-turbo", name="Qwen Turbo", provider="qwen",
                  context_window=1000000, supports_streaming=True, supports_structured=True,
                  max_output_tokens=8192, pricing_per_1m_input=0.05, pricing_per_1m_output=0.20),
        ModelInfo(id="qwen-max", name="Qwen Max", provider="qwen",
                  context_window=32768, supports_streaming=True, supports_structured=True,
                  max_output_tokens=8192, pricing_per_1m_input=2.50, pricing_per_1m_output=10.00),
        ModelInfo(id="qwen-coder-turbo", name="Qwen Coder Turbo", provider="qwen",
                  context_window=131072, supports_streaming=True, supports_structured=True,
                  max_output_tokens=8192, pricing_per_1m_input=0.20, pricing_per_1m_output=0.60),
    ]