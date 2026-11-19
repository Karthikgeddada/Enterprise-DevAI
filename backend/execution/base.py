from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class ValidationResult:
    """Result of a validation check."""
    level: str  # 'static' or 'isolated'
    passed: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    summary: str = ""

    def add_check(self, name: str, passed: bool, message: str = "", details: Optional[Dict] = None):
        self.checks.append({
            'name': name, 'passed': passed, 'message': message, 'details': details or {}
        })
        if not passed:
            self.errors.append(f"{name}: {message}")

    def add_warning(self, name: str, message: str):
        self.warnings.append(f"{name}: {message}")


class BaseValidator(ABC):
    """Abstract interface for validators."""

    @property
    @abstractmethod
    def level(self) -> str:
        pass

    @abstractmethod
    def validate(self, project_id: str, files: List[Dict[str, str]]) -> ValidationResult:
        """Validate files and return a result."""
        pass


class BaseExecutor(ABC):
    """Abstract interface for isolated code executors."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def execute(self, project_dir: str, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute a command in an isolated environment."""
        pass