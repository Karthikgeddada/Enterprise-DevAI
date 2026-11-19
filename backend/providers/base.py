from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, AsyncIterator

from providers.errors import ProviderError, ErrorCategory


@dataclass
class GenerationRequest:
    """Standardized request to a provider."""
    messages: List[Dict[str, str]]
    model: str
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout: float = 120.0
    stream: bool = False
    response_format: Optional[Dict[str, Any]] = None  # e.g. {"type": "json_object"}
    system_prompt: Optional[str] = None


@dataclass
class GenerationResponse:
    """Standardized response from a provider."""
    content: str
    model: str
    provider: str
    usage: Optional[Dict[str, int]] = None  # {"prompt_tokens": N, "completion_tokens": M, "total_tokens": K}
    finish_reason: Optional[str] = None
    raw: Any = None


@dataclass
class ModelInfo:
    """Metadata about a model offered by a provider."""
    id: str
    name: str
    provider: str
    context_window: int = 0
    supports_streaming: bool = True
    supports_structured: bool = False
    max_output_tokens: int = 4096
    pricing_per_1m_input: float = 0.0
    pricing_per_1m_output: float = 0.0


@dataclass
class ProviderInfo:
    """Metadata about a provider."""
    name: str
    display_name: str
    models: List[ModelInfo] = field(default_factory=list)
    available: bool = False
    requires_api_key: bool = True


class BaseProvider(ABC):
    """Abstract interface that all providers must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable provider name."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and available."""
        pass

    @abstractmethod
    def get_models(self) -> List[ModelInfo]:
        """Return list of models offered by this provider."""
        pass

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Generate a response (non-streaming)."""
        pass

    @abstractmethod
    async def stream_generate(self, request: GenerationRequest) -> AsyncIterator[str]:
        """Stream response tokens. Yields content chunks."""
        pass

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD for a request. Returns 0.0 if pricing unknown."""
        for m in self.get_models():
            if m.id == model:
                return (input_tokens / 1_000_000 * m.pricing_per_1m_input +
                        output_tokens / 1_000_000 * m.pricing_per_1m_output)
        return 0.0