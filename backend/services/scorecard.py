"""Scorecard: a run's build statistics, computed purely from stored state.

Everything derives from data the app already records (files, logs, run
lifecycle timestamps), so the scorecard works for any past run — nothing
extra is tracked at generation time.
"""
import os
import re
from typing import Any, Dict, List, Optional

# Both engines log self-heal events identically ("retrying (attempt 2/3)...").
_RETRY_RE = re.compile(r"retrying \(attempt", re.IGNORECASE)


def _lines(content: Any) -> int:
    return len(str(content or "").split("\n"))


def compute_scorecard(run: Dict[str, Any]) -> Dict[str, Any]:
    """Return the scorecard dict for a run dict (live or rehydrated)."""
    files: List[Dict[str, Any]] = run.get("files", []) or []
    logs = "\n".join(str(l) for l in (run.get("logs") or []))

    total_lines = 0
    languages: Dict[str, Dict[str, int]] = {}
    for f in files:
        path = str(f.get("path", ""))
        ext = (os.path.splitext(path)[1] or ".txt").lstrip(".").lower()
        n = _lines(f.get("content"))
        total_lines += n
        d = languages.setdefault(ext, {"files": 0, "lines": 0})
        d["files"] += 1
        d["lines"] += n

    paths = [str(f.get("path", "")) for f in files]
    checks = {
        "readme": any(p.upper() == "README.MD" for p in paths),
        "architecture_doc": any(p.upper() == "ARCHITECTURE.MD" for p in paths),
        "architecture_diagram": any(p.upper() == "ARCHITECTURE.MMD" for p in paths),
        "tests": any("test" in p.lower() for p in paths),
    }

    largest = max(files, key=lambda f: _lines(f.get("content")), default=None)

    started = run.get("started_at")
    completed = run.get("completed_at")
    duration: Optional[float] = (
        round(completed - started, 1)
        if isinstance(started, (int, float)) and isinstance(completed, (int, float))
        else None
    )

    return {
        "run_id": run.get("run_id", ""),
        "status": run.get("status", ""),
        "prompt": run.get("prompt", ""),
        "file_count": len(files),
        "total_lines": total_lines,
        "languages": dict(
            sorted(languages.items(), key=lambda kv: kv[1]["lines"], reverse=True)
        ),
        "largest_file": ({"path": str(largest.get("path", "")), "lines": _lines(largest.get("content"))}
                         if largest else None),
        "quality_checks": checks,
        "self_heals": len(_RETRY_RE.findall(logs)),
        "duration_seconds": duration,
    }
