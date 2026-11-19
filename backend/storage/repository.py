from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field


@dataclass
class ProjectRecord:
    """Metadata for a project."""
    id: str
    name: str
    description: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    status: str = "active"
    language: str = "python"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FileVersion:
    """A version of a file in a project."""
    project_id: str
    path: str
    content: str
    version: int
    hash: str
    created_at: float
    created_by: str = "user"


@dataclass
class ConversationRecord:
    """A conversation message."""
    id: str
    project_id: str
    role: str  # user, assistant, system
    content: str
    created_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskRecord:
    """A task in an implementation plan."""
    id: str
    project_id: str
    plan_id: str
    title: str
    description: str
    status: str = "pending"  # pending, running, awaiting_review, validating, completed, failed, paused, cancelled
    order: int = 0
    dependencies: List[str] = field(default_factory=list)
    acceptance_criteria: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    error: Optional[str] = None
    result: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiffRecord:
    """A proposed or applied file change."""
    id: str
    project_id: str
    task_id: str
    file_path: str
    base_content: str
    proposed_content: str
    diff_text: str
    status: str = "proposed"  # proposed, accepted, rejected, reverted
    created_at: float = 0.0
    reviewed_at: Optional[float] = None
    applied_at: Optional[float] = None
    reviewer: Optional[str] = None
    base_version: int = 0


@dataclass
class CheckpointRecord:
    """A checkpoint for task recovery."""
    id: str
    project_id: str
    task_id: str
    state: str
    context: Dict[str, Any]
    created_at: float


@dataclass
class UsageRecord:
    """Provider usage for a request."""
    id: str
    project_id: str
    task_id: Optional[str]
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    latency_ms: float
    created_at: float


class Repository(ABC):
    """Abstract repository interface for persistence."""

    @abstractmethod
    def init_schema(self) -> None:
        pass

    # Projects
    @abstractmethod
    def create_project(self, project: ProjectRecord) -> None:
        pass

    @abstractmethod
    def get_project(self, project_id: str) -> Optional[ProjectRecord]:
        pass

    @abstractmethod
    def list_projects(self) -> List[ProjectRecord]:
        pass

    @abstractmethod
    def update_project(self, project_id: str, **fields: Any) -> None:
        pass

    @abstractmethod
    def delete_project(self, project_id: str) -> None:
        pass

    # Files
    @abstractmethod
    def save_file(self, project_id: str, path: str, content: str, created_by: str = "user") -> int:
        pass

    @abstractmethod
    def get_file(self, project_id: str, path: str) -> Optional[FileVersion]:
        pass

    @abstractmethod
    def list_files(self, project_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def delete_file(self, project_id: str, path: str) -> None:
        pass

    @abstractmethod
    def get_file_versions(self, project_id: str, path: str) -> List[FileVersion]:
        pass

    # Conversations
    @abstractmethod
    def save_conversation(self, conv: ConversationRecord) -> None:
        pass

    @abstractmethod
    def get_conversations(self, project_id: str) -> List[ConversationRecord]:
        pass

    # Tasks
    @abstractmethod
    def create_task(self, task: TaskRecord) -> None:
        pass

    @abstractmethod
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        pass

    @abstractmethod
    def list_tasks(self, project_id: str, plan_id: Optional[str] = None) -> List[TaskRecord]:
        pass

    @abstractmethod
    def update_task(self, task_id: str, **fields: Any) -> None:
        pass

    @abstractmethod
    def delete_task(self, task_id: str) -> None:
        pass

    # Diffs
    @abstractmethod
    def save_diff(self, diff: DiffRecord) -> None:
        pass

    @abstractmethod
    def get_diffs_for_task(self, task_id: str) -> List[DiffRecord]:
        pass

    @abstractmethod
    def get_diffs_for_project(self, project_id: str) -> List[DiffRecord]:
        pass

    @abstractmethod
    def update_diff(self, diff_id: str, **fields: Any) -> None:
        pass

    # Checkpoints
    @abstractmethod
    def save_checkpoint(self, checkpoint: CheckpointRecord) -> None:
        pass

    @abstractmethod
    def get_latest_checkpoint(self, project_id: str, task_id: str) -> Optional[CheckpointRecord]:
        pass

    @abstractmethod
    def list_checkpoints(self, project_id: str) -> List[CheckpointRecord]:
        pass

    # Usage
    @abstractmethod
    def save_usage(self, usage: UsageRecord) -> None:
        pass

    @abstractmethod
    def get_usage(self, project_id: str) -> List[UsageRecord]:
        pass

    # Audit
    @abstractmethod
    def save_audit_event(self, event: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def get_audit_events(self, project_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        pass