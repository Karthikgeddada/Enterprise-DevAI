"""Shared pytest fixtures.

Point RUNS_DB (the SQLite run store) at a throwaway session-scoped path so
no test ever touches a real database file, and each test module can still
override it with monkeypatch for restart simulations.
"""
import os
import tempfile

import pytest

from services import run_store


@pytest.fixture(scope="session", autouse=True)
def _isolated_runs_db():
    with tempfile.TemporaryDirectory(prefix="dtai-tests-") as tmp:
        os.environ["RUNS_DB"] = os.path.join(tmp, "runs.db")
        run_store.reset_broken()
        yield
        os.environ.pop("RUNS_DB", None)
