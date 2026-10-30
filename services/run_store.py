"""SQLite persistence for generation runs.

The in-memory dict in generation_service stays the live working copy (the
pipeline mutates status/logs on every step). This module mirrors every
state change to SQLite and rehydrates runs after a worker restart, so
continue-mode ("Previous run not found. The server may have restarted.")
survives restarts and polling clients keep their history.

Honest scoping (on free-tier hosts the disk is often ephemeral anyway):
- Survives: worker crashes/restarts within a deploy, local dev restarts.
- Does not survive: filesystem resets on redeploy/scale-out; for that you'd
  move to managed Postgres. This layer is deliberately structured so that
  swap is a drop-in (same save/load contract).

Safety: if the DB is unavailable (bad path, disk full, read-only FS) the
module disables itself and the app keeps running purely in memory -
persistence must never take the app down.

Env: RUNS_DB (default data/runs.db).
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


def _db_path() -> str:
    # Read lazily so tests (and env changes) are picked up.
    return os.getenv("RUNS_DB", "data/runs.db")


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
) -> None:
    """Upsert a run snapshot. Never raises."""
    if _broken:
        return
    try:
        with _lock:
            conn = _connect()
            try:
                conn.execute(
                    """INSERT INTO runs (run_id, status, logs, files, prompt, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(run_id) DO UPDATE SET
                           status = excluded.status,
                           logs = excluded.logs,
                           files = excluded.files,
                           prompt = excluded.prompt,
                           updated_at = excluded.updated_at""",
                    (
                        run_id,
                        status,
                        json.dumps([str(l) for l in logs]),
                        json.dumps(files),
                        prompt,
                        time.time(),
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
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT status, logs, files, prompt FROM runs WHERE run_id = ?",
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
        }
    except Exception as e:  # noqa: BLE001
        _fail(e)
        return None


def reset_broken() -> None:
    """Test helper: re-enable persistence after a simulated failure."""
    global _broken
    _broken = False
