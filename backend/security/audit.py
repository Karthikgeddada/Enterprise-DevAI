import json
import os
import time
from typing import Optional, Dict, Any


class AuditLogger:
    """Simple audit logger that writes structured events to a JSON-lines file."""

    def __init__(self, log_path: str):
        self.log_path = log_path
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def log_event(self, event_type: str, actor: str = "system", **details: Any) -> None:
        entry = {
            'timestamp': time.time(),
            'type': event_type,
            'actor': actor,
            'details': details,
        }
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')

    def log_file_operation(self, action: str, project_id: str, path: str, actor: str = "user") -> None:
        self.log_event('file_operation', actor, action=action, project_id=project_id, path=path)

    def log_provider_call(self, provider: str, model: str, action: str, success: bool, error: Optional[str] = None) -> None:
        self.log_event('provider_call', action=action, provider=provider, model=model, success=success, error=error)

    def log_security_event(self, event: str, details: Dict[str, Any]) -> None:
        self.log_event('security', details=details, event=event)

    def log_task_event(self, task_id: str, event: str, **details: Any) -> None:
        self.log_event('task', task_id=task_id, event=event, **details)