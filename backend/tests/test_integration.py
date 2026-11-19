import pytest
import tempfile
import os
import io
import zipfile

from storage.sqlite_repository import SQLiteRepository
from storage.repository import ProjectRecord, TaskRecord
from services.project_service import ProjectService
from services.task_service import TaskService
from services.diff_service import DiffService
from services.checkpoint_service import CheckpointService
from services.validation_service import ValidationService
from security.path_validator import PathValidationError
from execution.isolated_executor import IsolatedExecutor
from config.settings import settings


class TestIntegration:

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.projects_dir = os.path.join(self.tmpdir, "projects")
        os.environ['DEVTEAM_DB_PATH'] = self.db_path
        os.environ['DEVTEAM_PROJECTS_DIR'] = self.projects_dir
        os.makedirs(self.projects_dir, exist_ok=True)

        self.repo = SQLiteRepository(self.db_path)
        self.project_service = ProjectService(self.repo)
        self.task_service = TaskService(self.repo)
        self.diff_service = DiffService(self.repo)
        self.checkpoint_service = CheckpointService(self.repo)
        self.validation_service = ValidationService()

    def test_create_project_save_file_retrieve(self):
        project = self.project_service.create_project("Test", "Integration test")
        self.project_service.save_file(project.id, "main.py", "print('hello')")
        content = self.project_service.get_file(project.id, "main.py")
        assert content == "print('hello')"
        files = self.project_service.list_files(project.id)
        assert len(files) == 1

    def test_create_plan_and_tasks(self):
        project = self.project_service.create_project("Test", "Integration")
        tasks_data = [
            {'title': 'Setup', 'description': 'Create structure'},
            {'title': 'Code', 'description': 'Write code', 'dependencies': [0]},
        ]
        task_records = self.task_service.create_plan(project.id, "plan1", tasks_data)
        assert len(task_records) == 2
        assert task_records[0].title == 'Setup'
        assert task_records[1].dependencies == [0]

    def test_accept_change_persists(self):
        project = self.project_service.create_project("Test", "Integration")
        self.project_service.save_file(project.id, "app.py", "x = 1")

        # Propose change
        diff = self.diff_service.propose_change(
            project.id, "task1", "app.py", "x = 1", "x = 2", base_version=1
        )
        assert diff is not None

        # Accept change
        success, msg, _ = self.diff_service.accept_diff_for_project(project.id, diff.id)
        assert success

        # Verify persistence
        content = self.project_service.get_file(project.id, "app.py")
        assert content == "x = 2"

    def test_reject_change_preserves_file(self):
        project = self.project_service.create_project("Test", "Integration")
        self.project_service.save_file(project.id, "app.py", "original")

        diff = self.diff_service.propose_change(
            project.id, "task1", "app.py", "original", "modified"
        )
        success, msg = self.diff_service.reject_diff(project.id, diff.id)
        assert success

        content = self.project_service.get_file(project.id, "app.py")
        assert content == "original"

    def test_unrelated_files_preserved(self):
        project = self.project_service.create_project("Test", "Integration")
        self.project_service.save_file(project.id, "file_a.py", "content_a")
        self.project_service.save_file(project.id, "file_b.py", "content_b")

        # Only modify file_a
        diff = self.diff_service.propose_change(
            project.id, "task1", "file_a.py", "content_a", "modified_a", base_version=1
        )
        self.diff_service.accept_diff_for_project(project.id, diff.id)

        # file_b should be unchanged
        assert self.project_service.get_file(project.id, "file_b.py") == "content_b"
        assert self.project_service.get_file(project.id, "file_a.py") == "modified_a"

    def test_checkpoint_preservation_on_quota_error(self):
        project = self.project_service.create_project("Test", "Integration")
        self.project_service.save_file(project.id, "app.py", "v1")

        # Create a checkpoint
        self.checkpoint_service.create_checkpoint(
            project.id, "task1", "failed",
            {'error': 'quota_exhausted', 'saved_files': ['app.py']}
        )

        # Verify checkpoint exists
        cp = self.checkpoint_service.get_latest(project.id, "task1")
        assert cp is not None
        assert cp.state == "failed"
        assert cp.context['saved_files'] == ['app.py']

        # File should still be there
        assert self.project_service.get_file(project.id, "app.py") == "v1"

    def test_restart_recovery(self):
        project = self.project_service.create_project("Test", "Integration")
        self.project_service.save_file(project.id, "main.py", "print(1)")

        # Simulate restart with new repo instance
        repo2 = SQLiteRepository(self.db_path)
        project_service2 = ProjectService(repo2)

        assert project_service2.get_project(project.id) is not None
        assert project_service2.get_file(project.id, "main.py") == "print(1)"

    def test_export_project_zip(self):
        project = self.project_service.create_project("Test", "Integration")
        self.project_service.save_file(project.id, "main.py", "print('hello')")
        self.project_service.save_file(project.id, "utils.py", "def util(): pass")

        zip_path = self.project_service.export_zip(project.id)
        assert os.path.exists(zip_path)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            assert 'main.py' in names
            assert 'utils.py' in names

    def test_invalid_path_rejected(self):
        project = self.project_service.create_project("Test", "Integration")

        with pytest.raises(PathValidationError):
            self.project_service.save_file(project.id, "../../../etc/passwd", "malicious")

    def test_code_execution_disabled(self):
        executor = IsolatedExecutor()
        assert not executor.is_available
        result = executor.execute("/tmp", "python script.py")
        assert not result['success']
        assert 'disabled' in result['stderr'].lower()

    def test_static_validation_on_real_files(self):
        project = self.project_service.create_project("Test", "Integration")
        self.project_service.save_file(project.id, "main.py", "print('hello')")
        self.project_service.save_file(project.id, "config.json", '{"key": "value"}')

        files = [
            {'path': 'main.py', 'content': "print('hello')"},
            {'path': 'config.json', 'content': '{"key": "value"}'},
        ]
        result = self.validation_service.run_static_validation(project.id, files)
        assert result.passed

    def test_task_state_transitions_integration(self):
        project = self.project_service.create_project("Test", "Integration")
        task_records = self.task_service.create_plan(project.id, "plan1", [
            {'title': 'T1', 'description': 'Task 1'},
        ])
        task = task_records[0]

        # pending -> running -> awaiting_review -> validating -> completed
        self.task_service.transition_task(task.id, 'running')
        assert self.task_service.get_task(task.id).status == 'running'

        self.task_service.transition_task(task.id, 'awaiting_review')
        assert self.task_service.get_task(task.id).status == 'awaiting_review'

        self.task_service.transition_task(task.id, 'validating')
        assert self.task_service.get_task(task.id).status == 'validating'

        self.task_service.transition_task(task.id, 'completed')
        assert self.task_service.get_task(task.id).status == 'completed'

    def test_duplicate_task_prevention(self):
        """Verify that already-completed tasks aren't re-executed."""
        project = self.project_service.create_project("Test", "Integration")
        task_records = self.task_service.create_plan(project.id, "plan1", [
            {'title': 'T1', 'description': 'Task 1'},
        ])
        task = task_records[0]

        # Complete the task (through proper state machine)
        self.task_service.transition_task(task.id, 'running')
        self.task_service.transition_task(task.id, 'awaiting_review')
        self.task_service.transition_task(task.id, 'validating')
        self.task_service.transition_task(task.id, 'completed')
        assert self.task_service.get_task(task.id).status == 'completed'

        # Should not be able to transition from completed
        with pytest.raises(ValueError):
            self.task_service.transition_task(task.id, 'running')