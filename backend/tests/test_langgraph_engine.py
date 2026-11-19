"""Tests for the LangGraph pipeline engine (services/langgraph_pipeline.py)
and the PIPELINE_ENGINE dispatch in services/generation_service.py.

Agents are faked with plain async functions - these tests cover the graph
orchestration (conditional edges, coder retry, status/log contract) with no
network calls.
"""
import asyncio
import sys

import pytest

import services
import services.generation_service as gs
import services.langgraph_pipeline as lg
from providers.errors import ErrorCategory, ProviderError

CODE = [{"path": "app.py", "content": "print('hi')"}]
FIXED = [{"path": "app.py", "content": "print('fixed')"}]
TESTS = [{"path": "test_app.py", "content": "def test_x(): pass"}]
DOCS = [{"path": "README.md", "content": "# demo"}]

# The exact status sequence the custom engine emits for a normal run with
# review issues (debugger runs). The LangGraph engine must match it.
FULL_STATUSES = [
    "analyzing_requirements",
    "designing_architecture",
    "generating_code",
    "reviewing",
    "debugging",
    "testing",
    "documenting",
]


def _mock_agents(monkeypatch, review_text="Issue: variable naming is inconsistent.", coder_fn=None):
    """Replace both engines' agent references with deterministic fakes."""
    calls = {"coder": 0, "debugger": 0}

    async def requirement_agent(prompt):
        return "R1: it must work"

    async def architect_agent(prompt, requirements):
        return "Components: A, B"

    async def coder_agent(**kwargs):
        calls["coder"] += 1
        if coder_fn is not None:
            return coder_fn(calls["coder"])
        return [dict(f) for f in CODE]

    async def reviewer_agent(files):
        return review_text

    async def debugger_agent(files, review):
        calls["debugger"] += 1
        return [dict(f) for f in FIXED]

    async def tester_agent(files):
        return [dict(f) for f in TESTS]

    async def documentation_agent(files, requirements):
        return [dict(f) for f in DOCS]

    async def packager_agent(payload):
        calls["packaged"] = payload

    for mod in (lg, gs):
        monkeypatch.setattr(mod, "requirement_agent", requirement_agent)
        monkeypatch.setattr(mod, "architect_agent", architect_agent)
        monkeypatch.setattr(mod, "coder_agent", coder_agent)
        monkeypatch.setattr(mod, "reviewer_agent", reviewer_agent)
        monkeypatch.setattr(mod, "debugger_agent", debugger_agent)
        monkeypatch.setattr(mod, "tester_agent", tester_agent)
        monkeypatch.setattr(mod, "documentation_agent", documentation_agent)
        monkeypatch.setattr(mod, "packager_agent", packager_agent)
    return calls


def _run_graph(monkeypatch, prompt="build a demo app", base_files=None, **mock_kwargs):
    calls = _mock_agents(monkeypatch, **mock_kwargs)
    statuses, logs = [], []
    final = asyncio.run(
        lg.execute("run1", prompt, base_files, statuses.append, logs.append)
    )
    return final, statuses, logs, calls


def test_issues_path_runs_debugger(monkeypatch):
    final, statuses, logs, calls = _run_graph(monkeypatch)
    assert statuses == FULL_STATUSES
    assert calls["debugger"] == 1
    # debugger output replaces the coder's files; test + docs are appended
    assert final["final_files"] == FIXED + TESTS + DOCS
    assert calls["packaged"]["run_id"] == "run1"
    assert calls["packaged"]["tests_files"] == TESTS
    assert calls["packaged"]["docs_files"] == DOCS


def test_lgtm_review_skips_debugger(monkeypatch):
    final, statuses, logs, calls = _run_graph(monkeypatch, review_text="LGTM")
    assert "debugging" not in statuses
    assert statuses == [s for s in FULL_STATUSES if s != "debugging"]
    assert calls["debugger"] == 0
    assert any("LGTM" in l for l in logs)
    # without review issues the coder's files pass through untouched
    assert final["final_files"][0]["content"] == "print('hi')"


def test_review_with_extra_text_is_not_lgtm(monkeypatch):
    # "LGTM, but consider renaming..." is NOT a clean LGTM: the debugger runs.
    _, statuses, _, calls = _run_graph(
        monkeypatch, review_text="LGTM, but consider renaming 'x' to 'y'."
    )
    assert "debugging" in statuses
    assert calls["debugger"] == 1


def test_coder_retries_malformed_json(monkeypatch):
    def coder_fn(attempt):
        if attempt == 1:
            raise ProviderError(
                "Coder returned no files (finish_reason=MAX_TOKENS)",
                ErrorCategory.MALFORMED_RESPONSE,
                retryable=False,
            )
        return [dict(f) for f in CODE]

    final, statuses, logs, calls = _run_graph(monkeypatch, coder_fn=coder_fn)
    assert calls["coder"] == 2  # failed once, retried once, succeeded
    assert any("retrying" in l for l in logs)
    # the retry makes "generating_code" fire twice - collapse repeats
    assert list(dict.fromkeys(statuses)) == FULL_STATUSES
    assert final["final_files"]


def test_coder_retry_exhaustion_raises(monkeypatch):
    def coder_fn(attempt):
        raise ProviderError(
            "Coder returned no files (finish_reason=LENGTH)",
            ErrorCategory.MALFORMED_RESPONSE,
            retryable=False,
        )

    calls = _mock_agents(monkeypatch, coder_fn=coder_fn)
    statuses, logs = [], []
    with pytest.raises(ProviderError):
        asyncio.run(lg.execute("run1", "p", None, statuses.append, logs.append))
    assert calls["coder"] == lg.MAX_CODER_ATTEMPTS
    assert any("retrying" in l for l in logs)
    assert statuses[0] == "analyzing_requirements"
    assert statuses[-1] == "generating_code"
    assert "reviewing" not in statuses


def test_non_retryable_coder_error_fails_fast(monkeypatch):
    def coder_fn(attempt):
        raise ProviderError("401 invalid api key", ErrorCategory.AUTH_ERROR, retryable=False)

    calls = _mock_agents(monkeypatch, coder_fn=coder_fn)
    statuses, logs = [], []
    with pytest.raises(ProviderError):
        asyncio.run(lg.execute("run1", "p", None, statuses.append, logs.append))
    assert calls["coder"] == 1  # auth errors must not be retried by the graph
    assert "retrying" not in " ".join(logs)


def test_continue_mode_merges_base_files(monkeypatch):
    change = [{"path": "app.py", "content": "print('v2')"}]
    calls = _mock_agents(
        monkeypatch,
        review_text="LGTM",  # clean review: no debugger overwrite of the merge
        coder_fn=lambda attempt: [dict(f) for f in change],
    )
    statuses, logs = [], []
    final = asyncio.run(
        lg.execute(
            "run1", "add logging", [dict(f) for f in CODE], statuses.append, logs.append
        )
    )
    contents = {f["path"]: f["content"] for f in final["final_files"]}
    assert contents["app.py"] == "print('v2')"  # coder change overlaid the base
    assert any("Continuing development" in l for l in logs)
    assert statuses == [s for s in FULL_STATUSES if s != "debugging"]


class _RecordingRun(dict):
    """dict that records every status mutation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.status_events = []

    def __setitem__(self, key, value):
        if key == "status":
            self.status_events.append(value)
        super().__setitem__(key, value)


def _seed_run(run_id):
    run = _RecordingRun({"status": "starting", "logs": ["Run started."], "files": []})
    gs._runs[run_id] = run
    return run


def test_status_and_log_parity_with_custom_engine(monkeypatch):
    """Both engines must produce identical status events, files and logs."""
    _mock_agents(monkeypatch)

    monkeypatch.delenv("PIPELINE_ENGINE", raising=False)
    custom_run = _seed_run("parity-custom")
    asyncio.run(gs._run_pipeline("parity-custom", "build a demo app"))

    monkeypatch.setenv("PIPELINE_ENGINE", "langgraph")
    graph_run = _seed_run("parity-graph")
    asyncio.run(gs._run_pipeline("parity-graph", "build a demo app"))

    assert graph_run.status_events == custom_run.status_events
    assert graph_run["files"] == custom_run["files"]
    assert graph_run["logs"] == custom_run["logs"]
    assert custom_run["status"] == "completed"


def test_default_engine_is_custom(monkeypatch):
    monkeypatch.delenv("PIPELINE_ENGINE", raising=False)
    used = []

    async def fake_custom(run_id, prompt, base_files=None):
        used.append(run_id)

    monkeypatch.setattr(gs, "_run_custom_pipeline", fake_custom)
    _seed_run("engine-default")
    asyncio.run(gs._run_pipeline("engine-default", "p"))
    assert used == ["engine-default"]  # default (and any unknown value) = custom


def test_langgraph_engine_dispatch(monkeypatch):
    monkeypatch.setenv("PIPELINE_ENGINE", "langgraph")
    seen = {}

    async def fake_execute(run_id, prompt, base_files, set_status, log):
        seen["args"] = (run_id, prompt, base_files)
        set_status("analyzing_requirements")
        log("graph ran")
        return {"final_files": [dict(f) for f in CODE]}

    monkeypatch.setattr(lg, "execute", fake_execute)
    run = _seed_run("engine-lg")
    asyncio.run(gs._run_pipeline("engine-lg", "build it", None))
    assert seen["args"] == ("engine-lg", "build it", None)
    assert run["status"] == "completed"
    assert run["files"] == CODE
    assert run["logs"][-1] == "Done. Project packaged as ZIP."


def test_langgraph_failure_maps_to_failed_status(monkeypatch):
    monkeypatch.setenv("PIPELINE_ENGINE", "langgraph")

    async def fake_execute(run_id, prompt, base_files, set_status, log):
        set_status("analyzing_requirements")
        raise RuntimeError("boom")

    monkeypatch.setattr(lg, "execute", fake_execute)
    run = _seed_run("engine-lg-fail")
    asyncio.run(gs._run_pipeline("engine-lg-fail", "p"))
    assert run["status"] == "failed"
    assert run["logs"][-1] == "FAILED: boom"  # same failure contract as custom


def test_langgraph_missing_dependency_falls_back(monkeypatch):
    monkeypatch.setenv("PIPELINE_ENGINE", "langgraph")
    # Simulate langgraph not being installed: block the module import.
    monkeypatch.delattr(services, "langgraph_pipeline", raising=False)
    monkeypatch.setitem(sys.modules, "services.langgraph_pipeline", None)
    used = []

    async def fake_custom(run_id, prompt, base_files=None):
        used.append(run_id)

    monkeypatch.setattr(gs, "_run_custom_pipeline", fake_custom)
    run = _seed_run("engine-fallback")
    asyncio.run(gs._run_pipeline("engine-fallback", "p"))
    assert used == ["engine-fallback"]  # fell back to the proven custom engine
    assert any("unavailable" in l for l in run["logs"])
