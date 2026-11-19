import pytest
import tempfile
import os
from services.diff_service import DiffService
from storage.sqlite_repository import SQLiteRepository


class TestDiffPatch:

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.repo = SQLiteRepository(self.db_path)
        self.diff_service = DiffService(self.repo)
        self.project_id = "test-project"
        from storage.repository import ProjectRecord
        self.repo.create_project(ProjectRecord(id=self.project_id, name="Test"))

    def test_create_diff_text(self):
        base = "line1\nline2\nline3"
        proposed = "line1\nmodified\nline3"
        diff = DiffService.create_diff_text(base, proposed)
        assert '---' in diff
        assert '+++' in diff
        assert 'modified' in diff

    def test_has_changes_true(self):
        assert DiffService.has_changes("a", "b")

    def test_has_changes_false(self):
        assert not DiffService.has_changes("a", "a")

    def test_compute_hash(self):
        h1 = DiffService.compute_hash("content")
        h2 = DiffService.compute_hash("content")
        h3 = DiffService.compute_hash("different")
        assert h1 == h2
        assert h1 != h3

    def test_propose_change(self):
        self.repo.save_file(self.project_id, "test.py", "print('hello')")
        base = "print('hello')"
        proposed = "print('world')"
        diff = self.diff_service.propose_change(
            self.project_id, "task1", "test.py", base, proposed, base_version=1
        )
        assert diff is not None
        assert diff.status == 'proposed'
        assert diff.base_content == base
        assert diff.proposed_content == proposed

    def test_propose_no_change(self):
        diff = self.diff_service.propose_change(
            self.project_id, "task1", "test.py", "same", "same"
        )
        assert diff is None

    def test_accept_diff(self):
        self.repo.save_file(self.project_id, "app.py", "x = 1")
        diff = self.diff_service.propose_change(
            self.project_id, "task1", "app.py", "x = 1", "x = 2", base_version=1
        )
        success, msg, updated = self.diff_service.accept_diff_for_project(
            self.project_id, diff.id
        )
        assert success
        assert updated.status == 'accepted'
        # Verify file was updated
        file = self.repo.get_file(self.project_id, "app.py")
        assert file.content == "x = 2"

    def test_reject_diff(self):
        diff = self.diff_service.propose_change(
            self.project_id, "task1", "app.py", "base", "proposed"
        )
        success, msg = self.diff_service.reject_diff(self.project_id, diff.id)
        assert success

    def test_revert_diff(self):
        self.repo.save_file(self.project_id, "file.py", "original")
        diff = self.diff_service.propose_change(
            self.project_id, "task1", "file.py", "original", "changed", base_version=1
        )
        self.diff_service.accept_diff_for_project(self.project_id, diff.id)
        success, msg = self.diff_service.revert_diff(self.project_id, diff.id)
        assert success
        file = self.repo.get_file(self.project_id, "file.py")
        assert file.content == "original"

    def test_accept_conflict_detection(self):
        self.repo.save_file(self.project_id, "f.py", "v1")
        diff = self.diff_service.propose_change(
            self.project_id, "task1", "f.py", "v1", "v2", base_version=1
        )
        # Change the file after diff was created
        self.repo.save_file(self.project_id, "f.py", "v1_modified")
        # Now accept should detect conflict
        success, msg, _ = self.diff_service.accept_diff_for_project(
            self.project_id, diff.id
        )
        assert not success
        assert 'changed' in msg.lower() or 'conflict' in msg.lower()