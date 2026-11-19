"""Tests for the scorecard (services/scorecard.py, GET /scorecard/<id>)
and the run-timing persistence that feeds its duration stat.
"""
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.api as api
from services import generation_service as gs
from services import run_store
from services.scorecard import compute_scorecard


FILES = [
    {"path": "main.py", "content": "a\nb\nc"},
    {"path": "tests/test_main.py", "content": "x"},
    {"path": "README.md", "content": "# readme"},
    {"path": "ARCHITECTURE.md", "content": "design"},
    {"path": "ARCHITECTURE.mmd", "content": "graph TD"},
]


def _run(**over):
    run = {
        "run_id": "sc1",
        "status": "completed",
        "prompt": "build a todo api",
        "files": FILES,
        "logs": [
            "Run started.",
            "Coder failed (boom); retrying (attempt 2/3)...",
            "Coder failed (boom2); retrying (attempt 3/3)...",
            "Done. Project packaged as ZIP.",
        ],
        "started_at": 100.0,
        "completed_at": 147.6,
    }
    run.update(over)
    return run


# ------------------------------------------------------- pure computation
def test_compute_scorecard_counts_and_languages():
    sc = compute_scorecard(_run())
    assert sc["file_count"] == 5
    assert sc["total_lines"] == 3 + 1 + 1 + 1 + 1
    assert sc["languages"]["py"] == {"files": 2, "lines": 4}
    assert sc["languages"]["md"]["files"] == 2
    # sorted by lines, py first
    assert list(sc["languages"])[0] == "py"
    assert sc["largest_file"] == {"path": "main.py", "lines": 3}


def test_compute_scorecard_quality_checks():
    sc = compute_scorecard(_run())
    assert sc["quality_checks"] == {
        "readme": True,
        "architecture_doc": True,
        "architecture_diagram": True,
        "tests": True,
    }


def test_compute_scorecard_self_heals_and_duration():
    sc = compute_scorecard(_run())
    assert sc["self_heals"] == 2
    assert sc["duration_seconds"] == 47.6


def test_compute_scorecard_missing_timing():
    sc = compute_scorecard(_run(started_at=None, completed_at=None))
    assert sc["duration_seconds"] is None


def test_compute_scorecard_empty_run():
    sc = compute_scorecard({"files": [], "logs": []})
    assert sc["file_count"] == 0
    assert sc["languages"] == {}
    assert sc["largest_file"] is None
    assert sc["duration_seconds"] is None


# ------------------------------------------------------------ endpoint
@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_scorecard_endpoint(client):
    gs._runs["sc1"] = _run()
    r = client.get("/scorecard/sc1")
    assert r.status_code == 200
    body = r.json()
    assert body["file_count"] == 5
    assert body["self_heals"] == 2
    assert body["duration_seconds"] == 47.6


def test_scorecard_endpoint_unknown_run(client):
    r = client.get("/scorecard/nope")
    assert r.status_code == 404


# ------------------------------------------------- timing persistence
@pytest.fixture()
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNS_DB", str(tmp_path / "runs.db"))
    run_store.reset_broken()
    yield run_store
    run_store.reset_broken()


def test_timing_roundtrip_through_store(store):
    gs._runs["sc2"] = _run()
    gs._persist("sc2")

    del gs._runs["sc2"]
    run = gs._load("sc2")
    assert run["started_at"] == 100.0
    assert run["completed_at"] == 147.6
    # duration survives restarts, so scorecards of old runs stay truthful
    assert compute_scorecard(run)["duration_seconds"] == 47.6


def test_timing_migration_from_old_schema(store, tmp_path):
    # A DB created before the timing columns existed.
    db = str(tmp_path / "runs.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE runs (
               run_id TEXT PRIMARY KEY, status TEXT NOT NULL, logs TEXT NOT NULL,
               files TEXT NOT NULL, prompt TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL)"""
    )
    conn.execute(
        "INSERT INTO runs VALUES ('old1', 'completed', '[]', '[]', 'p', 1.0)"
    )
    conn.commit()
    conn.close()

    # Any save/load triggers the ALTER TABLE migration.
    store.save("old1", "completed", ["l"], [], "p", started_at=5.0, completed_at=9.0)
    data = store.load("old1")
    assert data["started_at"] == 5.0
    assert data["completed_at"] == 9.0
    # Rows never re-saved keep NULL timings (scorecard shows duration —).
    store.save("old2", "completed", ["l"], [], "p")
    assert store.load("old2")["started_at"] is None
