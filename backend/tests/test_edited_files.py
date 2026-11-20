"""Tests for in-browser file editing (Monaco) — Feature #4 backend.

POST /generate accepts edited_files: [{path, content}]. They are merged on
TOP of the base snapshot (base_run_id's files, or nothing) so "continue
with my edits" sends the user's changes to the coder as context.
"""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.api as api
import services.generation_service as gs
from services import run_store


@pytest.fixture(autouse=True)
def clean_state():
    gs._runs.clear()
    run_store.reset_broken()
    yield
    gs._runs.clear()


def _seed_base_run(files):
    gs._runs["base1"] = {
        "status": "completed",
        "logs": ["Run started.", "Done."],
        "files": files,
        "prompt": "base project",
    }


async def _start_and_capture(coro_factory, captured):
    """Run start_generation with a stubbed pipeline that records base_files."""

    async def fake_pipeline(run_id, prompt, base_files):
        captured["base_files"] = base_files
        gs._runs[run_id]["status"] = "completed"

    orig = gs._run_pipeline
    gs._run_pipeline = fake_pipeline
    try:
        run_id = await coro_factory()
        await asyncio.sleep(0)  # let the created pipeline task run
        return run_id
    finally:
        gs._run_pipeline = orig


# ------------------------------------------------------------ sanitizer
def test_sanitize_accepts_clean_edits():
    out = gs._sanitize_edited_files(
        [{"path": "src/app.py", "content": "print('hi')"}]
    )
    assert out == [{"path": "src/app.py", "content": "print('hi')"}]


def test_sanitize_rejects_bad_shape():
    with pytest.raises(ValueError, match="list"):
        gs._sanitize_edited_files("not-a-list")
    with pytest.raises(ValueError, match="path.*content"):
        gs._sanitize_edited_files([{"path": "a.py"}])
    with pytest.raises(ValueError, match="object"):
        gs._sanitize_edited_files(["a.py"])


def test_sanitize_rejects_unsafe_paths():
    for bad in ["/abs.py", "../escape.py", "a/../../b.py", "back\\slash.py"]:
        with pytest.raises(ValueError, match="Invalid file path"):
            gs._sanitize_edited_files([{"path": bad, "content": "x"}])


def test_sanitize_rejects_empty_path():
    for bad in ["", "   "]:
        with pytest.raises(ValueError, match="non-empty"):
            gs._sanitize_edited_files([{"path": bad, "content": "x"}])


def test_sanitize_rejects_too_many():
    with pytest.raises(ValueError, match="max 50"):
        gs._sanitize_edited_files(
            [{"path": f"f{i}.py", "content": "x"} for i in range(51)]
        )


# ---------------------------------------------------------- merge logic
def test_edits_without_base_seed_a_fresh_project():
    captured = {}
    edits = [{"path": "main.py", "content": "print('mine')"}]

    rid = asyncio.run(
        _start_and_capture(
            lambda: gs.start_generation("build on my snippet", edited_files=edits),
            captured,
        )
    )

    assert captured["base_files"] == edits
    log = "\n".join(gs.get_status(rid)["logs"])
    assert "User edits applied: 1" in log


def test_edits_override_base_files_by_path():
    _seed_base_run([
        {"path": "a.py", "content": "old"},
        {"path": "b.py", "content": "keep"},
    ])
    captured = {}
    edits = [
        {"path": "a.py", "content": "user edited"},
        {"path": "c.py", "content": "brand new"},
    ]

    asyncio.run(
        _start_and_capture(
            lambda: gs.start_generation(
                "continue with my edits", base_run_id="base1", edited_files=edits
            ),
            captured,
        )
    )

    merged = {f["path"]: f["content"] for f in captured["base_files"]}
    assert merged == {"a.py": "user edited", "b.py": "keep", "c.py": "brand new"}


def test_edits_base_run_must_be_completed():
    gs._runs["base1"] = {"status": "generating_code", "logs": [], "files": []}
    with pytest.raises(ValueError, match="not completed"):
        asyncio.run(
            gs.start_generation(
                "x", base_run_id="base1",
                edited_files=[{"path": "a.py", "content": "y"}],
            )
        )


def test_bad_edits_raise_before_task_starts():
    with pytest.raises(ValueError, match="Invalid file path"):
        asyncio.run(
            gs.start_generation(
                "x", edited_files=[{"path": "../evil.py", "content": "x"}]
            )
        )


# ------------------------------------------------------------- endpoint
@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_generate_endpoint_passes_edited_files(client, monkeypatch):
    seen = {}

    async def fake_start(prompt, base_run_id=None, provider=None, edited_files=None):
        seen.update(
            prompt=prompt, base_run_id=base_run_id,
            provider=provider, edited_files=edited_files,
        )
        return "newrun1"

    monkeypatch.setattr(api, "start_generation", fake_start)

    edits = [{"path": "app.py", "content": "print('edited')"}]
    r = client.post(
        "/generate",
        json={"prompt": "continue with my edits",
              "base_run_id": "som", "edited_files": edits},
    )
    assert r.status_code == 200
    assert seen["edited_files"] == edits
    assert seen["base_run_id"] == "som"


def test_generate_endpoint_rejects_bad_edits(client):
    r = client.post(
        "/generate",
        json={"prompt": "x",
              "edited_files": [{"path": "/abs", "content": "y"}]},
    )
    assert r.status_code == 400
    assert "Invalid file path" in r.json()["detail"]