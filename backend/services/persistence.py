import os
from typing import Optional

from storage.sqlite_repository import SQLiteRepository
from storage.repository import Repository
from config.settings import settings
from services.project_service import ProjectService
from services.task_service import TaskService
from services.diff_service import DiffService
from services.checkpoint_service import CheckpointService
from services.usage_service import UsageService
from services.validation_service import ValidationService


class ServiceContainer:
    """Central container for all services. Singleton."""

    _instance: Optional['ServiceContainer'] = None

    def __init__(self, repo: Repository):
        self.repo = repo
        self.project_service = ProjectService(repo)
        self.task_service = TaskService(repo)
        self.diff_service = DiffService(repo)
        self.checkpoint_service = CheckpointService(repo)
        self.usage_service = UsageService(repo)
        self.validation_service = ValidationService()

    @classmethod
    def get_instance(cls) -> 'ServiceContainer':
        if cls._instance is None:
            os.makedirs('data', exist_ok=True)
            os.makedirs(settings.PROJECTS_DIR, exist_ok=True)
            repo = SQLiteRepository(settings.DB_PATH)
            cls._instance = cls(repo)
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset the singleton (for testing)."""
        cls._instance = None


def get_services() -> ServiceContainer:
    return ServiceContainer.get_instance()