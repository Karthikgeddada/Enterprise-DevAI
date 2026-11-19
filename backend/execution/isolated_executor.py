from typing import Dict, Any
from execution.base import BaseExecutor


class IsolatedExecutor(BaseExecutor):
    """
    Level B isolated execution interface.
    
    This is a stub implementation. Arbitrary code execution is DISABLED
    unless a verified isolated sandbox is configured.
    
    On Streamlit Community Cloud, no secure sandbox is available.
    This executor will always report as unavailable.
    """

    @property
    def is_available(self) -> bool:
        """Execution is disabled by default for security."""
        return False

    def execute(self, project_dir: str, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Execute is not available. Returns an error result.
        Do not execute arbitrary code in the Streamlit process.
        """
        return {
            'success': False,
            'stdout': '',
            'stderr': 'Code execution is disabled. No verified isolated executor is configured.\n'
                     'This is a security measure - arbitrary code is not executed in the application process.\n'
                     'To enable execution, configure an external sandbox provider (e.g. Docker, E2B).',
            'exit_code': -1,
            'timed_out': False,
            'executor': 'disabled',
        }


class SubprocessExecutor(BaseExecutor):
    """
    Optional subprocess-based executor for local development.
    NOT for production use - only available when explicitly enabled.
    """

    def __init__(self, timeout: int = 30, allowed_commands: list = None):
        self.timeout = timeout
        self.allowed_commands = allowed_commands or ['python', 'python3', 'pytest', 'pip']

    @property
    def is_available(self) -> bool:
        import os
        return os.getenv('ENABLE_CODE_EXECUTION', 'false').lower() == 'true'

    def execute(self, project_dir: str, command: str, timeout: int = None) -> Dict[str, Any]:
        import subprocess

        if not self.is_available:
            return {
                'success': False, 'stdout': '', 'stderr': 'Code execution disabled',
                'exit_code': -1, 'timed_out': False, 'executor': 'disabled',
            }

        # Validate command is allowed
        parts = command.split()
        if not parts or parts[0] not in self.allowed_commands:
            return {
                'success': False, 'stdout': '',
                'stderr': f'Command not allowed: {parts[0] if parts else "empty"}',
                'exit_code': -1, 'timed_out': False, 'executor': 'subprocess',
            }

        try:
            result = subprocess.run(
                command, shell=True, cwd=project_dir,
                capture_output=True, text=True,
                timeout=timeout or self.timeout,
            )
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'exit_code': result.returncode,
                'timed_out': False,
                'executor': 'subprocess',
            }
        except subprocess.TimeoutExpired:
            return {
                'success': False, 'stdout': '', 'stderr': 'Execution timed out',
                'exit_code': -1, 'timed_out': True, 'executor': 'subprocess',
            }
        except Exception as e:
            return {
                'success': False, 'stdout': '', 'stderr': str(e),
                'exit_code': -1, 'timed_out': False, 'executor': 'subprocess',
            }