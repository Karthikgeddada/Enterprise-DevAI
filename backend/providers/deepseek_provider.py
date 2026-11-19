import os
from typing import List, Optional, AsyncIterator

from providers.base import BaseProvider, GenerationRequest, GenerationResponse, ModelInfo
from providers.errors import ProviderError, ErrorCategory, classify_error


class OpenAICompatibleProvider(BaseProvider):
    """
    Base for providers that use the OpenAI-compatible API format.
    Subclasses configure base_url, api_key env var, and model list.
    """

    _provider_name = "openai_compatible"
    _display_name = "OpenAI Compatible"
    _api_key_env = "API_KEY"
    _base_url = ""
    _default_model = ""
    _models: List[ModelInfo] = []

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def display_name(self) -> str:
        return self._display_name

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self._api_key = api_key or self._get_api_key()
        self._model = default_model or self._default_model

    def _get_api_key(self) -> Optional[str]:
        return os.getenv(self._api_key_env)

    def is_available(self) -> bool:
        return bool(self._api_key) or not self._requires_key

    def get_models(self) -> List[ModelInfo]:
        return list(self._models)

    _requires_key: bool = True

    def _get_client(self):
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=self._api_key or "dummy", base_url=self._base_url)

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not self.is_available():
            raise ProviderError(
                f"{self._display_name} API key not configured. Set {self._api_key_env} in secrets or .env.",
                ErrorCategory.AUTH_ERROR,
                retryable=False,
            )
        try:
            client = self._get_client()
            messages = list(request.messages)
            if request.system_prompt:
                messages = [{"role": "system", "content": request.system_prompt}] + messages

            kwargs = {
                "model": request.model or self._model,
                "messages": messages,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            }
            if request.response_format:
                kwargs["response_format"] = request.response_format

            response = await client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            usage = None
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            return GenerationResponse(
                content=content,
                model=request.model or self._model,
                provider=self.name,
                usage=usage,
                finish_reason=response.choices[0].finish_reason,
                raw=response,
            )
        except ProviderError:
            raise
        except Exception as e:
            raise classify_error(e)

    async def stream_generate(self, request: GenerationRequest) -> AsyncIterator[str]:
        if not self.is_available():
            raise ProviderError(
                f"{self._display_name} API key not configured.",
                ErrorCategory.AUTH_ERROR,
                retryable=False,
            )
        try:
            client = self._get_client()
            messages = list(request.messages)
            if request.system_prompt:
                messages = [{"role": "system", "content": request.system_prompt}] + messages

            kwargs = {
                "model": request.model or self._model,
                "messages": messages,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "stream": True,
            }

            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except ProviderError:
            raise
        except Exception as e:
            raise classify_error(e)


class DeepSeekProvider(OpenAICompatibleProvider):
    _provider_name = "deepseek"
    _display_name = "DeepSeek"
    _api_key_env = "DEEPSEEK_API_KEY"
    _base_url = "https://api.deepseek.com/v1"
    _default_model = "deepseek-chat"
    _models = [
        ModelInfo(id="deepseek-chat", name="DeepSeek Chat", provider="deepseek",
                  context_window=64000, supports_streaming=True, supports_structured=True,
                  max_output_tokens=8192, pricing_per_1m_input=0.14, pricing_per_1m_output=0.28),
        ModelInfo(id="deepseek-reasoner", name="DeepSeek Reasoner", provider="deepseek",
                  context_window=64000, supports_streaming=True, supports_structured=False,
                  max_output_tokens=8192, pricing_per_1m_input=0.55, pricing_per_1m_output=2.19),
    ]