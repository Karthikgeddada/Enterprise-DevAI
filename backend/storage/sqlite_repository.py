import sqlite3
import json
import hashlib
import time
import os
from typing import List, Dict, Optional, Any

from storage.repository import (
    Repository, ProjectRecord, FileVersion, ConversationRecord,
    TaskRecord, DiffRecord, CheckpointRecord, UsageRecord,
)


SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        created_at REAL DEFAULT 0,
        updated_at REAL DEFAULT 0,
        status TEXT DEFAULT 'active',
        language TEXT DEFAULT 'python',
        metadata TEXT DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS file_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        path TEXT NOT NULL,
        content TEXT NOT NULL,
        version INTEGER NOT NULL,
        hash TEXT NOT NULL,
        created_at REAL,
        created_by TEXT DEFAULT 'user',
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_file_versions_project_path
        ON file_versions(project_id, path, version DESC)""",
    """CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at REAL,
        metadata TEXT DEFAULT '{}',
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )""",
    """CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        sort_order INTEGER DEFAULT 0,
        dependencies TEXT DEFAULT '[]',
        acceptance_criteria TEXT DEFAULT '',
        created_at REAL DEFAULT 0,
        updated_at REAL DEFAULT 0,
        error TEXT,
        result TEXT,
        metadata TEXT DEFAULT '{}',
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )""",
    """CREATE TABLE IF NOT EXISTS diffs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        base_content TEXT,
        proposed_content TEXT,
        diff_text TEXT,
        status TEXT DEFAULT 'proposed',
        created_at REAL DEFAULT 0,
        reviewed_at REAL,
        applied_at REAL,
        reviewer TEXT,
        base_version INTEGER DEFAULT 0,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )""",
    """CREATE TABLE IF NOT EXISTS checkpoints (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        state TEXT NOT NULL,
        context TEXT DEFAULT '{}',
        created_at REAL,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )""",
    """CREATE TABLE IF NOT EXISTS usage_records (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        task_id TEXT,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        estimated_cost REAL DEFAULT 0,
        latency_ms REAL DEFAULT 0,
        created_at REAL,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )""",
    """CREATE TABLE IF NOT EXISTS audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL,
        type TEXT,
        actor TEXT DEFAULT 'system',
        project_id TEXT,
        details TEXT DEFAULT '{}'
    )""",
]


class SQLiteRepository(Repository):
    """SQLite-based persistent repository."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self) -> None:
        conn = self._get_conn()
        try:
            for sql in SCHEMA_SQL:
                conn.execute(sql)
            conn.commit()
        finally:
            conn.close()

    # ---- Projects ----

    def create_project(self, project: ProjectRecord) -> None:
        conn = self._get_conn()
        try:
            now = time.time()
            conn.execute(
                "INSERT INTO projects (id, name, description, created_at, updated_at, status, language, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project.id, project.name, project.description, now, now,
                 project.status, project.language, json.dumps(project.metadata))
            )
            conn.commit()
        finally:
            conn.close()

    def get_project(self, project_id: str) -> Optional[ProjectRecord]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                return None
            return ProjectRecord(
                id=row['id'], name=row['name'], description=row['description'],
                created_at=row['created_at'], updated_at=row['updated_at'],
                status=row['status'], language=row['language'],
                metadata=json.loads(row['metadata'] or '{}'),
            )
        finally:
            conn.close()

    def list_projects(self) -> List[ProjectRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
            return [ProjectRecord(
                id=r['id'], name=r['name'], description=r['description'],
                created_at=r['created_at'], updated_at=r['updated_at'],
                status=r['status'], language=r['language'],
                metadata=json.loads(r['metadata'] or '{}'),
            ) for r in rows]
        finally:
            conn.close()

    def update_project(self, project_id: str, **fields: Any) -> None:
        conn = self._get_conn()
        try:
            fields['updated_at'] = time.time()
            if 'metadata' in fields and isinstance(fields['metadata'], dict):
                fields['metadata'] = json.dumps(fields['metadata'])
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [project_id]
            conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()

    def delete_project(self, project_id: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM file_versions WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM conversations WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM diffs WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM checkpoints WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM usage_records WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        finally:
            conn.close()

    # ---- Files ----

    def save_file(self, project_id: str, path: str, content: str, created_by: str = "user") -> int:
        conn = self._get_conn()
        try:
            # Get current max version
            row = conn.execute(
                "SELECT MAX(version) as max_ver FROM file_versions WHERE project_id = ? AND path = ?",
                (project_id, path)
            ).fetchone()
            version = (row['max_ver'] or 0) + 1
            h = hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
            conn.execute(
                "INSERT INTO file_versions (project_id, path, content, version, hash, created_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, path, content, version, h, time.time(), created_by)
            )
            conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (time.time(), project_id))
            conn.commit()
            return version
        finally:
            conn.close()

    def get_file(self, project_id: str, path: str) -> Optional[FileVersion]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM file_versions WHERE project_id = ? AND path = ? ORDER BY version DESC LIMIT 1",
                (project_id, path)
            ).fetchone()
            if not row:
                return None
            return FileVersion(
                project_id=row['project_id'], path=row['path'], content=row['content'],
                version=row['version'], hash=row['hash'],
                created_at=row['created_at'], created_by=row['created_by'],
            )
        finally:
            conn.close()

    def list_files(self, project_id: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT path, MAX(version) as version, hash, created_at, created_by "
                "FROM file_versions WHERE project_id = ? GROUP BY path ORDER BY path",
                (project_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_file(self, project_id: str, path: str) -> None:
        conn = self._get_conn()
        try:
            # Save a tombstone version
            conn.execute(
                "INSERT INTO file_versions (project_id, path, content, version, hash, created_at, created_by) "
                "VALUES (?, ?, '', (SELECT COALESCE(MAX(version),0)+1 FROM file_versions WHERE project_id=? AND path=?), '', ?, 'system')",
                (project_id, path, project_id, path, time.time())
            )
            conn.commit()
        finally:
            conn.close()

    def get_file_versions(self, project_id: str, path: str) -> List[FileVersion]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM file_versions WHERE project_id = ? AND path = ? ORDER BY version DESC",
                (project_id, path)
            ).fetchall()
            return [FileVersion(
                project_id=r['project_id'], path=r['path'], content=r['content'],
                version=r['version'], hash=r['hash'],
                created_at=r['created_at'], created_by=r['created_by'],
            ) for r in rows]
        finally:
            conn.close()

    # ---- Conversations ----

    def save_conversation(self, conv: ConversationRecord) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO conversations (id, project_id, role, content, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (conv.id, conv.project_id, conv.role, conv.content, conv.created_at, json.dumps(conv.metadata))
            )
            conn.commit()
        finally:
            conn.close()

    def get_conversations(self, project_id: str) -> List[ConversationRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,)
            ).fetchall()
            return [ConversationRecord(
                id=r['id'], project_id=r['project_id'], role=r['role'],
                content=r['content'], created_at=r['created_at'],
                metadata=json.loads(r['metadata'] or '{}'),
            ) for r in rows]
        finally:
            conn.close()

    # ---- Tasks ----

    def create_task(self, task: TaskRecord) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO tasks (id, project_id, plan_id, title, description, status, sort_order, "
                "dependencies, acceptance_criteria, created_at, updated_at, error, result, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task.id, task.project_id, task.plan_id, task.title, task.description,
                 task.status, task.order, json.dumps(task.dependencies),
                 task.acceptance_criteria, time.time(), time.time(),
                 task.error, task.result, json.dumps(task.metadata))
            )
            conn.commit()
        finally:
            conn.close()

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            return TaskRecord(
                id=row['id'], project_id=row['project_id'], plan_id=row['plan_id'],
                title=row['title'], description=row['description'], status=row['status'],
                order=row['sort_order'],
                dependencies=json.loads(row['dependencies'] or '[]'),
                acceptance_criteria=row['acceptance_criteria'],
                created_at=row['created_at'], updated_at=row['updated_at'],
                error=row['error'], result=row['result'],
                metadata=json.loads(row['metadata'] or '{}'),
            )
        finally:
            conn.close()

    def list_tasks(self, project_id: str, plan_id: Optional[str] = None) -> List[TaskRecord]:
        conn = self._get_conn()
        try:
            if plan_id:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE project_id = ? AND plan_id = ? ORDER BY sort_order ASC",
                    (project_id, plan_id)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE project_id = ? ORDER BY sort_order ASC",
                    (project_id,)
                ).fetchall()
            return [TaskRecord(
                id=r['id'], project_id=r['project_id'], plan_id=r['plan_id'],
                title=r['title'], description=r['description'], status=r['status'],
                order=r['sort_order'],
                dependencies=json.loads(r['dependencies'] or '[]'),
                acceptance_criteria=r['acceptance_criteria'],
                created_at=r['created_at'], updated_at=r['updated_at'],
                error=r['error'], result=r['result'],
                metadata=json.loads(r['metadata'] or '{}'),
            ) for r in rows]
        finally:
            conn.close()

    def update_task(self, task_id: str, **fields: Any) -> None:
        conn = self._get_conn()
        try:
            fields['updated_at'] = time.time()
            if 'dependencies' in fields and isinstance(fields['dependencies'], list):
                fields['dependencies'] = json.dumps(fields['dependencies'])
            if 'metadata' in fields and isinstance(fields['metadata'], dict):
                fields['metadata'] = json.dumps(fields['metadata'])
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [task_id]
            conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()

    def delete_task(self, task_id: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
        finally:
            conn.close()

    # ---- Diffs ----

    def save_diff(self, diff: DiffRecord) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO diffs (id, project_id, task_id, file_path, base_content, proposed_content, "
                "diff_text, status, created_at, reviewed_at, applied_at, reviewer, base_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (diff.id, diff.project_id, diff.task_id, diff.file_path,
                 diff.base_content, diff.proposed_content, diff.diff_text,
                 diff.status, diff.created_at, diff.reviewed_at, diff.applied_at,
                 diff.reviewer, diff.base_version)
            )
            conn.commit()
        finally:
            conn.close()

    def get_diffs_for_task(self, task_id: str) -> List[DiffRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM diffs WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,)
            ).fetchall()
            return [DiffRecord(
                id=r['id'], project_id=r['project_id'], task_id=r['task_id'],
                file_path=r['file_path'], base_content=r['base_content'],
                proposed_content=r['proposed_content'], diff_text=r['diff_text'],
                status=r['status'], created_at=r['created_at'],
                reviewed_at=r['reviewed_at'], applied_at=r['applied_at'],
                reviewer=r['reviewer'], base_version=r['base_version'],
            ) for r in rows]
        finally:
            conn.close()

    def get_diffs_for_project(self, project_id: str) -> List[DiffRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM diffs WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,)
            ).fetchall()
            return [DiffRecord(
                id=r['id'], project_id=r['project_id'], task_id=r['task_id'],
                file_path=r['file_path'], base_content=r['base_content'],
                proposed_content=r['proposed_content'], diff_text=r['diff_text'],
                status=r['status'], created_at=r['created_at'],
                reviewed_at=r['reviewed_at'], applied_at=r['applied_at'],
                reviewer=r['reviewer'], base_version=r['base_version'],
            ) for r in rows]
        finally:
            conn.close()

    def update_diff(self, diff_id: str, **fields: Any) -> None:
        conn = self._get_conn()
        try:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [diff_id]
            conn.execute(f"UPDATE diffs SET {set_clause} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()

    # ---- Checkpoints ----

    def save_checkpoint(self, checkpoint: CheckpointRecord) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO checkpoints (id, project_id, task_id, state, context, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (checkpoint.id, checkpoint.project_id, checkpoint.task_id,
                 checkpoint.state, json.dumps(checkpoint.context), checkpoint.created_at)
            )
            conn.commit()
        finally:
            conn.close()

    def get_latest_checkpoint(self, project_id: str, task_id: str) -> Optional[CheckpointRecord]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE project_id = ? AND task_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id, task_id)
            ).fetchone()
            if not row:
                return None
            return CheckpointRecord(
                id=row['id'], project_id=row['project_id'], task_id=row['task_id'],
                state=row['state'],
                context=json.loads(row['context'] or '{}'),
                created_at=row['created_at'],
            )
        finally:
            conn.close()

    def list_checkpoints(self, project_id: str) -> List[CheckpointRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM checkpoints WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,)
            ).fetchall()
            return [CheckpointRecord(
                id=r['id'], project_id=r['project_id'], task_id=r['task_id'],
                state=r['state'],
                context=json.loads(r['context'] or '{}'),
                created_at=r['created_at'],
            ) for r in rows]
        finally:
            conn.close()

    # ---- Usage ----

    def save_usage(self, usage: UsageRecord) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO usage_records (id, project_id, task_id, provider, model, "
                "prompt_tokens, completion_tokens, total_tokens, estimated_cost, latency_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (usage.id, usage.project_id, usage.task_id, usage.provider, usage.model,
                 usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
                 usage.estimated_cost, usage.latency_ms, usage.created_at)
            )
            conn.commit()
        finally:
            conn.close()

    def get_usage(self, project_id: str) -> List[UsageRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM usage_records WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,)
            ).fetchall()
            return [UsageRecord(
                id=r['id'], project_id=r['project_id'], task_id=r['task_id'],
                provider=r['provider'], model=r['model'],
                prompt_tokens=r['prompt_tokens'], completion_tokens=r['completion_tokens'],
                total_tokens=r['total_tokens'], estimated_cost=r['estimated_cost'],
                latency_ms=r['latency_ms'], created_at=r['created_at'],
            ) for r in rows]
        finally:
            conn.close()

    # ---- Audit ----

    def save_audit_event(self, event: Dict[str, Any]) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO audit_events (timestamp, type, actor, project_id, details) VALUES (?, ?, ?, ?, ?)",
                (event.get('timestamp', time.time()), event.get('type', 'unknown'),
                 event.get('actor', 'system'), event.get('project_id'),
                 json.dumps(event.get('details', {})))
            )
            conn.commit()
        finally:
            conn.close()

    def get_audit_events(self, project_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE project_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (project_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()