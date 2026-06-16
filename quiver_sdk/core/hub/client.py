"""
QuiverCore Hub WebSocket client.
Mirrors the Hub client from @quiver/core.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional


class HubClient:
    """
    Client for communicating with a QuiverCore Hub server over WebSocket.

    Example::

        client = HubClient("ws://127.0.0.1:8765")
        await client.connect()
        session = await client.start_session({
            "provider_id": "anthropic",
            "model_id": "claude-sonnet-4-6",
        })
        result = await client.send(session["session_id"], "Hello!")
    """

    def __init__(
        self,
        url: str = "ws://127.0.0.1:8765",
        token: Optional[str] = None,
        reconnect: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        self._url = url
        self._token = token
        self._reconnect = reconnect
        self._timeout_ms = timeout_ms
        self._ws = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._event_listeners: Dict[str, List[Callable]] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Connect to the hub server."""
        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets package is required for Hub client. "
                "Install it with: pip install websockets"
            )

        self._ws = await websockets.connect(self._url)
        self._connected = True
        self._reader_task = asyncio.ensure_future(self._read_loop())

    async def disconnect(self) -> None:
        """Disconnect from the hub server."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        self._connected = False

    async def _call(self, method: str, params: Dict[str, Any]) -> Any:
        """Send a JSON-RPC request and await the response."""
        if not self._connected or not self._ws:
            raise RuntimeError("Not connected to hub server")

        req_id = str(uuid.uuid4())
        if self._token:
            params = {**params, "token": self._token}

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut

        await self._ws.send(json.dumps(request))

        try:
            return await asyncio.wait_for(fut, timeout=self._timeout_ms / 1000)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"Hub call '{method}' timed out after {self._timeout_ms}ms")

    async def _read_loop(self) -> None:
        """Read messages from the WebSocket."""
        if not self._ws:
            return
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # Response to a request
                req_id = str(msg.get("id", ""))
                if req_id and req_id in self._pending:
                    fut = self._pending.pop(req_id)
                    if "error" in msg:
                        fut.set_exception(RuntimeError(msg["error"].get("message", "Hub error")))
                    else:
                        fut.set_result(msg.get("result"))
                    continue

                # Notification / event
                method = msg.get("method")
                if method == "event":
                    params = msg.get("params", {})
                    session_id = params.get("session_id", "")
                    event = params.get("event", {})
                    for listener in list(self._event_listeners.get(session_id, [])):
                        try:
                            result = listener(event)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            pass

        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            self._connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("Connection closed"))
            self._pending.clear()

    # ---- Public API ----

    async def start_session(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Start a new session."""
        return await self._call("start_session", config)

    async def send(self, session_id: str, message: str) -> Dict[str, Any]:
        """Send a message to a session."""
        return await self._call("send", {"session_id": session_id, "message": message})

    async def abort(self, session_id: str) -> None:
        """Abort a running session."""
        await self._call("abort", {"session_id": session_id})

    async def read_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Read messages from a session."""
        params = {"session_id": session_id, "offset": offset}
        if limit is not None:
            params["limit"] = limit
        result = await self._call("read_messages", params)
        return result.get("messages", [])

    async def list_sessions(
        self, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List all sessions."""
        result = await self._call("list_sessions", {"limit": limit, "offset": offset})
        return result.get("sessions", [])

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get a session by ID."""
        return await self._call("get_session", {"session_id": session_id})

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        await self._call("delete_session", {"session_id": session_id})

    def subscribe(self, session_id: str, listener: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        """Subscribe to events for a session."""
        if session_id not in self._event_listeners:
            self._event_listeners[session_id] = []
        self._event_listeners[session_id].append(listener)

        def unsubscribe():
            listeners = self._event_listeners.get(session_id, [])
            if listener in listeners:
                listeners.remove(listener)

        return unsubscribe

    async def ping(self) -> bool:
        """Check if the server is alive."""
        try:
            result = await self._call("ping", {})
            return result.get("pong", False)
        except Exception:
            return False
