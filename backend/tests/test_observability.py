"""Tests for observability (services/observability.py, GET /stats)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.api as api
from services import run_store
from services.observability import compute_stats, _classify_failure


@pytest.fixture()
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNS_DB", str(tmp_path / "runs.db"))
    run_store.reset_broken()
    yield run_store
    run_store.reset_broken()


def _seed_ok(store, rid, started, completed, logs=None):
    store.save(
        rid, "completed",
        logs or ["Run started.", "Done. Project packaged as ZIP."],
        [
            {"path": "main.py", "content": "a\nb"},
            {"path": "README.md", "content": "# x"},
        ],
        "build an app",
        started_at=started,
        completed_at=completed,
    )


def _seed_failed(store, rid, failed_line):
    store.save(rid, "failed", ["Run started.", f"FAILED: {failed_line}"], [], "build an app")


def test_stats_counts_and_averages(store):
    _seed_ok(store, "a", 100.0, 110.0)
    _seed_ok(store, "b", 200.0, 230.0)  # avg duration = (10 + 30) / 2 = 20
    _seed_failed(store, "c", "Gemini API error: 503 UNAVAILABLE high demand")

    s = compute_stats()
    assert s["runs"]["total"] == 3
    assert s["runs"]["by_status"] == {"completed": 2, "failed": 1}
    assert s["builds"]["avg_duration_seconds"] == 20.0
    assert s["builds"]["avg_files"] == 1.3  # (2+2+0)/3, rounded to 1 decimal
    assert s["builds"]["self_heals_total"] == 0


def test_stats_failure_causes(store):
    _seed_failed(store, "o", "Gemini API error: 503 UNAVAILABLE ... try again later")
    _seed_failed(store, "r", "Groq API Error: rate_limit exceeded (429)")
    _seed_failed(store, "u", "Coder returned no usable files")

    s = compute_stats()
    assert s["runs"]["failure_causes"] == {"outage": 1, "rate_limit": 1, "malformed": 1}


def test_stats_self_heals_and_languages(store):
    _seed_ok(store, "h", 0.0, 1.0, logs=[
        "Run started.",
        "Coder failed (x); retrying (attempt 2/3)...",
        "Done. Project packaged as ZIP.",
    ])
    s = compute_stats()
    assert s["builds"]["self_heals_total"] == 1
    assert s["languages"]["py"] == {"files": 1, "lines": 2}


def test_stats_empty_store(store):
    s = compute_stats()
    assert s["runs"]["total"] == 0
    assert s["builds"]["avg_duration_seconds"] is None
    assert s["languages"] == {}


def test_classify_failure_helper():
    assert _classify_failure(["FAILED: 401 unauthorized"]) == "auth"
    assert _classify_failure(["FAILED: something weird"]) == "other"
    assert _classify_failure(["no failures here"]) == "unknown"


# ------------------------------------------------------------ endpoint
def test_stats_endpoint(store):
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)

    _seed_ok(store, "e1", 100.0, 145.0)
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["runs"]["total"] == 1
    assert body["builds"]["avg_duration_seconds"] == 45.0
