"""Full-project generation pipeline for the web app.

Runs the agent team (requirements -> architecture -> coding -> review ->
debug -> tests -> docs -> packaging) as a background asyncio task and tracks
progress in memory so the frontend can poll GET /status/{run_id}.

Statuses emitted (must match webui/app.js):
    starting, analyzing_requirements, designing_architecture, generating_code,
    reviewing, debugging, testing, documenting, completed, failed
"""
import asyncio
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

# In-memory run store (fine for a single-process deployment)
_runs: Dict[str, Dict[str, Any]] = {}


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


async def _run_pipeline(run_id: str, prompt: str) -> None:
    run = _runs[run_id]

    def log(msg: Any) -> None:
        run["logs"].append(str(msg))

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


async def start_generation(prompt: str) -> str:
    """Start a generation run in the background. Returns the run id."""
    if not prompt or not prompt.strip():
        raise ValueError("Prompt is required.")
    run_id = uuid.uuid4().hex[:12]
    _runs[run_id] = {"status": "starting", "logs": ["Run started."], "files": []}
    asyncio.create_task(_run_pipeline(run_id, prompt.strip()))
    return run_id


def get_status(run_id: str) -> Optional[Dict[str, Any]]:
    run = _runs.get(run_id)
    if not run:
        return None
    return {"status": run["status"], "logs": list(run["logs"])}


def get_files(run_id: str) -> Optional[List[Dict[str, str]]]:
    """Return generated files (only meaningful once status is completed)."""
    run = _runs.get(run_id)
    if not run:
        return None
    return list(run.get("files", []))
