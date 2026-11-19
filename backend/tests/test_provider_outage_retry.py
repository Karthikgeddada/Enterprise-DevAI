"""Provider-outage resilience: 5xx/demand-spike errors must classify as
retryable and generate_response must retry them instead of failing a run.

This reproduces the live incident: Gemini returned
"503 UNAVAILABLE ... high demand ... try again later" during a demand
spike and the architect stage failed the whole run instantly.
"""
import pytest

from config import llm_config
from providers.errors import ErrorCategory, ProviderError, classify_error


# The exact error surface the live run logged.
LIVE_503 = (
    "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is "
    "currently experiencing high demand. Spikes in demand are usually "
    "temporary. Please try again later.', 'status': 'UNAVAILABLE'}}"
)


def test_live_gemini_503_classifies_retryable():
    err = classify_error(Exception(LIVE_503))
    assert err.category == ErrorCategory.PROVIDER_OUTAGE
    assert err.retryable is True
    assert err.status_code == 503


def test_overload_wording_is_retryable_without_status():
    err = classify_error(Exception("The model is overloaded, try again soon"))
    assert err.category == ErrorCategory.PROVIDER_OUTAGE
    assert err.retryable is True


def test_auth_error_still_non_retryable():
    err = classify_error(Exception("401 unauthorized: invalid API key"))
    assert err.category == ErrorCategory.AUTH_ERROR
    assert err.retryable is False


def test_groq_style_503_with_code_attr():
    class E(Exception):
        code = 503
    err = classify_error(E("service unavailable"))
    assert err.category == ErrorCategory.PROVIDER_OUTAGE
    assert err.retryable is True


# ------------------------------------------- generate_response retry
class _Resp:
    def __init__(self, content):
        self.content = content


def _fast_outage(n):
    return ProviderError(
        f"503 UNAVAILABLE (simulated {n})",
        ErrorCategory.PROVIDER_OUTAGE,
        retryable=True,
        retry_after=0.05,  # keep tests fast; honors the RetryPolicy contract
    )


@pytest.fixture()
def gemini_env(monkeypatch):
    monkeypatch.setattr(llm_config, "LLM_PROVIDER", "gemini")

    calls = {"n": 0}

    class FakeProvider:
        async def generate(self, request):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise _fast_outage(calls["n"])
            return _Resp("recovered output")

    monkeypatch.setattr("providers.gemini_provider.GeminiProvider", FakeProvider)
    return calls


def test_gemini_branch_retries_outage_then_succeeds(gemini_env):
    import asyncio

    result = asyncio.run(llm_config.generate_response("hello"))
    assert result == "recovered output"
    assert gemini_env["n"] == 3  # 2 failures + 1 success


def test_gemini_branch_exhausts_retries_with_same_error_surface(monkeypatch):
    import asyncio

    monkeypatch.setattr(llm_config, "LLM_PROVIDER", "gemini")

    class AlwaysDown:
        async def generate(self, request):
            raise _fast_outage(0)

    monkeypatch.setattr("providers.gemini_provider.GeminiProvider", AlwaysDown)

    with pytest.raises(Exception, match="Gemini API error"):
        asyncio.run(llm_config.generate_response("hello"))
