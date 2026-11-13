"""One entry point used by the Streamlit app, the smoke test and the evaluation notebook."""
from __future__ import annotations

import asyncio
import time

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
    llm = llm or get_llm()
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


def run_incident(query: str, scenario_id: str, llm=None) -> dict:
    """Synchronous wrapper (Streamlit scripts and scripts/ have no running event loop)."""
    return asyncio.run(arun_incident(query, scenario_id, llm))
