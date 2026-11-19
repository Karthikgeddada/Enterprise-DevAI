import asyncio
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import os
from services.generation_service import start_generation, get_status, get_files, get_run
from services.github_export import push_project_to_github
from services.scorecard import compute_scorecard
from services.observability import compute_stats
from services import run_store
from services.guard import rate_limit, require_api_key

router = APIRouter()

class PromptRequest(BaseModel):
    prompt: str
    base_run_id: Optional[str] = None  # set to continue developing an existing project
    provider: Optional[str] = None  # per-run LLM provider ("auto"/None = deployment default)

class GithubExportRequest(BaseModel):
    run_id: str
    repo_name: Optional[str] = None
    token: Optional[str] = None  # falls back to the GITHUB_TOKEN env var

@router.get("/models")
async def list_models():
    """Provider options selectable per run (auto + configured providers).
    Read-only like /runs."""
    from config.llm_config import provider_choices
    return {"choices": provider_choices()}

@router.post("/generate", dependencies=[Depends(require_api_key), Depends(rate_limit)])
async def generate_project(req: PromptRequest):
    try:
        run_id = await start_generation(req.prompt, req.base_run_id, req.provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"run_id": run_id, "message": "Generation started"}

@router.get("/status/{run_id}")
async def get_project_status(run_id: str):
    state = get_status(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "status": state["status"],
        "logs": state["logs"]
    }

@router.get("/stream/{run_id}")
async def stream_run(run_id: str):
    """Server-Sent Events feed of a run's live status and logs.

    Emits one event whenever status or logs change, then closes on a terminal
    status. Read-only like /status, so it stays open (scoped by unguessable
    run ids). The frontend keeps 2s polling as automatic fallback.
    """
    if not get_status(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_stream():
        last: Optional[str] = None
        idle = 0
        while True:
            state = get_status(run_id)
            if state is None:
                return
            payload = json.dumps({"status": state["status"], "logs": state["logs"]})
            if payload != last:
                last = payload
                idle = 0
                yield f"data: {payload}\n\n"
                if state["status"] in ("completed", "failed"):
                    return
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ": ping\n\n"  # keep proxies from closing an idle line
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.get("/runs")
async def list_runs():
    """Run history for the dashboard: newest first, capped at 50.

    Read-only like /status, so it stays open in the public demo.
    """
    return {"runs": run_store.list_runs(50)}

@router.get("/stats")
async def get_stats():
    """Operational stats over the run store: status counts, failure causes,
    avg build time/files/lines, self-heal total, top languages.
    Read-only like /runs."""
    return compute_stats()

@router.get("/scorecard/{run_id}")
async def get_scorecard(run_id: str):
    """Build statistics for a run: files, lines, languages, quality checks,
    self-heal count and duration. Read-only like /files."""
    run = get_run(run_id)
    if run is None or not run.get("files"):
        raise HTTPException(status_code=404, detail="Run not found or has no files")
    return compute_scorecard(run)

@router.get("/files/{run_id}")
async def get_project_files(run_id: str):
    files = get_files(run_id)
    if files is None:
        raise HTTPException(status_code=404, detail="Files not found")
    return {"files": files}

@router.get("/download/{run_id}", dependencies=[Depends(require_api_key)])
async def download_project(run_id: str):
    zip_path = f"generated_projects/{run_id}.zip"
    if not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="ZIP not found or generation incomplete")
    return FileResponse(zip_path, media_type="application/zip", filename=f"devteam_project_{run_id}.zip")

@router.get("/preview/{run_id}")
async def preview_code(run_id: str):
    files = get_files(run_id)
    if files is None:
        raise HTTPException(status_code=404, detail="Files not found")
    # Return html preview or just list for frontend
    return {"files": files}

@router.get("/api/health")
async def health():
    return {"status": "ok"}

@router.post("/export/github", dependencies=[Depends(require_api_key), Depends(rate_limit)])
async def export_to_github(req: GithubExportRequest):
    """Create a real GitHub repo from a finished run (user's PAT).

    The token is used for this single request and never stored. PyGithub
    is blocking, so the push runs in a worker thread.
    """
    files = get_files(req.run_id)
    if not files:
        raise HTTPException(status_code=404, detail="Run not found or has no files")

    token = (req.token or os.getenv("GITHUB_TOKEN") or "").strip()
    if not token:
        raise HTTPException(
            status_code=400,
            detail="A GitHub personal access token is required (classic token with 'repo' scope, or fine-grained with Contents: write).",
        )

    try:
        result = await asyncio.to_thread(
            push_project_to_github,
            files,
            req.repo_name or f"devteam-ai-{req.run_id}",
            token,
        )
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Bad credentials" in msg:
            raise HTTPException(status_code=401, detail="GitHub rejected that token. Check it and its scopes.")
        raise HTTPException(status_code=502, detail=f"GitHub export failed: {msg[:300]}")
    return result
