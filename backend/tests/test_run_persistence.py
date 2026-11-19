"""Tests for SQLite run persistence (services/run_store.py + its wiring in
services/generation_service.py).

"Restart" is simulated by clearing the in-memory _runs dict - exactly what
a process restart does to it - and proving state comes back from SQLite.
"""
import asyncio

import pytest

import services.generation_service as gs
from services import run_store


@pytest.fixture(autouse=True)
def clean_state():
    gs._runs.clear()
    run_store.reset_broken()
    yield
    gs._runs.clear()


def test_run_store_roundtrip():
    run_store.save(
        "abc123", "completed", ["Run started.", "Done."],
        [{"path": "a.py", "content": "print(1)"}], prompt="test app",
    )
    data = run_store.load("abc123")
    assert data["status"] == "completed"
    assert data["logs"] == ["Run started.", "Done."]
    assert data["files"][0]["path"] == "a.py"
    assert data["prompt"] == "test app"
    assert run_store.load("missing") is None


def test_status_and_files_survive_restart():
    gs._runs["abc123"] = {
        "status": "completed",
        "logs": ["Run started.", "Done."],
        "files": [{"path": "a.py", "content": "print(1)"}],
    }
    gs._persist("abc123")

    gs._runs.clear()  # worker restart

    state = gs.get_status("abc123")
    assert state["status"] == "completed"
    assert "Done." in state["logs"]
    files = gs.get_files("abc123")
    assert files and files[0]["path"] == "a.py"


def test_interrupted_run_marked_failed_on_rehydrate():
    # A run persisted mid-pipeline died with the old process. A client must
    # not poll a phantom "generating_code" forever.
    run_store.save("xyz789", "generating_code", ["Run started."], [])
    gs._runs.clear()

    state = gs.get_status("xyz789")
    assert state["status"] == "failed"
    assert any("restarted" in line.lower() for line in state["logs"])


def test_continue_mode_across_restart(monkeypatch):
    run_store.save(
        "old123", "completed", ["Done."],
        [{"path": "a.py", "content": "print(1)"}],
    )
    gs._runs.clear()  # restart wipes memory; base run must come from SQLite

    async def noop_pipeline(run_id, prompt, base_files=None):
        assert base_files and base_files[0]["path"] == "a.py"

    monkeypatch.setattr(gs, "_run_pipeline", noop_pipeline)
    new_id = asyncio.run(gs.start_generation("add a feature", base_run_id="old123"))
    assert len(new_id) == 12
    # the new run itself was persisted at creation
    assert run_store.load(new_id)["status"] == "starting"


def test_continue_still_rejects_incomplete_base():
    run_store.save("old999", "generating_code", ["Run started."], [])
    gs._runs.clear()
    with pytest.raises(ValueError, match="not completed"):
        asyncio.run(gs.start_generation("x", base_run_id="old999"))


def test_broken_db_never_breaks_the_app(monkeypatch):
    # Unwritable path -> persistence disables itself, in-memory flow works.
    monkeypatch.setenv("RUNS_DB", "/proc/definitely/not/writable/runs.db")
    run_store.save("a", "completed", ["l"], [])
    assert run_store._broken
    assert run_store.load("a") is None

    async def noop_pipeline(run_id, prompt, base_files=None):
        pass

    monkeypatch.setattr(gs, "_run_pipeline", noop_pipeline)
    run_id = asyncio.run(gs.start_generation("x"))  # must not raise
    assert gs.get_status(run_id)["status"] == "starting"
