"""One entry point used by the Streamlit app, the smoke test and the evaluation notebook."""
from __future__ import annotations

import asyncio
import threading
import time

import httpx

from langchain_mcp_adapters.tools import load_mcp_tools

from .agents import build_graph
from .config import get_llm
from .guardrails import check_input
from .mcp_client import mcp_session


async def arun_incident(query: str, scenario_id: str, llm=None) -> dict:
    t0 = time.perf_counter()
    gate = check_input(query)
    # only the redacted query is kept, so secrets typed by the user never reach the trace export
    base = {"query": gate["query"], "scenario_id": scenario_id, "input_guardrail": gate}
    if not gate["allowed"]:
        return {**base, "status": "blocked", "trace": [{"agent": "input_guardrail", "type": "guardrail", **gate}],
                "latency_s": round(time.perf_counter() - t0, 2), "mcp_tools_listed": 0, "tool_calls": 0}
    if llm is None:
        # A fresh HTTP client owned by *this* event loop, closed when the run ends (see core.config.get_llm).
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as http_client:
            return await _run_graph(base, gate, scenario_id, get_llm(http_async_client=http_client), t0)
    return await _run_graph(base, gate, scenario_id, llm, t0)


async def _run_graph(base: dict, gate: dict, scenario_id: str, llm, t0: float) -> dict:
    async with mcp_session(scenario_id) as session:
        listed = await session.list_tools()
        tools = await load_mcp_tools(session)
        graph = build_graph(llm, tools)
        init = {"query": gate["query"], "scenario_id": scenario_id, "turns": 0, "visits": {}, "revisions": 0,
                "pending_review": False, "evidence": [], "trace": [{"agent": "input_guardrail", "type": "guardrail", **gate}],
                "route": []}
        state = await graph.ainvoke(init, config={"recursion_limit": 60})
    tool_calls = sum(1 for t in state["trace"] if t["type"] == "mcp_tool_call")
    return {**base, **state, "status": "completed", "mcp_tools_listed": len(listed.tools),
            "mcp_tool_names": [t.name for t in listed.tools], "tool_calls": tool_calls,
            "latency_s": round(time.perf_counter() - t0, 2)}


# One long-lived event loop on a daemon thread. Every synchronous call (Streamlit reruns, scripts) submits
# to the same loop instead of creating and closing a loop per call with asyncio.run().
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _background_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread
    with _lock:
        if _loop is None or _loop.is_closed() or _thread is None or not _thread.is_alive():
            _loop = asyncio.new_event_loop()
            _thread = threading.Thread(target=_loop.run_forever, name="kubesentinel-asyncio", daemon=True)
            _thread.start()
        return _loop


def run_incident(query: str, scenario_id: str, llm=None, timeout: float = 900) -> dict:
    """Synchronous wrapper used by the Streamlit app and the scripts.

    The coroutine runs on one persistent background event loop, so repeated runs and Streamlit reruns never
    touch a loop that has already been closed.
    """
    future = asyncio.run_coroutine_threadsafe(arun_incident(query, scenario_id, llm), _background_loop())
    return future.result(timeout=timeout)
