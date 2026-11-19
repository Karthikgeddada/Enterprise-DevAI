import json
import time
from typing import List, Dict, Any, Optional

from providers.base import GenerationRequest
from providers.registry import get_registry
from providers.retry import RetryPolicy
from providers.errors import classify_error, ProviderError, ErrorCategory
from utils.json_parser import parse_json_response


async def coder_agent(
    user_request: str,
    task_title: str,
    task_description: str,
    context: str,
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Generate targeted file changes for a single bounded task.
    Returns a list of file dicts: [{"path": "...", "content": "...", "action": "create"|"modify"}]
    """
    registry = get_registry()
    provider = registry.get_provider(provider_name) if provider_name else registry.get_default_provider()
    if not provider:
        raise ProviderError("No provider available", ErrorCategory.AUTH_ERROR, retryable=False)

    selected_model = model or registry.get_default_model(provider.name)

    system_prompt = """You are a Code Generator Agent for an incremental AI coding workspace.
Generate ONLY the files needed for this specific task. Do NOT regenerate unchanged files.

Output ONLY valid JSON in this exact format. No markdown blocks, no extra text:
{
    "files": [
        {
            "path": "relative/path/to/file.py",
            "content": "full file content...",
            "action": "create"
        }
    ]
}

Rules:
- "action" must be "create" for new files or "modify" for changed files.
- Include the FULL content of each file, not just the changed parts.
- Only include files that need to be created or modified for THIS task.
- Do NOT include files that are not part of this task.
- Keep the output focused: prefer 3-6 files for this task.
- Ensure all code is syntactically valid.
- Include proper imports and dependencies."""

    user_msg = f"""User Request: {user_request}

Task: {task_title}
Task Description: {task_description}

Current Project Context:
{context}"""

    # The coder must emit full file contents inside one JSON payload.
    # The default max_tokens=4096 truncates it mid-file, which then parses
    # to zero files ("Coder returned no files"). Use the model's cap.
    model_cap = next(
        (m.max_output_tokens for m in provider.get_models() if m.id == selected_model),
        8192,
    )
    request = GenerationRequest(
        messages=[{"role": "user", "content": user_msg}],
        model=selected_model,
        system_prompt=system_prompt,
        max_tokens=model_cap,
        response_format={"type": "json_object"} if provider.get_models() and provider.get_models()[0].supports_structured else None,
    )

    retry = RetryPolicy(max_retries=3)

    async def _call():
        return await provider.generate(request)

    t0 = time.time()
    response = await retry.execute_with_retry(_call)
    latency_ms = (time.time() - t0) * 1000

    if project_id and response.usage:
        try:
            from services.persistence import get_services
            services = get_services()
            u = response.usage
            services.usage_service.record_usage(
                project_id=project_id, provider=provider.name, model=selected_model,
                prompt_tokens=u.get('prompt_tokens', 0),
                completion_tokens=u.get('completion_tokens', 0),
                total_tokens=u.get('total_tokens', 0),
                latency_ms=latency_ms, task_id=task_id,
            )
        except Exception:
            pass

    data = parse_json_response(response.content)
    files = data.get("files", [])

    if not files:
        finish = getattr(response, "finish_reason", None)
        raise ProviderError(
            f"Coder returned no files (finish_reason={finish})",
            ErrorCategory.MALFORMED_RESPONSE,
            retryable=False,
        )

    # Validate file paths are relative (not absolute)
    for f in files:
        path = f.get("path", "")
        if path.startswith("/"):
            f["path"] = path.lstrip("/")
        if "action" not in f:
            f["action"] = "modify" if context else "create"

    return files


# Legacy compatibility - keep the old signature working for existing code
async def coder_agent_legacy(prompt: str, architecture: str) -> list:
    """Legacy coder agent for backward compatibility."""
    return await coder_agent(prompt, "Generate all code files", architecture)
