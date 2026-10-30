r"""LangGraph engine for the generation pipeline.

Models the same agent flow as generation_service._run_custom_pipeline as a
LangGraph StateGraph (nodes call the existing agents unchanged):

    requirements -> architecture -> code -> review --(issues)--> debug -> test -> docs -> package
                                                     \---(LGTM)--------------^          |
                                                                                        v
                                                                                      END

Agents are NOT modified — each node calls the existing async agent functions.
Status strings and log lines exactly match the custom engine so the frontend
needs no changes.

Conditional edges: code -> code retries the coder on malformed JSON (up to
MAX_CODER_ATTEMPTS); review -> test skips the debugger when the reviewer says
LGTM (the custom engine always ran it).

Enabled with PIPELINE_ENGINE=langgraph (default stays "custom").
"""
from typing import Any, Callable, Dict, List, Optional

from typing_extensions import TypedDict

# Imported at module level so importing this module fails cleanly when
# langgraph is not installed - generation_service catches the ImportError and
# falls back to the custom engine.
from langgraph.graph import END, START, StateGraph

from agents.requirement_agent import requirement_agent
from agents.architect_agent import architect_agent
from agents.coder_agent import coder_agent
from agents.reviewer_agent import reviewer_agent
from agents.debugger_agent import debugger_agent
from agents.tester_agent import tester_agent
from agents.documentation_agent import documentation_agent
from agents.packager_agent import packager_agent
from providers.errors import ErrorCategory, ProviderError

# Total attempts for the coder node before the run fails (1 try + 2 retries).
MAX_CODER_ATTEMPTS = 3

# Callbacks the host (generation_service) provides so graph nodes can update
# the in-memory run store exactly like the custom pipeline does.
SetStatus = Callable[[str], None]
Log = Callable[[Any], None]


class PipelineState(TypedDict, total=False):
    prompt: str
    run_id: str
    base_files: List[Dict[str, str]]
    requirements: str
    architecture: str
    code_files: List[Dict[str, str]]
    coder_attempts: int
    review: str
    review_ok: bool
    test_files: List[Dict[str, str]]
    docs_files: List[Dict[str, str]]
    final_files: List[Dict[str, str]]
    error: Optional[str]


def _review_is_lgtm(review: str) -> bool:
    """True when the reviewer's verdict is a clean LGTM (first line only)."""
    first_line = next((ln for ln in str(review).splitlines() if ln.strip()), "")
    cleaned = "".join(ch for ch in first_line.upper() if ch.isalnum())
    return cleaned == "LGTM"


def _coder_failure_is_retryable(exc: Exception) -> bool:
    """Retry only malformed-output failures.

    Transient provider errors are already retried inside coder_agent's
    RetryPolicy; auth/quota/network problems fail fast, exactly like the
    custom engine.
    """
    return isinstance(exc, ProviderError) and exc.category == ErrorCategory.MALFORMED_RESPONSE


def build_graph(set_status: SetStatus, log: Log):
    """Compile the generation pipeline as a LangGraph StateGraph.

    set_status/log update the run store; nodes are thin wrappers around the
    existing agents so both engines stay behaviorally identical.
    """
    # Deferred import: generation_service imports this module, so the shared
    # sanitize/context/merge helpers are pulled in at call time only.
    from services.generation_service import _merge_files, _project_context, _sanitize_files

    async def requirements_node(state: PipelineState) -> Dict[str, Any]:
        set_status("analyzing_requirements")
        log("Analyzing requirements...")
        requirements = await requirement_agent(state["prompt"])
        log("Requirements extracted.")
        return {"requirements": requirements}

    async def architecture_node(state: PipelineState) -> Dict[str, Any]:
        set_status("designing_architecture")
        log("Designing architecture...")
        architecture = await architect_agent(state["prompt"], state["requirements"])
        log("Architecture designed.")
        return {"architecture": architecture}

    async def code_node(state: PipelineState) -> Dict[str, Any]:
        set_status("generating_code")
        attempts = state.get("coder_attempts", 0)
        base_files = state.get("base_files") or []

        if base_files:
            log(f"Continuing development on the existing project ({len(base_files)} files)...")
            task_title = "Apply the requested change to the existing project"
            context = _project_context(base_files)
        else:
            log("Generating code files...")
            task_title = "Generate the full project"
            context = ""

        try:
            raw_files = await coder_agent(
                user_request=state["prompt"],
                task_title=task_title,
                task_description=state["architecture"],
                context=context,
            )
        except Exception as exc:
            if attempts + 1 < MAX_CODER_ATTEMPTS and _coder_failure_is_retryable(exc):
                log(f"Coder failed ({exc}); retrying (attempt {attempts + 2}/{MAX_CODER_ATTEMPTS})...")
                return {"coder_attempts": attempts + 1}
            raise

        code_files = _sanitize_files(raw_files)
        if not code_files:
            if attempts + 1 < MAX_CODER_ATTEMPTS:
                log(f"Coder returned no usable files; retrying (attempt {attempts + 2}/{MAX_CODER_ATTEMPTS})...")
                return {"coder_attempts": attempts + 1}
            raise RuntimeError("Code generation returned no usable files.")

        if base_files:
            code_files = _merge_files(base_files, code_files)
            log(f"Project updated — now {len(code_files)} files.")
        else:
            log(f"Generated {len(code_files)} code files.")
        return {"code_files": code_files}

    async def review_node(state: PipelineState) -> Dict[str, Any]:
        set_status("reviewing")
        log("Reviewing code...")
        review = await reviewer_agent(state["code_files"])
        log(f"Review: {str(review)[:200]}")
        review_ok = _review_is_lgtm(review)
        if review_ok:
            log("Reviewer says LGTM — skipping the debugger.")
        return {"review": review, "review_ok": review_ok}

    async def debug_node(state: PipelineState) -> Dict[str, Any]:
        set_status("debugging")
        log("Applying fixes if needed...")
        code_files = state["code_files"]
        fixed = _sanitize_files(await debugger_agent(code_files, state["review"]))
        if fixed:
            code_files = fixed
        return {"code_files": code_files}

    async def test_node(state: PipelineState) -> Dict[str, Any]:
        set_status("testing")
        log("Generating tests...")
        test_files = _sanitize_files(await tester_agent(state["code_files"]))
        log(f"Generated {len(test_files)} test files.")
        return {"test_files": test_files}

    async def docs_node(state: PipelineState) -> Dict[str, Any]:
        set_status("documenting")
        log("Writing documentation...")
        docs_files = _sanitize_files(
            await documentation_agent(state["code_files"], state["requirements"])
        )
        log(f"Generated {len(docs_files)} documentation files.")
        return {"docs_files": docs_files}

    async def package_node(state: PipelineState) -> Dict[str, Any]:
        await packager_agent({
            "run_id": state["run_id"],
            "code_files": state["code_files"],
            "tests_files": state["test_files"],
            "docs_files": state["docs_files"],
        })
        final_files = state["code_files"] + state["test_files"] + state["docs_files"]
        return {"final_files": final_files}

    def route_after_code(state: PipelineState) -> str:
        # No code_files means the attempt failed and was logged - loop back
        # into the coder node until files arrive or attempts run out (the
        # node raises on the final attempt).
        return "review" if state.get("code_files") else "code"

    def route_after_review(state: PipelineState) -> str:
        # Reviewer said LGTM -> skip the debugger node entirely.
        return "test" if state.get("review_ok") else "debug"

    graph = StateGraph(PipelineState)
    graph.add_node("requirements", requirements_node)
    graph.add_node("architecture", architecture_node)
    graph.add_node("code", code_node)
    graph.add_node("review", review_node)
    graph.add_node("debug", debug_node)
    graph.add_node("test", test_node)
    graph.add_node("docs", docs_node)
    graph.add_node("package", package_node)

    graph.add_edge(START, "requirements")
    graph.add_edge("requirements", "architecture")
    graph.add_edge("architecture", "code")
    graph.add_conditional_edges("code", route_after_code, {"review": "review", "code": "code"})
    graph.add_conditional_edges("review", route_after_review, {"test": "test", "debug": "debug"})
    graph.add_edge("debug", "test")
    graph.add_edge("test", "docs")
    graph.add_edge("docs", "package")
    graph.add_edge("package", END)

    return graph.compile()


async def execute(
    run_id: str,
    prompt: str,
    base_files: Optional[List[Dict[str, str]]],
    set_status: SetStatus,
    log: Log,
) -> Dict[str, Any]:
    """Run the LangGraph pipeline. Returns the final state.

    Raises on agent failure — the caller (generation_service) turns that into
    the same failed status + FAILED log line the frontend already handles.
    """
    graph = build_graph(set_status, log)
    final = await graph.ainvoke({
        "prompt": prompt,
        "run_id": run_id,
        "base_files": base_files or [],
    })
    return final
