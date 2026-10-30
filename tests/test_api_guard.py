"""Tests for the API key guard and per-IP rate limit (services/guard.py).

The guards are wired into /generate (key + rate limit) and /download (key
only). Read-only endpoints (/status, /files, /api/health) must stay open so
the public demo keeps polling even when a key is configured.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.api as api
from services import guard


@pytest.fixture()
def client(monkeypatch):
    async def fake_start(prompt, base_run_id=None):
        return "run123"

    monkeypatch.setattr(api, "start_generation", fake_start)
    monkeypatch.delenv("API_KEY", raising=False)
    guard.reset_rate_limiter()
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_generate_open_when_no_api_key(client, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    r = client.post("/generate", json={"prompt": "x"})
    assert r.status_code == 200
    assert r.json()["run_id"] == "run123"


def test_generate_401_without_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    r = client.post("/generate", json={"prompt": "x"})
    assert r.status_code == 401
    assert "API key" in r.json()["detail"]


def test_generate_401_wrong_key(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    r = client.post("/generate", json={"prompt": "x"}, headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_generate_200_with_valid_header(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    r = client.post("/generate", json={"prompt": "x"}, headers={"X-API-Key": "secret"})
    assert r.status_code == 200


def test_download_key_via_query_param(client, monkeypatch, tmp_path):
    # The ZIP link is a plain <a href>, so the key must be passable as a
    # query param; without it the download is rejected.
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "generated_projects").mkdir()
    (tmp_path / "generated_projects" / "run123.zip").write_bytes(b"PK\x03\x04")

    r = client.get("/download/run123")
    assert r.status_code == 401
    r = client.get("/download/run123?api_key=secret")
    assert r.status_code == 200
    assert r.content.startswith(b"PK")


def test_rate_limit_blocks_after_max(client, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_MAX", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW", "600")
    assert client.post("/generate", json={"prompt": "x"}).status_code == 200
    assert client.post("/generate", json={"prompt": "x"}).status_code == 200
    r = client.post("/generate", json={"prompt": "x"})
    assert r.status_code == 429
    assert "Rate limit" in r.json()["detail"]


def test_readonly_endpoints_stay_open_with_key(client, monkeypatch):
    # Even with a key configured, polling endpoints must not 401 - they are
    # scoped by unguessable run ids.
    monkeypatch.setenv("API_KEY", "secret")
    assert client.get("/api/health").status_code == 200
    assert client.get("/status/whatever").status_code == 404  # not 401
    assert client.get("/files/whatever").status_code == 404  # not 401


def test_window_expiry_frees_the_bucket(client, monkeypatch):
    # Simulate time passing: backdate the existing entries, then a new call
    # must be allowed again.
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_MAX", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW", "600")
    assert client.post("/generate", json={"prompt": "x"}).status_code == 200
    assert client.post("/generate", json={"prompt": "x"}).status_code == 429
    bucket = guard._rate_buckets["testclient"]
    for i in range(len(bucket)):
        bucket[i] -= 601
    assert client.post("/generate", json={"prompt": "x"}).status_code == 200
