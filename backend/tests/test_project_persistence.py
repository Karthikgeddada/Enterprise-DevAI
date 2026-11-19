import pytest
import tempfile
import os
from storage.sqlite_repository import SQLiteRepository
from storage.repository import ProjectRecord, ConversationRecord, TaskRecord, CheckpointRecord


class TestProjectPersistence:

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.repo = SQLiteRepository(self.db_path)

    def test_create_and_get_project(self):
        project = ProjectRecord(id="p1", name="Test Project", description="A test")
        self.repo.create_project(project)
        retrieved = self.repo.get_project("p1")
        assert retrieved is not None
        assert retrieved.name == "Test Project"
        assert retrieved.description == "A test"

    def test_list_projects(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Project 1"))
        self.repo.create_project(ProjectRecord(id="p2", name="Project 2"))
        projects = self.repo.list_projects()
        assert len(projects) == 2

    def test_update_project(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Original"))
        self.repo.update_project("p1", name="Renamed")
        retrieved = self.repo.get_project("p1")
        assert retrieved.name == "Renamed"

    def test_delete_project(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Test"))
        self.repo.save_file("p1", "main.py", "print(1)")
        self.repo.delete_project("p1")
        assert self.repo.get_project("p1") is None
        assert self.repo.list_files("p1") == []

    def test_save_and_get_file(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Test"))
        version = self.repo.save_file("p1", "main.py", "print('hello')")
        assert version == 1
        version = self.repo.save_file("p1", "main.py", "print('world')")
        assert version == 2

        file = self.repo.get_file("p1", "main.py")
        assert file is not None
        assert file.content == "print('world')"
        assert file.version == 2

    def test_list_files(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Test"))
        self.repo.save_file("p1", "main.py", "print(1)")
        self.repo.save_file("p1", "util.py", "def x(): pass")
        files = self.repo.list_files("p1")
        assert len(files) == 2
        paths = [f['path'] for f in files]
        assert 'main.py' in paths
        assert 'util.py' in paths

    def test_file_versions(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Test"))
        self.repo.save_file("p1", "file.py", "v1")
        self.repo.save_file("p1", "file.py", "v2")
        self.repo.save_file("p1", "file.py", "v3")
        versions = self.repo.get_file_versions("p1", "file.py")
        assert len(versions) == 3
        assert versions[0].version == 3  # Latest first

    def test_save_and_get_conversation(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Test"))
        self.repo.save_conversation(ConversationRecord(
            id="c1", project_id="p1", role="user", content="Hello", created_at=1.0
        ))
        convs = self.repo.get_conversations("p1")
        assert len(convs) == 1
        assert convs[0].content == "Hello"

    def test_create_and_get_task(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Test"))
        task = TaskRecord(
            id="t1", project_id="p1", plan_id="plan1",
            title="Task 1", description="Do something"
        )
        self.repo.create_task(task)
        retrieved = self.repo.get_task("t1")
        assert retrieved is not None
        assert retrieved.title == "Task 1"

    def test_update_task(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Test"))
        self.repo.create_task(TaskRecord(
            id="t1", project_id="p1", plan_id="plan1",
            title="Task 1", description="Test"
        ))
        self.repo.update_task("t1", status="completed")
        retrieved = self.repo.get_task("t1")
        assert retrieved.status == "completed"

    def test_checkpoint_save_and_restore(self):
        self.repo.create_project(ProjectRecord(id="p1", name="Test"))
        self.repo.create_task(TaskRecord(
            id="t1", project_id="p1", plan_id="plan1",
            title="Task 1", description="Test"
        ))
        cp = CheckpointRecord(
            id="cp1", project_id="p1", task_id="t1",
            state="running", context={'data': 'test'}, created_at=1.0
        )
        self.repo.save_checkpoint(cp)

        restored = self.repo.get_latest_checkpoint("p1", "t1")
        assert restored is not None
        assert restored.state == "running"
        assert restored.context == {'data': 'test'}

    def test_restart_recovery(self):
        # Simulate restart by creating a new repo instance with same DB
        self.repo.create_project(ProjectRecord(id="p1", name="Test"))
        self.repo.save_file("p1", "main.py", "print('hello')")
        self.repo.create_task(TaskRecord(
            id="t1", project_id="p1", plan_id="plan1",
            title="Task 1", description="Test", status="paused"
        ))

        # New repo instance - simulates restart
        repo2 = SQLiteRepository(self.db_path)
        assert repo2.get_project("p1") is not None
        assert repo2.get_file("p1", "main.py") is not None
        assert repo2.get_task("t1") is not None
        assert repo2.get_task("t1").status == "paused"