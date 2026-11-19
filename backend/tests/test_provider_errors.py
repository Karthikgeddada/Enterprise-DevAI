import pytest
from providers.errors import classify_error, ProviderError, ErrorCategory


class TestProviderErrors:

    def test_auth_error(self):
        exc = Exception("Invalid API key")
        result = classify_error(exc)
        assert result.category == ErrorCategory.AUTH_ERROR
        assert not result.retryable

    def test_rate_limit_error(self):
        exc = Exception("rate_limit_exceeded")
        result = classify_error(exc)
        assert result.category == ErrorCategory.RATE_LIMIT
        assert result.retryable

    def test_rate_limit_with_status_code(self):
        class FakeError(Exception):
            status_code = 429
        exc = FakeError("Too many requests")
        result = classify_error(exc)
        assert result.category == ErrorCategory.RATE_LIMIT
        assert result.retryable

    def test_quota_exhausted(self):
        exc = Exception("daily quota exhausted")
        result = classify_error(exc)
        assert result.category == ErrorCategory.QUOTA_EXHAUSTED
        assert not result.retryable

    def test_billing_error(self):
        exc = Exception("insufficient billing quota")
        result = classify_error(exc)
        assert result.category == ErrorCategory.QUOTA_EXHAUSTED
        assert not result.retryable

    def test_invalid_model(self):
        exc = Exception("model not found")
        result = classify_error(exc)
        assert result.category == ErrorCategory.INVALID_MODEL
        assert not result.retryable

    def test_timeout(self):
        exc = Exception("Request timed out")
        result = classify_error(exc)
        assert result.category == ErrorCategory.NETWORK_TIMEOUT
        assert result.retryable

    def test_provider_outage_5xx(self):
        class FakeError(Exception):
            status_code = 503
        exc = FakeError("Service unavailable")
        result = classify_error(exc)
        assert result.category == ErrorCategory.PROVIDER_OUTAGE
        assert result.retryable

    def test_connection_error(self):
        exc = Exception("Connection refused")
        result = classify_error(exc)
        assert result.category == ErrorCategory.PROVIDER_OUTAGE
        assert result.retryable

    def test_malformed_response(self):
        exc = Exception("JSON decode error")
        result = classify_error(exc)
        assert result.category == ErrorCategory.MALFORMED_RESPONSE
        assert not result.retryable

    def test_unknown_error(self):
        exc = Exception("Something unexpected")
        result = classify_error(exc)
        assert result.category == ErrorCategory.UNKNOWN
        assert not result.retryable

    def test_retry_after_header(self):
        class FakeError(Exception):
            status_code = 429
            headers = {"retry-after": "5.0"}
        exc = FakeError("Rate limited")
        result = classify_error(exc)
        assert result.retry_after == 5.0