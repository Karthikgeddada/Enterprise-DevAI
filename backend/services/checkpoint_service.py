import uuid
import time
from typing import Optional, Dict, Any, List

from storage.repository import Repository, CheckpointRecord


class CheckpointService:
    """Service for creating and restoring task checkpoints."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def create_checkpoint(
        self,
        project_id: str,
        task_id: str,
        state: str,
        context: Dict[str, Any],
    ) -> CheckpointRecord:
        """Create a checkpoint for a task."""
        checkpoint = CheckpointRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_id=task_id,
            state=state,
            context=context,
            created_at=time.time(),
        )
        self.repo.save_checkpoint(checkpoint)
        return checkpoint

    def get_latest(self, project_id: str, task_id: str) -> Optional[CheckpointRecord]:
        return self.repo.get_latest_checkpoint(project_id, task_id)

    def list_all(self, project_id: str) -> List[CheckpointRecord]:
        return self.repo.list_checkpoints(project_id)

    def restore_context(self, project_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        """Get the context from the latest checkpoint for a task."""
        cp = self.get_latest(project_id, task_id)
        if cp:
            return cp.context
        return None