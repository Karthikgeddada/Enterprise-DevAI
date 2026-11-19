import json
import time
from typing import List, Dict, Any, Optional

from providers.base import GenerationRequest
from providers.registry import get_registry
from providers.retry import RetryPolicy
from providers.errors import classify_error, ProviderError, ErrorCategory
from utils.json_parser import parse_json_response


async def planner_agent(
    user_request: str,
    project_context: str,
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Analyze a user request and create a structured implementation plan.
    Returns a list of task definitions with dependencies and acceptance criteria.
    """
    registry = get_registry()
    provider = registry.get_provider(provider_name) if provider_name else registry.get_default_provider()
    if not provider:
        raise ProviderError("No provider available", ErrorCategory.AUTH_ERROR, retryable=False)

    selected_model = model or registry.get_default_model(provider.name)

    system_prompt = """You are a Planning Agent for an AI coding workspace.
Analyze the user's request and the current project context, then create a structured implementation plan.

Output ONLY valid JSON in this exact format. No markdown blocks, no extra text:
{
    "tasks": [
        {
            "title": "Short task title",
            "description": "What to do in this task",
            "dependencies": [0],
            "acceptance_criteria": "How to verify the task is done",
            "files_affected": ["path/to/file.py"]
        }
    ]
}

Rules:
- Break work into small, bounded tasks (2-5 files each max).
- List dependencies as task indices (0-based) that must complete first.
- Each task should be independently reviewable.
- For new projects: start with project structure, then core logic, then tests, then docs.
- For modifications: target only the files that need to change.
- Do NOT include more than 8 tasks."""

    user_msg = f"User Request: {user_request}\n\nCurrent Project Context:\n{project_context}"

    request = GenerationRequest(
        messages=[{"role": "user", "content": user_msg}],
        model=selected_model,
        system_prompt=system_prompt,
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
                total_tokens=u.get('total_tokens', 0), latency_ms=latency_ms,
            )
        except Exception:
            pass

    data = parse_json_response(response.content)
    tasks = data.get("tasks", [])

    if not tasks:
        raise ProviderError("Planner returned no tasks", ErrorCategory.MALFORMED_RESPONSE, retryable=False)

    return tasks