"""Request guards for the expensive/exploit-prone API endpoints.

Two independent protections:

1. Optional API key: when the API_KEY env var is set, mutating/expensive
   endpoints (/generate, /download) require a matching X-API-Key header (or
   ?api_key= query param, so the ZIP download link works from an <a> tag).
   Unset (default) = open, so the public demo keeps working.
   Read-only endpoints (/status, /files) stay open: run ids are unguessable
   12-char hex strings, and the static frontend cannot hold a secret anyway.

2. Per-IP rate limit on /generate: a simple in-memory sliding window. This is
   an honest single-process limit - at real scale it would move to Redis (or
   an edge rate limiter); it exists to stop casual quota abuse, not to be a
   production-grade limiter.

Env vars: API_KEY (empty = open), RATE_LIMIT_MAX (default 5),
RATE_LIMIT_WINDOW (default 600 seconds).
"""
import os
import time
from collections import deque

from fastapi import HTTPException, Request


def _api_key() -> str:
    # Read at call time so tests (and hot reloads) see env changes.
    return os.getenv("API_KEY", "").strip()


def _rate_limit_max() -> int:
    try:
        return max(1, int(os.getenv("RATE_LIMIT_MAX", "5")))
    except ValueError:
        return 5


def _rate_limit_window() -> int:
    try:
        return max(1, int(os.getenv("RATE_LIMIT_WINDOW", "600")))
    except ValueError:
        return 600


def provided_key(request: Request) -> str:
    return (
        request.headers.get("X-API-Key", "").strip()
        or request.query_params.get("api_key", "").strip()
    )


def require_api_key(request: Request) -> None:
    expected = _api_key()
    if not expected:
        return  # no key configured - endpoint stays open
    if provided_key(request) != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


# ip -> timestamps of recent /generate calls (single process only)
_rate_buckets: dict = {}


def rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _rate_limit_window()
    bucket = _rate_buckets.setdefault(ip, deque())
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= _rate_limit_max():
        raise HTTPException(
            status_code=429,
            detail="Rate limit reached. Please wait a few minutes and try again.",
        )
    bucket.append(now)


def reset_rate_limiter() -> None:
    """Test helper."""
    _rate_buckets.clear()
