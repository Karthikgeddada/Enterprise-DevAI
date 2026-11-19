from enum import Enum
from typing import Optional, Dict, Any


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


VALID_TRANSITIONS = {
    TaskState.PENDING: [TaskState.RUNNING, TaskState.CANCELLED],
    TaskState.RUNNING: [TaskState.AWAITING_REVIEW, TaskState.VALIDATING, TaskState.FAILED, TaskState.PAUSED, TaskState.CANCELLED],
    TaskState.AWAITING_REVIEW: [TaskState.VALIDATING, TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED],
    TaskState.VALIDATING: [TaskState.COMPLETED, TaskState.FAILED, TaskState.PAUSED, TaskState.CANCELLED],
    TaskState.COMPLETED: [],
    TaskState.FAILED: [TaskState.PENDING, TaskState.CANCELLED],
    TaskState.PAUSED: [TaskState.RUNNING, TaskState.CANCELLED],
    TaskState.CANCELLED: [],
}


def can_transition(from_state: str, to_state: str) -> bool:
    """Check if a state transition is valid."""
    try:
        from_enum = TaskState(from_state)
        to_enum = TaskState(to_state)
        return to_enum in VALID_TRANSITIONS.get(from_enum, [])
    except ValueError:
        return False


def is_terminal(state: str) -> bool:
    """Check if a state is terminal (no further transitions)."""
    try:
        return len(VALID_TRANSITIONS.get(TaskState(state), [])) == 0
    except ValueError:
        return True


def can_resume(state: str) -> bool:
    """Check if a task in this state can be resumed."""
    return state in (TaskState.PAUSED.value, TaskState.FAILED.value)