"""Full-project generation pipeline for the web app.

Runs the agent team (requirements -> architecture -> coding -> review ->
debug -> tests -> docs -> packaging) as a background asyncio task and tracks
progress in memory so the frontend can poll GET /status/{run_id}.

Statuses emitted (must match webui/app.js):
    starting, analyzing_requirements, designing_architecture, generating_code,
    reviewing, debugging, testing, documenting, completed, failed
"""
import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

from agents.requirement_agent import requirement_agent
from agents.architect_agent import architect_agent
from agents.coder_agent import coder_agent
from agents.reviewer_agent import reviewer_agent
from agents.debugger_agent import debugger_agent
from agents.tester_agent import tester_agent
from agents.documentation_agent import documentation_agent
from agents.packager_agent import packager_agent
from services import run_store

# In-memory run store: the live working copy the pipeline mutates on every
# step. Every change is mirrored to SQLite (services.run_store) so runs
# survive worker restarts - see _load/_persist below.
_runs: Dict[str, Dict[str, Any]] = {}

_TERMINAL = ("completed", "failed")


def _persist(run_id: str) -> None:
    """Mirror the live run dict to SQLite. Never raises, never blocks long."""
    run = _runs.get(run_id)
    if run is not None:
        run_store.save(run_id, run["status"], run["logs"], run.get("files", []))


def _load(run_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a run from memory, or rehydrate it from SQLite after a restart.

    A run found on disk in a non-terminal state belonged to a pipeline that
    died with the old process, so it is marked failed - a client should
    never poll a phantom "generating_code" forever.
    """
    run = _runs.get(run_id)
    if run is not None:
        return run
    data = run_store.load(run_id)
    if data is None:
        return None
    status = data["status"]
    logs = list(data["logs"])
    if status not in _TERMINAL:
        status = "failed"
        logs.append("Server restarted mid-run; this run can no longer finish. Please generate again.")
    run = {"status": status, "logs": logs, "files": data.get("files", [])}
    _runs[run_id] = run
    return run


def _sanitize_path(path: Any) -> Optional[str]:
    """Return a safe relative path, or None if the path is unsafe."""
    if not path or not isinstance(path, str):
        return None
    p = path.strip().replace("\\", "/").lstrip("/")
    parts = [seg for seg in p.split("/") if seg not in ("", ".", "..")]
    if not parts:
        return None
    return "/".join(parts)


def _sanitize_files(files: Any) -> List[Dict[str, str]]:
    """Keep only files with a safe path and string content."""
    safe: List[Dict[str, str]] = []
    if not isinstance(files, list):
        return safe
    for f in files:
        if not isinstance(f, dict):
            continue
        path = _sanitize_path(f.get("path"))
        content = f.get("content")
        if path is None or not isinstance(content, str):
            continue
        safe.append({"path": path, "content": content})
    return safe


def _project_context(base_files: List[Dict[str, str]], per_file: int = 6000, max_chars: int = 60000) -> str:
    """Render the current project files as context for the coder agent."""
    parts: List[str] = []
    for f in base_files:
        content = f["content"]
        if len(content) > per_file:
            content = content[:per_file] + "\n... (truncated)"
        parts.append(f"--- {f['path']} ---\n{content}")
    return "\n\n".join(parts)[:max_chars]


def _merge_files(base_files: List[Dict[str, str]], changes: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Overlay the coder's changed files onto the base project (by path)."""
    merged = {f["path"]: f["content"] for f in base_files}
    for f in changes:
        merged[f["path"]] = f["content"]
    return [{"path": p, "content": c} for p, c in merged.items()]


async def _run_pipeline(run_id: str, prompt: str, base_files: Optional[List[Dict[str, str]]] = None) -> None:
    """Dispatch to the selected pipeline engine.

    PIPELINE_ENGINE env: "custom" (default - the proven asyncio pipeline) or
    "langgraph" (StateGraph orchestration in services.langgraph_pipeline). If
    the langgraph module isn't importable we log it and fall back to custom,
    so a missing dependency can never take the app down.
    """
    run = _runs[run_id]

    def log(msg: Any) -> None:
        run["logs"].append(str(msg))
        _persist(run_id)  # every log line is a state checkpoint

    engine = os.getenv("PIPELINE_ENGINE", "custom").strip().lower()
    if engine == "langgraph":
        try:
            from services import langgraph_pipeline as _lg
        except ImportError as e:
            log(f"LangGraph engine unavailable ({e}); falling back to the custom pipeline.")
        else:
            try:
                final = await _lg.execute(
                    run_id,
                    prompt,
                    base_files,
                    set_status=lambda status: run.__setitem__("status", status),
                    log=log,
                )
                run["files"] = final.get("final_files", [])
                run["status"] = "completed"
                log("Done. Project packaged as ZIP.")
            except Exception as e:  # same failure contract as the custom engine
                run["status"] = "failed"
                log(f"FAILED: {e}")
            return
    await _run_custom_pipeline(run_id, prompt, base_files)


async def _run_custom_pipeline(run_id: str, prompt: str, base_files: Optional[List[Dict[str, str]]] = None) -> None:
    run = _runs[run_id]

    def log(msg: Any) -> None:
        run["logs"].append(str(msg))
        _persist(run_id)  # every log line is a state checkpoint

    try:
        run["status"] = "analyzing_requirements"
        log("Analyzing requirements...")
        requirements = await requirement_agent(prompt)
        log("Requirements extracted.")

        run["status"] = "designing_architecture"
        log("Designing architecture...")
        architecture = await architect_agent(prompt, requirements)
        log("Architecture designed.")

        run["status"] = "generating_code"
        if base_files:
            log(f"Continuing development on the existing project ({len(base_files)} files)...")
            code_files = _sanitize_files(
                await coder_agent(
                    user_request=prompt,
                    task_title="Apply the requested change to the existing project",
                    task_description=architecture,
                    context=_project_context(base_files),
                )
            )
            if not code_files:
                raise RuntimeError("Code generation returned no usable files.")
            code_files = _merge_files(base_files, code_files)
            log(f"Project updated — now {len(code_files)} files.")
        else:
            log("Generating code files...")
            code_files = _sanitize_files(
                await coder_agent(
                    user_request=prompt,
                    task_title="Generate the full project",
                    task_description=architecture,
                    context="",
                )
            )
            if not code_files:
                raise RuntimeError("Code generation returned no usable files.")
            log(f"Generated {len(code_files)} code files.")

        run["status"] = "reviewing"
        log("Reviewing code...")
        review = await reviewer_agent(code_files)
        log(f"Review: {str(review)[:200]}")

        run["status"] = "debugging"
        log("Applying fixes if needed...")
        fixed = _sanitize_files(await debugger_agent(code_files, review))
        if fixed:
            code_files = fixed

        run["status"] = "testing"
        log("Generating tests...")
        test_files = _sanitize_files(await tester_agent(code_files))
        log(f"Generated {len(test_files)} test files.")

        run["status"] = "documenting"
        log("Writing documentation...")
        docs_files = _sanitize_files(await documentation_agent(code_files, requirements))
        log(f"Generated {len(docs_files)} documentation files.")

        await packager_agent({
            "run_id": run_id,
            "code_files": code_files,
            "tests_files": test_files,
            "docs_files": docs_files,
        })

        run["files"] = code_files + test_files + docs_files
        run["status"] = "completed"
        log("Done. Project packaged as ZIP.")
    except Exception as e:  # surface every failure to the UI, never crash the app
        run["status"] = "failed"
        log(f"FAILED: {e}")


async def start_generation(prompt: str, base_run_id: Optional[str] = None) -> str:
    """Start a generation run in the background. Returns the run id.

    With base_run_id, the run continues development on that completed run's
    project: the coder receives the current files as context and its changes
    are merged on top of them.
    """
    if not prompt or not prompt.strip():
        raise ValueError("Prompt is required.")

    base_files: Optional[List[Dict[str, str]]] = None
    if base_run_id:
        base = _load(base_run_id)
        if not base:
            raise ValueError("Previous run not found. The server may have restarted.")
        if base.get("status") != "completed":
            raise ValueError("Previous run is not completed yet.")
        base_files = [dict(f) for f in base.get("files", [])]
        if not base_files:
            raise ValueError("Previous run has no files to continue from.")

    run_id = uuid.uuid4().hex[:12]
    _runs[run_id] = {"status": "starting", "logs": ["Run started."], "files": []}
    _persist(run_id)
    asyncio.create_task(_run_pipeline(run_id, prompt.strip(), base_files))
    return run_id


def get_status(run_id: str) -> Optional[Dict[str, Any]]:
    run = _load(run_id)
    if not run:
        return None
    return {"status": run["status"], "logs": list(run["logs"])}


def get_files(run_id: str) -> Optional[List[Dict[str, str]]]:
    """Return generated files (only meaningful once status is completed)."""
    run = _load(run_id)
    if not run:
        return None
    return list(run.get("files", []))
