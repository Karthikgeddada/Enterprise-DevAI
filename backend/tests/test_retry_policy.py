import asyncio
import pytest
from providers.retry import RetryPolicy, is_retriable, is_quota_error
from providers.errors import ProviderError, ErrorCategory


class TestRetryPolicy:

    def test_retriable_categories(self):
        assert is_retriable(ErrorCategory.RATE_LIMIT)
        assert is_retriable(ErrorCategory.NETWORK_TIMEOUT)
        assert is_retriable(ErrorCategory.PROVIDER_OUTAGE)

    def test_non_retriable_categories(self):
        assert not is_retriable(ErrorCategory.AUTH_ERROR)
        assert not is_retriable(ErrorCategory.QUOTA_EXHAUSTED)
        assert not is_retriable(ErrorCategory.INVALID_MODEL)

    def test_quota_error_detection(self):
        assert is_quota_error(ErrorCategory.QUOTA_EXHAUSTED)
        assert is_quota_error(ErrorCategory.AUTH_ERROR)
        assert not is_quota_error(ErrorCategory.RATE_LIMIT)

    def test_should_retry_retriable(self):
        policy = RetryPolicy(max_retries=3)
        error = ProviderError("rate limit", ErrorCategory.RATE_LIMIT, retryable=True)
        assert policy.should_retry(error, 0)
        assert policy.should_retry(error, 1)
        assert policy.should_retry(error, 2)
        assert not policy.should_retry(error, 3)

    def test_should_not_retry_non_retriable(self):
        policy = RetryPolicy(max_retries=3)
        error = ProviderError("auth error", ErrorCategory.AUTH_ERROR, retryable=False)
        assert not policy.should_retry(error, 0)

    def test_get_delay_exponential(self):
        policy = RetryPolicy(base_delay=1.0, max_delay=30.0)
        error = ProviderError("timeout", ErrorCategory.NETWORK_TIMEOUT, retryable=True)
        delay0 = policy.get_delay(error, 0)
        delay1 = policy.get_delay(error, 1)
        delay2 = policy.get_delay(error, 2)
        # Should increase (with jitter)
        assert delay0 < delay2
        assert delay1 >= 1.0

    def test_get_delay_honors_retry_after(self):
        policy = RetryPolicy(max_delay=60.0)
        error = ProviderError("rate limited", ErrorCategory.RATE_LIMIT, retryable=True, retry_after=10.0)
        delay = policy.get_delay(error, 0)
        assert delay >= 10.0

    def test_execute_with_retry_success_first_try(self):
        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            return "success"

        result = asyncio.run(policy.execute_with_retry(operation))
        assert result == "success"
        assert call_count == 1

    def test_execute_with_retry_succeeds_on_retry(self):
        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ProviderError("timeout", ErrorCategory.NETWORK_TIMEOUT, retryable=True)
            return "success"

        result = asyncio.run(policy.execute_with_retry(operation))
        assert result == "success"
        assert call_count == 2

    def test_execute_no_retry_on_non_retriable(self):
        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            raise ProviderError("auth", ErrorCategory.AUTH_ERROR, retryable=False)

        with pytest.raises(ProviderError):
            asyncio.run(policy.execute_with_retry(operation))
        assert call_count == 1

    def test_execute_exhausts_retries(self):
        policy = RetryPolicy(max_retries=2, base_delay=0.01)
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            raise ProviderError("timeout", ErrorCategory.NETWORK_TIMEOUT, retryable=True)

        with pytest.raises(ProviderError):
            asyncio.run(policy.execute_with_retry(operation))
        # max_retries=2 means 3 total attempts (initial + 2 retries)
        assert call_count == 3