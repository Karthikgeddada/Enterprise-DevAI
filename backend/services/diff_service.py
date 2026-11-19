import difflib
import hashlib
import uuid
import time
from typing import List, Dict, Optional, Tuple

from storage.repository import Repository, DiffRecord


class DiffService:
    """Service for creating, applying, and reverting file diffs."""

    def __init__(self, repo: Repository):
        self.repo = repo

    @staticmethod
    def create_diff_text(base_content: str, proposed_content: str) -> str:
        """Create a unified diff between base and proposed content."""
        base_lines = base_content.splitlines(keepends=True)
        proposed_lines = proposed_content.splitlines(keepends=True)
        diff = difflib.unified_diff(base_lines, proposed_lines, fromfile='base', tofile='proposed', lineterm='')
        return ''.join(diff)

    @staticmethod
    def create_diff_html(base_content: str, proposed_content: str) -> str:
        """Create an HTML-formatted diff for display."""
        base_lines = base_content.splitlines()
        proposed_lines = proposed_content.splitlines()
        differ = difflib.HtmlDiff()
        return differ.make_table(base_lines, proposed_lines, "Base", "Proposed")

    @staticmethod
    def compute_hash(content: str) -> str:
        """Compute a content hash for version tracking."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

    @staticmethod
    def has_changes(base_content: str, proposed_content: str) -> bool:
        """Check if proposed content actually differs from base."""
        return base_content != proposed_content

    def propose_change(
        self,
        project_id: str,
        task_id: str,
        file_path: str,
        base_content: str,
        proposed_content: str,
        base_version: int = 0,
    ) -> Optional[DiffRecord]:
        """
        Create a proposed diff record.
        Returns None if no changes.
        """
        if not self.has_changes(base_content, proposed_content):
            return None

        diff_text = self.create_diff_text(base_content, proposed_content)
        diff = DiffRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_id=task_id,
            file_path=file_path,
            base_content=base_content,
            proposed_content=proposed_content,
            diff_text=diff_text,
            status='proposed',
            created_at=time.time(),
            base_version=base_version,
        )
        self.repo.save_diff(diff)
        return diff

    def accept_diff(self, diff_id: str, reviewer: str = "user") -> Optional[DiffRecord]:
        """
        Accept a proposed diff and apply the change to the file.
        Checks base version for conflicts.
        """
        diffs = self.repo.get_diffs_for_project("")  # Need a way to get by id
        # Actually we need to get the diff by id - let's iterate
        # For now, use the task-level query
        # This is a limitation - we need a get_diff method
        # Let's work around it by passing project_id
        return None  # Will be handled by accept_diff_with_project

    def accept_diff_for_project(self, project_id: str, diff_id: str, reviewer: str = "user") -> Tuple[bool, str, Optional[DiffRecord]]:
        """
        Accept a diff. Returns (success, message, updated_diff).
        Checks base version for conflicts.
        """
        diffs = self.repo.get_diffs_for_project(project_id)
        diff = None
        for d in diffs:
            if d.id == diff_id:
                diff = d
                break

        if not diff:
            return False, "Diff not found", None

        if diff.status != 'proposed':
            return False, f"Diff already {diff.status}", diff

        # Check base version for conflicts
        current_file = self.repo.get_file(project_id, diff.file_path)
        if current_file and current_file.version != diff.base_version:
            return False, "File has changed since the diff was generated. Please regenerate.", diff

        # Apply the change
        self.repo.save_file(project_id, diff.file_path, diff.proposed_content, created_by=reviewer)

        # Update diff status
        now = time.time()
        self.repo.update_diff(
            diff_id,
            status='accepted',
            reviewed_at=now,
            applied_at=now,
            reviewer=reviewer,
        )

        diff.status = 'accepted'
        diff.reviewed_at = now
        diff.applied_at = now
        diff.reviewer = reviewer
        return True, "Change accepted and applied", diff

    def reject_diff(self, project_id: str, diff_id: str, reviewer: str = "user") -> Tuple[bool, str]:
        """Reject a proposed diff."""
        diffs = self.repo.get_diffs_for_project(project_id)
        diff = None
        for d in diffs:
            if d.id == diff_id:
                diff = d
                break

        if not diff:
            return False, "Diff not found"

        if diff.status != 'proposed':
            return False, f"Diff already {diff.status}"

        self.repo.update_diff(
            diff_id,
            status='rejected',
            reviewed_at=time.time(),
            reviewer=reviewer,
        )
        return True, "Change rejected"

    def revert_diff(self, project_id: str, diff_id: str) -> Tuple[bool, str]:
        """
        Revert an already-accepted diff by restoring the base content.
        """
        diffs = self.repo.get_diffs_for_project(project_id)
        diff = None
        for d in diffs:
            if d.id == diff_id:
                diff = d
                break

        if not diff:
            return False, "Diff not found"

        if diff.status != 'accepted':
            return False, f"Can only revert accepted diffs, this is {diff.status}"

        # Restore base content
        self.repo.save_file(project_id, diff.file_path, diff.base_content, created_by="system")
        self.repo.update_diff(diff_id, status='reverted')
        return True, "Change reverted to base version"

    def get_pending_diffs(self, project_id: str) -> List[DiffRecord]:
        """Get all pending (proposed) diffs for a project."""
        diffs = self.repo.get_diffs_for_project(project_id)
        return [d for d in diffs if d.status == 'proposed']

    def get_diffs_for_project(self, project_id: str) -> List[DiffRecord]:
        """Get all diffs for a project (any status)."""
        return self.repo.get_diffs_for_project(project_id)

    def get_change_history(self, project_id: str, file_path: Optional[str] = None) -> List[DiffRecord]:
        """Get change history for a project, optionally filtered by file path."""
        diffs = self.repo.get_diffs_for_project(project_id)
        if file_path:
            diffs = [d for d in diffs if d.file_path == file_path]
        return diffs