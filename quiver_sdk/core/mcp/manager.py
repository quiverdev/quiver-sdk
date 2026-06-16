"""
MCP server manager for QuiverCore.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from quiver_sdk.core.mcp.client import McpClient
from quiver_sdk.exceptions import McpError
from quiver_sdk.tools import create_tool
from quiver_sdk.types import AgentTool, AgentToolContext, McpServer, McpTool


class McpManager:
    """
    Manages multiple MCP server connections and exposes their tools
    as AgentTool instances.
    """

    def __init__(self, servers: Optional[List[McpServer]] = None) -> None:
        self._servers = servers or []
        self._clients: Dict[str, McpClient] = {}
        self._connected = False

    def add_server(self, server: McpServer) -> None:
        """Add an MCP server configuration."""
        self._servers.append(server)

    async def connect_all(self) -> None:
        """Connect to all configured servers."""
        tasks = []
        for server in self._servers:
            if server.name not in self._clients:
                client = McpClient(server)
                self._clients[server.name] = client
                tasks.append(self._connect_server(client, server.name))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._connected = True

    async def _connect_server(self, client: McpClient, name: str) -> None:
        try:
            await client.connect()
        except Exception as e:
            # Don't fail all servers if one fails
            del self._clients[name]

    async def connect_server(self, server: McpServer) -> McpClient:
        """Connect to a single MCP server."""
        client = McpClient(server)
        await client.connect()
        self._clients[server.name] = client
        return client

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""
        tasks = [c.disconnect() for c in self._clients.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        self._clients.clear()

    def get_client(self, server_name: str) -> Optional[McpClient]:
        """Get a client by server name."""
        return self._clients.get(server_name)

    def list_servers(self) -> List[str]:
        """List all connected server names."""
        return list(self._clients.keys())

    def list_tools(self) -> List[McpTool]:
        """List all tools from all connected servers."""
        tools = []
        for client in self._clients.values():
            tools.extend(client.tools)
        return tools

    def get_agent_tools(self) -> List[AgentTool]:
        """Create AgentTool instances for all MCP tools."""
        agent_tools = []
        for server_name, client in self._clients.items():
            for mcp_tool in client.tools:
                agent_tools.append(self._mcp_tool_to_agent_tool(client, mcp_tool))
        return agent_tools

    def _mcp_tool_to_agent_tool(self, client: McpClient, mcp_tool: McpTool) -> AgentTool:
        """Convert an MCP tool to an AgentTool."""
        tool_name = f"mcp_{mcp_tool.server_name}_{mcp_tool.name}"
        # Sanitize name for LLM
        tool_name = tool_name.replace("-", "_").replace(".", "_")

        input_schema = mcp_tool.input_schema or {
            "type": "object",
            "properties": {},
        }

        async def execute(input_data: Any, context: AgentToolContext) -> Any:
            try:
                result = await client.call_tool(mcp_tool.name, input_data or {})
                if isinstance(result, list):
                    parts = []
                    for item in result:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                parts.append(item.get("text", ""))
                            else:
                                import json
                                parts.append(json.dumps(item))
                        else:
                            parts.append(str(item))
                    return "\n".join(parts)
                return result
            except Exception as e:
                return f"[MCP tool error] {e}"

        return create_tool(
            name=tool_name,
            description=f"[{mcp_tool.server_name}] {mcp_tool.description or mcp_tool.name}",
            input_schema=input_schema,
            execute=execute,
            timeout_ms=60_000,
            retryable=False,
        )
