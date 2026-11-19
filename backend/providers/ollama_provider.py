import os
from typing import List, Optional, AsyncIterator

from providers.base import BaseProvider, GenerationRequest, GenerationResponse, ModelInfo
from providers.errors import ProviderError, ErrorCategory, classify_error
from providers.deepseek_provider import OpenAICompatibleProvider


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama local LLM provider (no API key required)."""

    _provider_name = "ollama"
    _display_name = "Ollama (Local)"
    _api_key_env = "OLLAMA_API_KEY"
    _base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    _default_model = os.getenv("OLLAMA_MODEL", "llama3:8b")
    _requires_key = False
    _models = [
        ModelInfo(id="llama3:8b", name="Llama 3 8B", provider="ollama",
                  context_window=8192, supports_streaming=True, supports_structured=False,
                  max_output_tokens=4096),
        ModelInfo(id="llama3:70b", name="Llama 3 70B", provider="ollama",
                  context_window=8192, supports_streaming=True, supports_structured=False,
                  max_output_tokens=4096),
        ModelInfo(id="qwen2.5-coder:7b", name="Qwen 2.5 Coder 7B", provider="ollama",
                  context_window=32768, supports_streaming=True, supports_structured=False,
                  max_output_tokens=8192),
        ModelInfo(id="deepseek-coder:6.7b", name="DeepSeek Coder 6.7B", provider="ollama",
                  context_window=16384, supports_streaming=True, supports_structured=False,
                  max_output_tokens=8192),
    ]

    def is_available(self) -> bool:
        # Ollama is local - check if server is reachable
        # For UI purposes, we just check if the base_url is set
        # Actual availability is checked on first call
        return True

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        try:
            return await super().generate(request)
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(
                f"Ollama request failed. Ensure Ollama is running at {self._base_url}. Error: {e}",
                ErrorCategory.PROVIDER_OUTAGE,
                retryable=False,
            )

    async def stream_generate(self, request: GenerationRequest) -> AsyncIterator[str]:
        try:
            async for chunk in super().stream_generate(request):
                yield chunk
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(
                f"Ollama stream failed. Ensure Ollama is running at {self._base_url}. Error: {e}",
                ErrorCategory.PROVIDER_OUTAGE,
                retryable=False,
            )