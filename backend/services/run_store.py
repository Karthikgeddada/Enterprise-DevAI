"""Persistence for generation runs: SQLite by default, Postgres when
DATABASE_URL is set (e.g. Neon — use the POOLED connection string on
serverless hosts).

The in-memory dict in generation_service stays the live working copy (the
pipeline mutates status/logs on every step). This module mirrors every
state change to the DB and rehydrates runs after a worker restart, so
continue-mode ("Previous run not found. The server may have restarted.")
survives restarts and polling clients keep their history.

Backends
--------
- sqlite: RUNS_DB path (default data/runs.db). Survives worker crashes
  within a deploy; not filesystem resets on redeploy.
- postgres: DATABASE_URL. Survives redeploys and scale-out entirely —
  the recommended production setup. Same save/load contract, same JSON
  column layout (logs/files stored as JSON text), so both backends are
  byte-identical in behavior.

Safety: if the DB is unavailable the module disables itself and the app
keeps running purely in memory - persistence must never take it down.

Env: DATABASE_URL (postgres) or RUNS_DB (sqlite, default data/runs.db).
"""
import json
import os
import sqlite3
import sys
import threading
import time
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_broken = False  # set on first DB error; disables persistence for the process
_pg = None  # lazily imported psycopg2 module


def _db_path() -> str:
    # Read lazily so tests (and env changes) are picked up.
    return os.getenv("RUNS_DB", "data/runs.db")


def _backend() -> str:
    return "postgres" if os.getenv("DATABASE_URL") else "sqlite"


def _pg_connect():
    """Open a Postgres connection (pooled URL recommended on serverless)."""
    global _pg
    if _pg is None:
        import psycopg2
        _pg = psycopg2
    return _pg.connect(os.getenv("DATABASE_URL"), connect_timeout=10)


def _pg_ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS runs (
                   run_id       TEXT PRIMARY KEY,
                   status       TEXT NOT NULL,
                   logs         TEXT NOT NULL,
                   files        TEXT NOT NULL,
                   prompt       TEXT NOT NULL DEFAULT '',
                   updated_at   DOUBLE PRECISION NOT NULL,
                   started_at   DOUBLE PRECISION,
                   completed_at DOUBLE PRECISION
               )"""
        )
    conn.commit()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS runs (
               run_id    TEXT PRIMARY KEY,
               status    TEXT NOT NULL,
               logs      TEXT NOT NULL,
               files     TEXT NOT NULL,
               prompt    TEXT NOT NULL DEFAULT '',
               updated_at REAL NOT NULL
           )"""
    )
    # Lightweight migration for the timing columns (added for scorecards):
    # older DBs simply lack them; "duplicate column name" is ignored.
    for col in ("started_at", "completed_at"):
        try:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} REAL")
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn


def _fail(e: Exception) -> None:
    global _broken
    _broken = True
    print(f"[run_store] persistence disabled after DB error: {e}", file=sys.stderr)


def save(
    run_id: str,
    status: str,
    logs: List[Any],
    files: List[Dict[str, Any]],
    prompt: str = "",
    started_at: Optional[float] = None,
    completed_at: Optional[float] = None,
) -> None:
    """Upsert a run snapshot. Never raises."""
    if _broken:
        return
    try:
        with _lock:
            if _backend() == "postgres":
                conn = _pg_connect()
                try:
                    _pg_ensure_table(conn)
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO runs (run_id, status, logs, files, prompt, updated_at,
                                                  started_at, completed_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT (run_id) DO UPDATE SET
                                   status = EXCLUDED.status,
                                   logs = EXCLUDED.logs,
                                   files = EXCLUDED.files,
                                   prompt = EXCLUDED.prompt,
                                   updated_at = EXCLUDED.updated_at,
                                   started_at = EXCLUDED.started_at,
                                   completed_at = EXCLUDED.completed_at""",
                            (
                                run_id,
                                status,
                                json.dumps([str(l) for l in logs]),
                                json.dumps(files),
                                prompt,
                                time.time(),
                                started_at,
                                completed_at,
                            ),
                        )
                    conn.commit()
                finally:
                    conn.close()
                return

            conn = _connect()
            try:
                conn.execute(
                    """INSERT INTO runs (run_id, status, logs, files, prompt, updated_at,
                                          started_at, completed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(run_id) DO UPDATE SET
                           status = excluded.status,
                           logs = excluded.logs,
                           files = excluded.files,
                           prompt = excluded.prompt,
                           updated_at = excluded.updated_at,
                           started_at = excluded.started_at,
                           completed_at = excluded.completed_at""",
                    (
                        run_id,
                        status,
                        json.dumps([str(l) for l in logs]),
                        json.dumps(files),
                        prompt,
                        time.time(),
                        started_at,
                        completed_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001 - persistence must never break the app
        _fail(e)


def load(run_id: str) -> Optional[Dict[str, Any]]:
    """Return {'status', 'logs', 'files', 'prompt'} for a run, or None."""
    if _broken:
        return None
    try:
        with _lock:
            if _backend() == "postgres":
                conn = _pg_connect()
                try:
                    _pg_ensure_table(conn)
                    with conn.cursor() as cur:
                        cur.execute(
                            """SELECT status, logs, files, prompt, started_at, completed_at
                               FROM runs WHERE run_id = %s""",
                            (run_id,),
                        )
                        row = cur.fetchone()
                finally:
                    conn.close()
            else:
                conn = _connect()
                try:
                    row = conn.execute(
                        """SELECT status, logs, files, prompt, started_at, completed_at
                           FROM runs WHERE run_id = ?""",
                        (run_id,),
                    ).fetchone()
                finally:
                    conn.close()
        if row is None:
            return None
        return {
            "status": row[0],
            "logs": json.loads(row[1]),
            "files": json.loads(row[2]),
            "prompt": row[3],
            "started_at": row[4],
            "completed_at": row[5],
        }
    except Exception as e:  # noqa: BLE001
        _fail(e)
        return None


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    """Newest-first run summaries for the history dashboard. Never raises.

    Files are counted in SQL (json_array_length) so the big JSON blobs are
    never parsed for the listing. Returns [] when persistence is disabled.
    """
    if _broken:
        return []
    try:
        with _lock:
            if _backend() == "postgres":
                conn = _pg_connect()
                try:
                    _pg_ensure_table(conn)
                    with conn.cursor() as cur:
                        cur.execute(
                            """SELECT run_id, status, prompt, updated_at,
                                      json_array_length(files::json)
                               FROM runs ORDER BY updated_at DESC LIMIT %s""",
                            (limit,),
                        )
                        rows = cur.fetchall()
                finally:
                    conn.close()
            else:
                conn = _connect()
                try:
                    rows = conn.execute(
                        """SELECT run_id, status, prompt, updated_at,
                                  json_array_length(files)
                           FROM runs ORDER BY updated_at DESC LIMIT ?""",
                        (limit,),
                    ).fetchall()
                finally:
                    conn.close()
        return [
            {
                "run_id": r[0],
                "status": r[1],
                "prompt": r[2] or "",
                "updated_at": r[3],
                "file_count": r[4] if isinstance(r[4], int) else 0,
            }
            for r in rows
        ]
    except Exception as e:  # noqa: BLE001 - the dashboard must never 500
        _fail(e)
        return []


def fetch_stats_rows(limit: int = 500) -> List[Dict[str, Any]]:
    """Decoded run rows for observability, backend-correct SQL. Never raises."""
    if _broken:
        return []
    try:
        with _lock:
            if _backend() == "postgres":
                conn = _pg_connect()
                try:
                    _pg_ensure_table(conn)
                    with conn.cursor() as cur:
                        cur.execute(
                            """SELECT status, logs, files, started_at, completed_at
                               FROM runs ORDER BY updated_at DESC LIMIT %s""",
                            (limit,),
                        )
                        rows = cur.fetchall()
                finally:
                    conn.close()
            else:
                conn = _connect()
                try:
                    rows = conn.execute(
                        """SELECT status, logs, files, started_at, completed_at
                           FROM runs ORDER BY updated_at DESC LIMIT ?""",
                        (limit,),
                    ).fetchall()
                finally:
                    conn.close()
        return [
            {
                "status": r[0],
                "logs": json.loads(r[1]),
                "files": json.loads(r[2]),
                "started_at": r[3],
                "completed_at": r[4],
            }
            for r in rows
        ]
    except Exception as e:  # noqa: BLE001
        _fail(e)
        return []


def reset_broken() -> None:
    """Test helper: re-enable persistence after a simulated failure."""
    global _broken
    _broken = False
