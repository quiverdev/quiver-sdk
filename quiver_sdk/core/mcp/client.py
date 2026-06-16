"""
MCP (Model Context Protocol) client implementation.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from typing import Any, Dict, List, Optional

from quiver_sdk.exceptions import McpError
from quiver_sdk.types import McpServer, McpTool


class McpClient:
    """
    Client for communicating with an MCP server over stdio or SSE.
    """

    def __init__(self, server: McpServer) -> None:
        self._server = server
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._sse_url: Optional[str] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._tools: List[McpTool] = []
        self._connected = False

    @property
    def server_name(self) -> str:
        return self._server.name

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> List[McpTool]:
        return list(self._tools)

    async def connect(self) -> None:
        """Connect to the MCP server."""
        transport = self._server.transport

        if transport == "stdio":
            await self._connect_stdio()
        elif transport in ("sse", "http"):
            await self._connect_sse()
        else:
            raise McpError(f"Unsupported MCP transport: {transport}")

        await self._initialize()
        self._connected = True

    async def _connect_stdio(self) -> None:
        command = self._server.command
        if not command:
            raise McpError(f"MCP server '{self._server.name}' requires a command for stdio transport")

        args = self._server.args or []
        env = {**os.environ, **(self._server.env or {})}

        self._proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.ensure_future(self._read_loop_stdio())

    async def _connect_sse(self) -> None:
        self._sse_url = self._server.url
        if not self._sse_url:
            raise McpError(f"MCP server '{self._server.name}' requires a URL for SSE transport")

    async def _initialize(self) -> None:
        """Send the MCP initialize handshake."""
        try:
            response = await asyncio.wait_for(
                self._send_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "quiver-sdk", "version": "1.0.0"},
                }),
                timeout=10.0,
            )
            # Discover tools
            await self.list_tools()
        except asyncio.TimeoutError:
            raise McpError(f"MCP server '{self._server.name}' initialization timed out")
        except Exception as e:
            raise McpError(f"MCP initialization failed: {e}")

    async def list_tools(self) -> List[McpTool]:
        """Fetch the list of tools from the server."""
        try:
            response = await asyncio.wait_for(
                self._send_request("tools/list", {}),
                timeout=10.0,
            )
            tools_data = response.get("tools", [])
            self._tools = [
                McpTool(
                    name=t.get("name", ""),
                    description=t.get("description"),
                    input_schema=t.get("inputSchema") or t.get("input_schema"),
                    server_name=self._server.name,
                )
                for t in tools_data
            ]
            return self._tools
        except Exception as e:
            raise McpError(f"Failed to list tools from '{self._server.name}': {e}")

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the MCP server."""
        try:
            response = await asyncio.wait_for(
                self._send_request("tools/call", {
                    "name": name,
                    "arguments": arguments,
                }),
                timeout=60.0,
            )
            return response.get("content") or response
        except asyncio.TimeoutError:
            raise McpError(f"Tool call '{name}' timed out")
        except Exception as e:
            raise McpError(f"Tool call '{name}' failed: {e}")

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        req_id = str(uuid.uuid4())
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut

        if self._proc:
            line = json.dumps(request) + "\n"
            self._proc.stdin.write(line.encode())
            await self._proc.stdin.drain()
        elif self._sse_url:
            return await self._http_request(method, params)
        else:
            raise McpError("Not connected")

        return await fut

    async def _http_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send an HTTP JSON-RPC request."""
        try:
            import aiohttp
        except ImportError:
            import urllib.request
            # Fallback
            req_data = json.dumps({
                "jsonrpc": "2.0",
                "id": "1",
                "method": method,
                "params": params,
            }).encode()
            req = urllib.request.Request(
                self._sse_url,
                data=req_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data.get("result", {})

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._sse_url,
                json={
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": method,
                    "params": params,
                },
            ) as resp:
                data = await resp.json()
                if "error" in data:
                    raise McpError(f"MCP error: {data['error']}")
                return data.get("result", {})

    async def _read_loop_stdio(self) -> None:
        """Read JSON-RPC responses from stdio."""
        if not self._proc or not self._proc.stdout:
            return

        buffer = b""
        while True:
            try:
                chunk = await self._proc.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        req_id = str(msg.get("id", ""))
                        if req_id in self._pending:
                            fut = self._pending.pop(req_id)
                            if "error" in msg:
                                fut.set_exception(McpError(str(msg["error"])))
                            elif "result" in msg:
                                fut.set_result(msg["result"])
                            else:
                                fut.set_result(msg)
                    except json.JSONDecodeError:
                        pass
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._connected = False
        # Reject any pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(McpError("Connection closed"))
        self._pending.clear()
