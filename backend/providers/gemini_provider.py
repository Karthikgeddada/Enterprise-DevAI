import os
import re
from typing import List, Optional, AsyncIterator

from providers.base import BaseProvider, GenerationRequest, GenerationResponse, ModelInfo
from providers.errors import ProviderError, ErrorCategory, classify_error


class GeminiProvider(BaseProvider):
    """Google Gemini API provider."""

    DEFAULT_MODELS = [
        ModelInfo(
            id="gemini-3.5-flash-lite", name="Gemini 3.5 Flash Lite (latest, cheapest)",
            provider="gemini", context_window=1048576,
            supports_streaming=True, supports_structured=True, max_output_tokens=8192,
            pricing_per_1m_input=0.075, pricing_per_1m_output=0.30,
        ),
        ModelInfo(
            id="gemini-2.0-flash",
            name="Gemini 2.0 Flash",
            provider="gemini",
            context_window=1048576,
            supports_streaming=True,
            supports_structured=True,
            max_output_tokens=8192,
            pricing_per_1m_input=0.10,
            pricing_per_1m_output=0.40,
        ),
        ModelInfo(
            id="gemini-2.0-flash-lite",
            name="Gemini 2.0 Flash Lite",
            provider="gemini",
            context_window=1048576,
            supports_streaming=True,
            supports_structured=True,
            max_output_tokens=8192,
            pricing_per_1m_input=0.075,
            pricing_per_1m_output=0.30,
        ),
        ModelInfo(
            id="gemini-1.5-pro",
            name="Gemini 1.5 Pro",
            provider="gemini",
            context_window=2097152,
            supports_streaming=True,
            supports_structured=True,
            max_output_tokens=8192,
            pricing_per_1m_input=1.25,
            pricing_per_1m_output=5.00,
        ),
    ]

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def display_name(self) -> str:
        return "Google Gemini"

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self._api_key = api_key or self._get_api_key()
        self._default_model = default_model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

    def _get_api_key(self) -> Optional[str]:
        return os.getenv("GEMINI_API_KEY")

    def is_available(self) -> bool:
        return bool(self._api_key)

    def get_models(self) -> List[ModelInfo]:
        return self.DEFAULT_MODELS.copy()

    def _get_client(self):
        from google import genai
        return genai.Client(api_key=self._api_key)

    def _recommended_model(self, err: Exception) -> Optional[str]:
        """Google's 404s often name the replacement: '...use models/<id>...'"""
        m = re.search(r"use models/([\w.\-]+)", str(err))
        return m.group(1) if m else None

    def _discover_model(self) -> Optional[str]:
        """Pick the cheapest available Gemini flash model via ListModels.

        Google retires/renames model aliases over time; this keeps the app
        working when a configured id disappears (404 INVALID_MODEL).
        """
        preferred = ("gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash-lite")
        try:
            client = self._get_client()
            available = [m.name.replace("models/", "") for m in client.models.list()]
        except Exception:
            return None
        for cand in preferred:
            if cand in available:
                return cand
        for name in available:
            if "gemini" in name and "flash-lite" in name:
                return name
        for name in available:
            if "gemini" in name and "flash" in name:
                return name
        return None

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not self.is_available():
            raise ProviderError(
                "GEMINI_API_KEY not configured. Set it in Streamlit Secrets or .env file.",
                ErrorCategory.AUTH_ERROR,
                retryable=False,
            )
        try:
            client = self._get_client()
            # Build content from messages
            contents = []
            system_instruction = request.system_prompt
            for msg in request.messages:
                role = msg.get("role", "user")
                text = msg.get("content", "")
                if role == "system" and not system_instruction:
                    system_instruction = text
                elif role == "assistant":
                    contents.append({"role": "model", "parts": [{"text": text}]})
                else:
                    contents.append({"role": "user", "parts": [{"text": text}]})

            config = {
                "temperature": request.temperature,
                "max_output_tokens": request.max_tokens,
            }
            if request.response_format:
                config["response_mime_type"] = "application/json"
            if system_instruction:
                config["system_instruction"] = system_instruction

            used_model = request.model
            try:
                response = await client.aio.models.generate_content(
                    model=used_model,
                    contents=contents,
                    config=config,
                )
            except Exception as first_err:
                first = classify_error(first_err)
                if first.category != ErrorCategory.INVALID_MODEL:
                    raise first
                # Configured model id is gone/renamed — prefer the replacement
                # Google names in the error, else discover one from ListModels.
                used_model = self._recommended_model(first_err) or self._discover_model() or self._default_model
                if used_model == request.model:
                    raise first
                response = await client.aio.models.generate_content(
                    model=used_model,
                    contents=contents,
                    config=config,
                )
                self._default_model = used_model
            content = response.text or ""
            usage = None
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                um = response.usage_metadata
                usage = {
                    "prompt_tokens": getattr(um, 'prompt_token_count', 0) or 0,
                    "completion_tokens": getattr(um, 'candidates_token_count', 0) or 0,
                    "total_tokens": getattr(um, 'total_token_count', 0) or 0,
                }
            return GenerationResponse(
                content=content,
                model=used_model,
                provider=self.name,
                usage=usage,
                finish_reason=getattr(response, 'finish_reason', None),
                raw=response,
            )
        except ProviderError:
            raise
        except Exception as e:
            raise classify_error(e)

    async def stream_generate(self, request: GenerationRequest) -> AsyncIterator[str]:
        if not self.is_available():
            raise ProviderError(
                "GEMINI_API_KEY not configured.",
                ErrorCategory.AUTH_ERROR,
                retryable=False,
            )
        try:
            client = self._get_client()
            contents = []
            system_instruction = request.system_prompt
            for msg in request.messages:
                role = msg.get("role", "user")
                text = msg.get("content", "")
                if role == "system" and not system_instruction:
                    system_instruction = text
                elif role == "assistant":
                    contents.append({"role": "model", "parts": [{"text": text}]})
                else:
                    contents.append({"role": "user", "parts": [{"text": text}]})

            config = {
                "temperature": request.temperature,
                "max_output_tokens": request.max_tokens,
            }
            if system_instruction:
                config["system_instruction"] = system_instruction

            response = await client.aio.models.generate_content_stream(
                model=request.model,
                contents=contents,
                config=config,
            )
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except ProviderError:
            raise
        except Exception as e:
            raise classify_error(e)