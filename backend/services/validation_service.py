from typing import List, Dict, Any
from execution.base import ValidationResult
from execution.static_validator import StaticValidator
from execution.isolated_executor import IsolatedExecutor


class ValidationService:
    """Service for running validation checks on project files."""

    def __init__(self):
        self.static_validator = StaticValidator()
        self.isolated_executor = IsolatedExecutor()

    def run_static_validation(self, project_id: str, files: List[Dict[str, str]]) -> ValidationResult:
        """Run Level A static validation."""
        return self.static_validator.validate(project_id, files)

    def run_isolated_execution(self, project_dir: str, command: str) -> Dict[str, Any]:
        """Run Level B isolated execution if available."""
        if not self.isolated_executor.is_available:
            return {
                'success': False,
                'message': 'Isolated execution is disabled. No verified sandbox is configured.',
                'available': False,
            }
        return self.isolated_executor.execute(project_dir, command)

    def is_execution_available(self) -> bool:
        return self.isolated_executor.is_available

    def validate_files(self, project_id: str, files: List[Dict[str, str]]) -> Dict[str, Any]:
        """Run all available validation and return a summary."""
        result = self.run_static_validation(project_id, files)
        return {
            'static': {
                'passed': result.passed,
                'errors': result.errors,
                'warnings': result.warnings,
                'checks': result.checks,
                'summary': result.summary,
            },
            'execution_available': self.is_execution_available(),
        }