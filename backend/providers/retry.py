import asyncio
import random
import time
from typing import Optional, Callable, Awaitable, TypeVar, Any
from providers.errors import ProviderError, ErrorCategory

T = TypeVar('T')


class RetryPolicy:
    """
    Bounded exponential backoff with jitter for transient failures.
    Does not retry non-retryable errors (auth, quota exhausted, invalid model).
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter_factor: float = 0.25,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter_factor = jitter_factor

    def should_retry(self, error: ProviderError, attempt: int) -> bool:
        if attempt >= self.max_retries:
            return False
        return error.retryable

    def get_delay(self, error: ProviderError, attempt: int) -> float:
        """Calculate delay for this attempt."""
        # Honor retry-after if provided
        if error.retry_after is not None:
            delay = min(error.retry_after, self.max_delay)
        else:
            delay = min(self.base_delay * (2 ** attempt), self.max_delay)

        # Add jitter
        jitter = delay * self.jitter_factor * random.random()
        return delay + jitter

    async def execute_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        on_retry: Optional[Callable[[ProviderError, int, float], Any]] = None,
    ) -> T:
        """
        Execute an async operation with retry logic.
        
        on_retry is called before each retry with (error, attempt, delay).
        """
        last_error: Optional[ProviderError] = None

        for attempt in range(self.max_retries + 1):
            try:
                return await operation()
            except Exception as e:
                if isinstance(e, ProviderError):
                    error = e
                else:
                    error = ProviderError(
                        str(e), ErrorCategory.UNKNOWN, retryable=False
                    )

                last_error = error

                if not self.should_retry(error, attempt):
                    raise error

                delay = self.get_delay(error, attempt)
                if on_retry:
                    on_retry(error, attempt, delay)

                await asyncio.sleep(delay)

        # Should not reach here, but just in case
        raise last_error or RuntimeError("Retry loop exhausted")


def is_retriable(category: ErrorCategory) -> bool:
    """Check if an error category is retriable."""
    return category in (
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.NETWORK_TIMEOUT,
        ErrorCategory.PROVIDER_OUTAGE,
    )


def is_quota_error(category: ErrorCategory) -> bool:
    """Check if an error category indicates quota is exhausted (non-retryable)."""
    return category in (
        ErrorCategory.QUOTA_EXHAUSTED,
        ErrorCategory.AUTH_ERROR,
    )