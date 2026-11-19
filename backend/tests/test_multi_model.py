"""Tests for multi-model (Feature 8): per-run provider choice threaded via
a ContextVar from POST /generate through generate_response, plus GET /models.
"""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.api as api
from config import llm_config
from config.llm_config import provider_choices, set_run_provider, get_run_provider


class _Resp:
    def __init__(self, content):
        self.content = content


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


# ---------------------------------------------------------- choices
def test_provider_choices_auto_always_first(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(llm_config, "LLM_PROVIDER", "gemini")
    choices = provider_choices()
    assert choices[0] == {"id": "auto", "label": "Auto (gemini)"}


def test_provider_choices_list_configured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    choices = {c["id"] for c in provider_choices()}
    assert {"auto", "gemini", "openrouter"} <= choices


# ---------------------------------------------------------- endpoints
def test_models_endpoint(client):
    r = client.get("/models")
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["id"] == "auto"


def test_generate_rejects_unknown_provider(client):
    r = client.post("/generate", json={"prompt": "x", "provider": "nope"})
    assert r.status_code == 400
    assert "Unknown provider" in r.json()["detail"]


# ------------------------------------------- contextvar threading
def test_generate_response_honors_override(monkeypatch):
    monkeypatch.setattr(llm_config, "LLM_PROVIDER", "openrouter")

    seen = []

    class FakeGemini:
        async def generate(self, request):
            seen.append("gemini")
            return _Resp("ok")

    monkeypatch.setattr("providers.gemini_provider.GeminiProvider", FakeGemini)

    async def scenario():
        # Inside a task created after set_run_provider, the override wins.
        set_run_provider("gemini")
        return await llm_config.generate_response("hello")

    assert asyncio.run(scenario()) == "ok"
    assert seen == ["gemini"]
    # Cleared override falls back to the deployment default provider.
    set_run_provider("")
    assert get_run_provider() == ""


def test_contextvar_inherited_by_asyncio_task(monkeypatch):
    """The exact mechanism start_generation relies on: a ContextVar set
    before asyncio.create_task is visible inside the task."""
    monkeypatch.setattr(llm_config, "LLM_PROVIDER", "openrouter")

    class FakeGemini:
        async def generate(self, request):
            return _Resp("from-gemini")

    monkeypatch.setattr("providers.gemini_provider.GeminiProvider", FakeGemini)

    async def parent():
        set_run_provider("gemini")
        task = asyncio.create_task(llm_config.generate_response("hi"))
        return await task

    assert asyncio.run(parent()) == "from-gemini"
