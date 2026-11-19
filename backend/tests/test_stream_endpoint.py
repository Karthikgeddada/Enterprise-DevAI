"""Tests for the SSE live-stream endpoint (GET /stream/{run_id}).

The stream emits one event whenever a run's status/logs change and closes
when the run reaches a terminal status. The frontend falls back to 2s
polling if the stream errors, so these tests cover: initial snapshot,
live push mid-run, terminal close, and 404 for unknown runs.
"""
import json
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.api as api
from services import generation_service


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _seed_run(run_id, status="completed", logs=None):
    run = {
        "status": status,
        "logs": logs if logs is not None else ["Run started."],
        "files": [],
    }
    generation_service._runs[run_id] = run
    return run


def test_stream_404_for_unknown_run(client):
    assert client.get("/stream/nope").status_code == 404


def test_stream_emits_state_and_closes_on_terminal(client):
    _seed_run("t1", status="completed", logs=["Run started.", "Done."])
    events = []
    with client.stream("GET", "/stream/t1") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    assert len(events) == 1  # terminal run: one snapshot, then the stream ends
    assert events[0]["status"] == "completed"
    assert events[0]["logs"][-1] == "Done."


def test_stream_pushes_change_then_closes(client):
    run = _seed_run("t2", status="generating_code", logs=["Generating..."])

    def finish():
        run["status"] = "completed"
        run["logs"].append("Done. Project packaged as ZIP.")

    timer = threading.Timer(0.3, finish)
    timer.start()
    events = []
    with client.stream("GET", "/stream/t2") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    timer.join()

    statuses = [e["status"] for e in events]
    assert statuses[0] == "generating_code"
    assert statuses[-1] == "completed"
    assert len(events) >= 2
