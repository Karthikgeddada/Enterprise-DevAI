import uuid
import time
from typing import List, Optional, Dict, Any

from storage.repository import Repository, TaskRecord


# Task state transitions
VALID_TRANSITIONS = {
    'pending': ['running', 'cancelled'],
    'running': ['awaiting_review', 'validating', 'failed', 'paused', 'cancelled'],
    'awaiting_review': ['validating', 'completed', 'failed', 'cancelled'],
    'validating': ['completed', 'failed', 'paused', 'cancelled'],
    'completed': [],
    'failed': ['pending', 'cancelled'],  # can retry
    'paused': ['running', 'cancelled'],  # can resume
    'cancelled': [],
}


class TaskService:
    """Service for managing implementation tasks and their states."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def create_plan(self, project_id: str, plan_id: str, tasks: List[Dict[str, Any]]) -> List[TaskRecord]:
        """Create a set of tasks from a plan."""
        records = []
        for i, t in enumerate(tasks):
            task = TaskRecord(
                id=str(uuid.uuid4()),
                project_id=project_id,
                plan_id=plan_id,
                title=t.get('title', f'Task {i+1}'),
                description=t.get('description', ''),
                status='pending',
                order=i,
                dependencies=t.get('dependencies', []),
                acceptance_criteria=t.get('acceptance_criteria', ''),
                metadata=t.get('metadata', {}),
            )
            self.repo.create_task(task)
            records.append(task)
        return records

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self.repo.get_task(task_id)

    def list_tasks(self, project_id: str, plan_id: Optional[str] = None) -> List[TaskRecord]:
        return self.repo.list_tasks(project_id, plan_id)

    def transition_task(self, task_id: str, new_status: str, error: Optional[str] = None) -> TaskRecord:
        """Transition a task to a new state with validation."""
        task = self.repo.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if new_status not in VALID_TRANSITIONS:
            raise ValueError(f"Invalid task status: {new_status}")

        if new_status not in VALID_TRANSITIONS.get(task.status, []):
            raise ValueError(f"Cannot transition from '{task.status}' to '{new_status}'")

        updates = {'status': new_status}
        if error:
            updates['error'] = error
        if new_status == 'completed':
            updates['error'] = None

        self.repo.update_task(task_id, **updates)
        task.status = new_status
        task.error = error
        return task

    def can_execute(self, task: TaskRecord, all_tasks: List[TaskRecord]) -> bool:
        """Check if a task can be executed (dependencies satisfied)."""
        if not task.dependencies:
            return True
        task_map = {t.id: t for t in all_tasks}
        for dep_id in task.dependencies:
            dep = task_map.get(dep_id)
            if not dep or dep.status != 'completed':
                return False
        return True

    def get_next_task(self, project_id: str, plan_id: str) -> Optional[TaskRecord]:
        """Get the next pending task whose dependencies are satisfied."""
        tasks = self.list_tasks(project_id, plan_id)
        for task in tasks:
            if task.status == 'pending' and self.can_execute(task, tasks):
                return task
        return None

    def update_task_result(self, task_id: str, result: str) -> None:
        self.repo.update_task(task_id, result=result)

    def is_plan_complete(self, project_id: str, plan_id: str) -> bool:
        """Check if all tasks in a plan are completed or cancelled."""
        tasks = self.list_tasks(project_id, plan_id)
        if not tasks:
            return False
        return all(t.status in ('completed', 'cancelled') for t in tasks)

    def get_plan_summary(self, project_id: str, plan_id: str) -> Dict[str, Any]:
        """Get a summary of task statuses in a plan."""
        tasks = self.list_tasks(project_id, plan_id)
        summary = {
            'total': len(tasks),
            'pending': 0, 'running': 0, 'awaiting_review': 0,
            'validating': 0, 'completed': 0, 'failed': 0, 'paused': 0, 'cancelled': 0,
        }
        for t in tasks:
            if t.status in summary:
                summary[t.status] += 1
        summary['is_complete'] = summary['total'] > 0 and summary['completed'] + summary['cancelled'] == summary['total']
        return summary