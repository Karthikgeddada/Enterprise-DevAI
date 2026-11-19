from enum import Enum
import re
from typing import Optional


class ErrorCategory(Enum):
    """Normalized provider error categories."""
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhaustured"
    AUTH_ERROR = "auth_error"
    INVALID_MODEL = "invalid_model"
    NETWORK_TIMEOUT = "network_timeout"
    PROVIDER_OUTAGE = "provider_outage"
    MALFORMED_RESPONSE = "malformed_response"
    CODING_FAILURE = "coding_failure"
    TEST_FAILURE = "test_failure"
    UNKNOWN = "unknown"


class ProviderError(Exception):
    """Base class for provider errors with category and retryability info."""

    def __init__(self, message: str, category: ErrorCategory, retryable: bool = False,
                 retry_after: Optional[float] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.retry_after = retry_after
        self.status_code = status_code


def classify_error(exc: Exception) -> ProviderError:
    """
    Classify a raw exception from a provider into a ProviderError.
    Handles common HTTP error patterns across providers.
    """
    msg = str(exc).lower()
    status_code = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)

    # google-genai and other SDKs often embed the HTTP status only in the
    # message text ("503 UNAVAILABLE. {'error': {'code': 503, ...}}");
    # recover it so 5xx responses classify as a retryable outage.
    if status_code is None:
        m = re.search(r"'code':\s*(\d{3})", str(exc)) or re.search(
            r"\b([45]\d\d)\s+[A-Z_]+", str(exc)
        )
        if m:
            try:
                status_code = int(m.group(1))
            except (ValueError, TypeError):
                pass

    # Authentication errors
    if status_code == 401 or 'invalid_api_key' in msg or 'unauthorized' in msg or 'invalid key' in msg or 'invalid api key' in msg:
        return ProviderError(str(exc), ErrorCategory.AUTH_ERROR, retryable=False, status_code=status_code)

    # Rate limit (transient)
    if status_code == 429 or 'rate_limit' in msg or 'rate limit' in msg or 'too many requests' in msg:
        retry_after = None
        if hasattr(exc, 'headers') and exc.headers:
            ra = exc.headers.get('retry-after')
            if ra:
                try:
                    retry_after = float(ra)
                except (ValueError, TypeError):
                    pass
        return ProviderError(str(exc), ErrorCategory.RATE_LIMIT, retryable=True, retry_after=retry_after, status_code=status_code)

    # Quota exhausted (not transient)
    if 'quota' in msg or 'billing' in msg or 'insufficient_quota' in msg or 'exhausted' in msg or 'daily' in msg:
        return ProviderError(str(exc), ErrorCategory.QUOTA_EXHAUSTED, retryable=False, status_code=status_code)

    # Invalid model
    if 'model' in msg and ('not found' in msg or 'invalid' in msg or 'unsupported' in msg):
        return ProviderError(str(exc), ErrorCategory.INVALID_MODEL, retryable=False, status_code=status_code)

    # Timeout
    if 'timeout' in msg or 'timed out' in msg or status_code == 408:
        return ProviderError(str(exc), ErrorCategory.NETWORK_TIMEOUT, retryable=True, status_code=status_code)

    # Provider outage (5xx, or explicit overload wording Google/OpenAI use
    # during demand spikes — often arrives with no structured status at all)
    if (status_code and 500 <= status_code < 600) or any(
        w in msg
        for w in (
            "unavailable",
            "overloaded",
            "overload",
            "high demand",
            "spikes in demand",
            "try again later",
        )
    ):
        return ProviderError(str(exc), ErrorCategory.PROVIDER_OUTAGE, retryable=True, status_code=status_code)

    if 'connection' in msg or 'unreachable' in msg or 'refused' in msg or 'reset' in msg:
        return ProviderError(str(exc), ErrorCategory.PROVIDER_OUTAGE, retryable=True, status_code=status_code)

    # Malformed response
    if 'json' in msg or 'parse' in msg or 'decode' in msg or 'malformed' in msg:
        return ProviderError(str(exc), ErrorCategory.MALFORMED_RESPONSE, retryable=False, status_code=status_code)

    return ProviderError(str(exc), ErrorCategory.UNKNOWN, retryable=False, status_code=status_code)