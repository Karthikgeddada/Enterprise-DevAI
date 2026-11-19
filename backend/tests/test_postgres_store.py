"""Postgres backend for run_store (DATABASE_URL), e.g. Neon.

Skipped entirely unless TEST_DATABASE_URL is set, so the default suite
stays hermetic. Rows use a test-prefixed id and are cleaned up.

Run against a real DB:
    TEST_DATABASE_URL='postgresql://...' python -m pytest tests/test_postgres_store.py
"""
import json
import os

import pytest

from services import run_store

TEST_URL = os.getenv("TEST_DATABASE_URL", "")
PREFIX = "test-pg-"

pytestmark = pytest.mark.skipif(
    not TEST_URL,
    reason="TEST_DATABASE_URL not set — Postgres backend not exercised",
)


@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.delenv("RUNS_DB", raising=False)
    run_store.reset_broken()
    yield run_store
    run_store.reset_broken()
    # cleanup: remove rows this test module created
    try:
        conn = run_store._pg_connect()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM runs WHERE run_id LIKE %s", (PREFIX + "%",))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _save(store, rid, **over):
    args = dict(
        status="completed",
        logs=["Run started.", f"log for {rid}", "Done. Project packaged as ZIP."],
        files=[
            {"path": "main.py", "content": "a\nb\nc"},
            {"path": "README.md", "content": "# x"},
        ],
        prompt="build a test app",
        started_at=100.0,
        completed_at=130.0,
    )
    args.update(over)
    store.save(PREFIX + rid, **args)


def test_backend_selection(store):
    assert store._backend() == "postgres"


def test_save_load_roundtrip(store):
    _save(store, "r1")
    data = store.load(PREFIX + "r1")
    assert data is not None
    assert data["status"] == "completed"
    assert data["logs"][1] == f"log for {PREFIX}r1"
    assert data["files"][0]["path"] == "main.py"
    assert data["prompt"] == "build a test app"
    assert data["started_at"] == 100.0
    assert data["completed_at"] == 130.0


def test_upsert_overwrites(store):
    _save(store, "r2", status="running")
    _save(store, "r2", status="completed", completed_at=140.0)
    data = store.load(PREFIX + "r2")
    assert data["status"] == "completed"
    assert data["completed_at"] == 140.0


def test_load_missing_returns_none(store):
    assert store.load(PREFIX + "nope") is None


def test_list_runs_shape_and_order(store):
    _save(store, "old", started_at=1.0, completed_at=2.0)
    _save(store, "new", started_at=2.0, completed_at=3.0)
    runs = store.list_runs(10)
    mine = [r for r in runs if r["run_id"].startswith(PREFIX)]
    assert len(mine) == 2
    assert all(r["file_count"] == 2 for r in mine)
    ids = [r["run_id"] for r in mine]
    assert ids.index(PREFIX + "new") < ids.index(PREFIX + "old")  # newest first


def test_fetch_stats_rows(store):
    _save(store, "s1", logs=["Run started.", "Coder failed (x); retrying (attempt 2/3)..."])
    rows = store.fetch_stats_rows(500)
    mine = [
        r
        for r in rows
        if PREFIX in json.dumps(r["logs"])
    ]
    assert len(mine) == 1
    assert "retrying (attempt" in "\n".join(mine[0]["logs"])
    assert mine[0]["started_at"] == 100.0


def test_json_content_roundtrips_exactly(store):
    files = [{"path": "weird$.json", "content": "{\"k\": \"quote' and \\ backslash\"}"}]
    _save(store, "j1", files=files)
    data = store.load(PREFIX + "j1")
    assert data["files"] == files
