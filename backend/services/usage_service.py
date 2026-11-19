import uuid
import time
from typing import List, Optional, Dict, Any

from storage.repository import Repository, UsageRecord
from providers.registry import get_registry


class UsageService:
    """Service for tracking provider usage and cost estimates."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def record_usage(
        self,
        project_id: str,
        provider: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: float = 0,
        task_id: Optional[str] = None,
    ) -> UsageRecord:
        """Record a provider usage event."""
        registry = get_registry()
        provider_obj = registry.get_provider(provider)
        estimated_cost = 0.0
        if provider_obj:
            estimated_cost = provider_obj.estimate_cost(model, prompt_tokens, completion_tokens)

        record = UsageRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_id=task_id,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens or (prompt_tokens + completion_tokens),
            estimated_cost=estimated_cost,
            latency_ms=latency_ms,
            created_at=time.time(),
        )
        self.repo.save_usage(record)
        return record

    def get_usage(self, project_id: str) -> List[UsageRecord]:
        return self.repo.get_usage(project_id)

    def get_usage_summary(self, project_id: str) -> Dict[str, Any]:
        """Get aggregated usage statistics for a project."""
        records = self.get_usage(project_id)
        total_tokens = sum(r.total_tokens for r in records)
        total_cost = sum(r.estimated_cost for r in records)
        total_requests = len(records)
        avg_latency = sum(r.latency_ms for r in records) / max(total_requests, 1)

        by_provider: Dict[str, Dict[str, Any]] = {}
        for r in records:
            if r.provider not in by_provider:
                by_provider[r.provider] = {'requests': 0, 'tokens': 0, 'cost': 0.0}
            by_provider[r.provider]['requests'] += 1
            by_provider[r.provider]['tokens'] += r.total_tokens
            by_provider[r.provider]['cost'] += r.estimated_cost

        return {
            'total_requests': total_requests,
            'total_tokens': total_tokens,
            'total_cost': round(total_cost, 6),
            'avg_latency_ms': round(avg_latency, 2),
            'by_provider': by_provider,
        }