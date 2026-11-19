import os
from typing import Dict, List, Optional

from providers.base import BaseProvider, ProviderInfo, ModelInfo
from providers.errors import ProviderError, ErrorCategory
from providers.retry import RetryPolicy


class ProviderRegistry:
    """
    Central registry for all LLM providers.
    Manages provider instances, model selection, and fallback chains.
    """

    def __init__(self):
        self._providers: Dict[str, BaseProvider] = {}
        self._retry_policy = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=30.0)
        self._fallback_chain: List[str] = []
        self._register_all()

    def _register_all(self):
        """Register all known providers. Safe to call even if deps are missing."""
        # OpenRouter (preferred: one key, many models)
        try:
            from providers.openrouter_provider import OpenRouterProvider
            openrouter = OpenRouterProvider()
            self._providers["openrouter"] = openrouter
        except Exception:
            pass

        # Gemini
        try:
            from providers.gemini_provider import GeminiProvider
            gemini = GeminiProvider()
            self._providers["gemini"] = gemini
        except Exception:
            pass

        # DeepSeek
        try:
            from providers.deepseek_provider import DeepSeekProvider
            deepseek = DeepSeekProvider()
            self._providers["deepseek"] = deepseek
        except Exception:
            pass

        # Qwen
        try:
            from providers.qwen_provider import QwenProvider
            qwen = QwenProvider()
            self._providers["qwen"] = qwen
        except Exception:
            pass

        # Ollama (always register - it's local)
        try:
            from providers.ollama_provider import OllamaProvider
            ollama = OllamaProvider()
            self._providers["ollama"] = ollama
        except Exception:
            pass

        # Set fallback chain: prefer OpenRouter, then other hosted providers, then local
        self._fallback_chain = [p for p in ["openrouter", "gemini", "deepseek", "qwen", "ollama"] if p in self._providers]

    def get_provider(self, name: str) -> Optional[BaseProvider]:
        return self._providers.get(name)

    def get_available_providers(self) -> List[ProviderInfo]:
        """Return info about all registered providers."""
        result = []
        for name, provider in self._providers.items():
            result.append(ProviderInfo(
                name=name,
                display_name=provider.display_name,
                models=provider.get_models(),
                available=provider.is_available(),
                requires_api_key=provider.is_available() and name != "ollama",
            ))
        return result

    def get_provider_by_name(self, name: str) -> Optional[BaseProvider]:
        return self._providers.get(name)

    def get_all_models(self) -> List[ModelInfo]:
        """Return all models from all providers."""
        models = []
        for provider in self._providers.values():
            models.extend(provider.get_models())
        return models

    def get_fallback_chain(self) -> List[str]:
        """Return the configured fallback chain of provider names."""
        return list(self._fallback_chain)

    def set_fallback_chain(self, chain: List[str]):
        """Configure the fallback chain."""
        self._fallback_chain = [p for p in chain if p in self._providers]

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    def get_default_provider(self) -> Optional[BaseProvider]:
        """Return the first available provider."""
        for name in self._fallback_chain:
            provider = self._providers.get(name)
            if provider and provider.is_available():
                return provider
        return None

    def get_default_model(self, provider_name: Optional[str] = None) -> Optional[str]:
        """Return default model for a provider (or the first available provider)."""
        if provider_name:
            provider = self._providers.get(provider_name)
            if provider and provider.get_models():
                return provider.get_models()[0].id
        provider = self.get_default_provider()
        if provider and provider.get_models():
            return provider.get_models()[0].id
        return None


# Singleton instance
_registry: Optional[ProviderRegistry] = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry