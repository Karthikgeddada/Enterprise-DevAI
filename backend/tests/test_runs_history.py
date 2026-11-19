"""Tests for the run-history dashboard (GET /runs) and prompt persistence.

The history panel lists past runs from the SQLite store; the prompt now
travels with every run so history rows are recognizable and continue-mode
survives restarts.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.api as api
from services import run_store
from services import generation_service as gs


@pytest.fixture()
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNS_DB", str(tmp_path / "runs.db"))
    run_store.reset_broken()
    yield run_store
    run_store.reset_broken()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _save(store, run_id, status, prompt, files):
    import time
    store.save(run_id, status, ["Run started."], files, prompt)
    time.sleep(0.01)  # distinct updated_at ordering


FILE = [{"path": "main.py", "content": "print('hi')"}]


def test_runs_endpoint_lists_newest_first(store, client):
    _save(store, "older", "completed", "build a todo api", FILE)
    _save(store, "newer", "failed", "build a chat app", [])

    r = client.get("/runs")
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert [x["run_id"] for x in runs] == ["newer", "older"]  # newest first
    assert runs[0]["prompt"] == "build a chat app"
    assert runs[0]["status"] == "failed"
    assert runs[1]["file_count"] == 1
    assert runs[1]["updated_at"] > 0


def test_runs_endpoint_empty(store, client):
    r = client.get("/runs")
    assert r.status_code == 200
    assert r.json() == {"runs": []}


def test_prompt_persisted_and_rehydrated(store, monkeypatch):
    gs._runs["hist1"] = {
        "status": "completed",
        "logs": ["Run started."],
        "files": FILE,
        "prompt": "build a url shortener",
    }
    gs._persist("hist1")

    loaded = run_store.load("hist1")
    assert loaded["prompt"] == "build a url shortener"

    # Rehydration path (server restart): _load keeps the prompt.
    del gs._runs["hist1"]
    run = gs._load("hist1")
    assert run is not None
    assert run["prompt"] == "build a url shortener"
    assert run["status"] == "completed"


def test_start_generation_seeds_prompt(store, monkeypatch):
    async def fake_pipeline(run_id, prompt, base_files=None):
        return None

    monkeypatch.setattr(gs, "_run_pipeline", fake_pipeline)
    import asyncio
    run_id = asyncio.run(gs.start_generation("build a calculator"))
    assert gs._runs[run_id]["prompt"] == "build a calculator"
    assert run_store.load(run_id)["prompt"] == "build a calculator"
