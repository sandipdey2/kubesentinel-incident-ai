"""Prove the MCP server works over real stdio: initialize, tools/list, tools/call.

    python scripts/verify_mcp.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.mcp_client import mcp_session  # noqa: E402


async def main():
    async with mcp_session("dns-resolution") as s:
        tools = await s.list_tools()
        print("tools/list ->", [t.name for t in tools.tools])
        for name, args in [("get_cluster_overview", {}), ("get_pod_logs", {"tail": 3}), ("anomaly_score", {}),
                           ("search_runbooks", {"query": "coredns nslookup can't resolve", "k": 2}), ("calculate_error_budget", {}),
                           ("classify_log_lines", {})]:
            res = await s.call_tool(name, args)
            text = res.content[0].text
            print(f"tools/call {name}({json.dumps(args)}) isError={res.isError} ->", text[:300].replace("\n", " "))


asyncio.run(main())
