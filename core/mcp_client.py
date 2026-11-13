"""MCP client side: launches the server over stdio and exposes its tools to LangChain.

Uses the official `mcp` SDK (stdio_client + ClientSession) and
langchain-mcp-adapters' load_mcp_tools, which converts each MCP tool schema into
a LangChain tool that the LLM can call through bind_tools. One server
subprocess is started per incident run and closed when the run ends.
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent.parent / "mcp_server" / "k8s_mcp_server.py"


def server_params(scenario_id: str) -> StdioServerParameters:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI", "GH_", "GITHUB"))}
    env["KS_SCENARIO"] = scenario_id          # the server never receives the API key
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)


@asynccontextmanager
async def mcp_session(scenario_id: str):
    async with stdio_client(server_params(scenario_id)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
