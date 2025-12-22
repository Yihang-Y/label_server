import asyncio
from dataclasses import dataclass
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import MCP_TIMEOUT

@dataclass
class ToolSession:
    session: ClientSession
    exit_stack: AsyncExitStack

    async def close(self):
        await self.exit_stack.aclose()

async def connect_mcp_copilot() -> ToolSession:
    exit_stack = AsyncExitStack()
    server_params = StdioServerParameters(
        command="python3",
        args=["-m", "mcp_copilot"],
        env=None,
    )

    stdio, write = await exit_stack.enter_async_context(stdio_client(server_params))
    session = await exit_stack.enter_async_context(ClientSession(stdio, write))
    await asyncio.wait_for(session.initialize(), timeout=MCP_TIMEOUT)
    return ToolSession(session=session, exit_stack=exit_stack)

async def fetch_mcp_tools(ts: ToolSession):
    tools = await ts.session.list_tools()
    available_tools = []
    for tool in tools.tools:
        available_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            }
        })
    return available_tools
