import uuid
import time
import os
from typing import List, Dict, Optional, Any

from storage.repository import Repository, ProjectRecord
from security.path_validator import resolve_safe_path, safe_create_project_zip, safe_extract_zip, list_project_files
from config.settings import settings


class ProjectService:
    """Service for managing projects with durable persistence."""

    def __init__(self, repo: Repository):
        self.repo = repo
        self.projects_dir = settings.PROJECTS_DIR
        os.makedirs(self.projects_dir, exist_ok=True)

    def _project_dir(self, project_id: str) -> str:
        return os.path.join(self.projects_dir, project_id)

    def create_project(self, name: str, description: str = "", language: str = "python") -> ProjectRecord:
        """Create a new project."""
        project_id = str(uuid.uuid4())
        project = ProjectRecord(
            id=project_id,
            name=name,
            description=description,
            language=language,
        )
        self.repo.create_project(project)
        os.makedirs(self._project_dir(project_id), exist_ok=True)
        self.repo.save_audit_event({
            'type': 'project_create', 'project_id': project_id,
            'details': {'name': name}, 'timestamp': time.time(),
        })
        return project

    def get_project(self, project_id: str) -> Optional[ProjectRecord]:
        return self.repo.get_project(project_id)

    def list_projects(self) -> List[ProjectRecord]:
        return self.repo.list_projects()

    def rename_project(self, project_id: str, new_name: str) -> None:
        self.repo.update_project(project_id, name=new_name)
        self.repo.save_audit_event({
            'type': 'project_rename', 'project_id': project_id,
            'details': {'new_name': new_name}, 'timestamp': time.time(),
        })

    def delete_project(self, project_id: str) -> None:
        import shutil
        proj_dir = self._project_dir(project_id)
        if os.path.exists(proj_dir):
            shutil.rmtree(proj_dir, ignore_errors=True)
        self.repo.delete_project(project_id)
        self.repo.save_audit_event({
            'type': 'project_delete', 'project_id': project_id,
            'details': {}, 'timestamp': time.time(),
        })

    def get_project_dir(self, project_id: str) -> str:
        return self._project_dir(project_id)

    def save_file(self, project_id: str, path: str, content: str, created_by: str = "user") -> int:
        """Save a file to both DB and filesystem."""
        proj_dir = self._project_dir(project_id)
        full_path = resolve_safe_path(proj_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        version = self.repo.save_file(project_id, path, content, created_by)
        self.repo.save_audit_event({
            'type': 'file_save', 'project_id': project_id,
            'details': {'path': path, 'version': version}, 'timestamp': time.time(),
        })
        return version

    def get_file(self, project_id: str, path: str) -> Optional[str]:
        """Get file content from DB."""
        fv = self.repo.get_file(project_id, path)
        if fv:
            return fv.content
        # Fallback to filesystem
        proj_dir = self._project_dir(project_id)
        full_path = resolve_safe_path(proj_dir, path)
        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def list_files(self, project_id: str) -> List[Dict[str, Any]]:
        """List all files in a project."""
        return self.repo.list_files(project_id)

    def delete_file(self, project_id: str, path: str) -> None:
        proj_dir = self._project_dir(project_id)
        full_path = resolve_safe_path(proj_dir, path)
        if os.path.exists(full_path):
            os.remove(full_path)
        self.repo.delete_file(project_id, path)
        self.repo.save_audit_event({
            'type': 'file_delete', 'project_id': project_id,
            'details': {'path': path}, 'timestamp': time.time(),
        })

    def rename_file(self, project_id: str, old_path: str, new_path: str) -> None:
        content = self.get_file(project_id, old_path)
        if content is not None:
            self.save_file(project_id, new_path, content)
            self.delete_file(project_id, old_path)

    def search_files(self, project_id: str, query: str) -> List[Dict[str, Any]]:
        """Search files by path name."""
        files = self.list_files(project_id)
        q = query.lower()
        return [f for f in files if q in f.get('path', '').lower()]

    def import_zip(self, project_id: str, zip_data: bytes) -> List[str]:
        """Import a ZIP archive into a project."""
        proj_dir = self._project_dir(project_id)
        extracted = safe_extract_zip(zip_data, proj_dir)
        # Save extracted files to DB
        for path in extracted:
            full_path = resolve_safe_path(proj_dir, path)
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            self.repo.save_file(project_id, path, content, created_by="import")
        self.repo.save_audit_event({
            'type': 'project_import', 'project_id': project_id,
            'details': {'files': len(extracted)}, 'timestamp': time.time(),
        })
        return extracted

    def export_zip(self, project_id: str) -> str:
        """Export a project as a ZIP archive."""
        proj_dir = self._project_dir(project_id)
        zip_path = os.path.join(self.projects_dir, f"{project_id}.zip")
        safe_create_project_zip(proj_dir, zip_path)
        return zip_path

    def get_project_activity(self, project_id: str) -> Dict[str, Any]:
        """Get project activity summary."""
        files = self.list_files(project_id)
        audit = self.repo.get_audit_events(project_id, limit=20)
        return {
            'file_count': len(files),
            'recent_events': audit,
            'last_updated': max((f.get('created_at', 0) for f in files), default=0),
        }
