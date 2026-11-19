"""Observability: aggregate operational stats over the run store.

Everything is computed from SQLite on demand — no counters to keep in
sync, no new infrastructure. The scale here (hundreds of runs, not
millions) makes a full scan cheap, and it stays correct across restarts.
"""
import json
import os
import re
import sqlite3
from typing import Any, Dict, List

from services import run_store

_RETRY_RE = re.compile(r"retrying \(attempt", re.IGNORECASE)

# Failure-cause keywords, ordered by specificity.
_CAUSE_PATTERNS = [
    ("outage", ("unavailable", "high demand", "try again later", "overloaded", "503", "502", "500")),
    ("rate_limit", ("rate limit", "rate_limit", "429", "quota")),
    ("auth", ("401", "unauthorized", "invalid api key", "invalid_api_key")),
    ("malformed", ("parse", "json", "malformed", "no usable")),
]


def _classify_failure(logs: List[str]) -> str:
    for line in reversed(logs):
        if "FAILED:" in line:
            low = line.lower()
            for cause, words in _CAUSE_PATTERNS:
                if any(w in low for w in words):
                    return cause
            return "other"
    return "unknown"


def compute_stats(limit: int = 500) -> Dict[str, Any]:
    """Aggregate run stats; never raises (empty stats on any DB issue)."""
    try:
        rows = _fetch_runs(limit)
    except Exception:  # noqa: BLE001 - observability must never break the app
        return {"runs": {}, "error": "stats unavailable"}

    total = len(rows)
    by_status: Dict[str, int] = {}
    durations: List[float] = []
    file_counts: List[int] = []
    line_counts: List[int] = []
    self_heals = 0
    causes: Dict[str, int] = {}
    languages: Dict[str, Dict[str, int]] = {}

    for r in rows:
        status = r["status"]
        by_status[status] = by_status.get(status, 0) + 1
        logs = r["logs"]
        self_heals += len(_RETRY_RE.findall("\n".join(logs)))
        if status == "failed":
            cause = _classify_failure(logs)
            causes[cause] = causes.get(cause, 0) + 1

        started, completed = r.get("started_at"), r.get("completed_at")
        if isinstance(started, (int, float)) and isinstance(completed, (int, float)):
            durations.append(max(completed - started, 0.0))

        files = r["files"]
        file_counts.append(len(files))
        lines = 0
        for f in files:
            path = str(f.get("path", ""))
            ext = (os.path.splitext(path)[1] or ".txt").lstrip(".").lower()
            n = len(str(f.get("content", "")).split("\n"))
            lines += n
            d = languages.setdefault(ext, {"files": 0, "lines": 0})
            d["files"] += 1
            d["lines"] += n
        line_counts.append(lines)

    def _avg(values: List[Any]) -> Any:
        return round(sum(values) / len(values), 1) if values else None

    return {
        "runs": {
            "total": total,
            "by_status": by_status,
            "failure_causes": causes,
        },
        "builds": {
            "avg_duration_seconds": _avg(durations),
            "avg_files": _avg(file_counts),
            "avg_lines": _avg(line_counts),
            "self_heals_total": self_heals,
        },
        "languages": dict(
            sorted(languages.items(), key=lambda kv: kv[1]["lines"], reverse=True)[:8]
        ),
    }


def _fetch_runs(limit: int) -> List[Dict[str, Any]]:
    """Raw run rows (logs/files decoded), backend-aware via run_store."""
    return run_store.fetch_stats_rows(limit)
