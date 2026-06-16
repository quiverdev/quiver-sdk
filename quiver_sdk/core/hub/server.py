"""
QuiverCore Hub WebSocket server.
Provides a JSON-RPC-over-WebSocket interface to QuiverCore for multi-process usage.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set

if TYPE_CHECKING:
    from quiver_sdk.core.quiver_core import QuiverCore


class HubServer:
    """
    WebSocket RPC server that exposes QuiverCore methods.

    Supports start_session, send, abort, read_messages, list_sessions,
    subscribe (streaming events), and dispose.
    """

    def __init__(
        self,
        core: "QuiverCore",
        host: str = "127.0.0.1",
        port: int = 8765,
        token: Optional[str] = None,
    ) -> None:
        self._core = core
        self._host = host
        self._port = port
        self._token = token
        self._server = None
        self._active_connections: Set[Any] = set()

    async def start(self) -> None:
        """Start the WebSocket server."""
        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets package is required for Hub server. "
                "Install it with: pip install websockets"
            )

        self._server = await websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
        )

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    @property
    def address(self) -> str:
        return f"ws://{self._host}:{self._port}"

    async def _handle_connection(self, ws: Any, path: str = "") -> None:
        """Handle a single WebSocket connection."""
        self._active_connections.add(ws)
        try:
            async for raw_msg in ws:
                try:
                    msg = json.loads(raw_msg)
                    await self._dispatch(ws, msg)
                except json.JSONDecodeError as e:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": f"Parse error: {e}"},
                    }))
                except Exception as e:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": msg.get("id") if "msg" in dir() else None,
                        "error": {"code": -32603, "message": str(e)},
                    }))
        finally:
            self._active_connections.discard(ws)

    async def _dispatch(self, ws: Any, msg: Dict[str, Any]) -> None:
        """Dispatch a JSON-RPC request."""
        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        # Auth check
        if self._token:
            bearer = (params or {}).get("token") or msg.get("auth")
            if bearer != self._token:
                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32001, "message": "Unauthorized"},
                }))
                return

        try:
            result = await self._call_method(method, params, ws)
            await ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }))
        except Exception as e:
            await ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }))

    async def _call_method(
        self, method: str, params: Dict[str, Any], ws: Any
    ) -> Any:
        """Call a QuiverCore method."""
        core = self._core

        if method == "start_session":
            result = await core.start_session(params)
            return {"session_id": result.session_id, "agent_id": result.agent_id}

        elif method == "send":
            session_id = params.get("session_id", "")
            message = params.get("message", "")
            result = await core.send(session_id, message)
            return {
                "status": result.status,
                "output_text": result.output_text,
                "iterations": result.iterations,
                "usage": {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "total_cost": result.usage.total_cost,
                },
            }

        elif method == "abort":
            session_id = params.get("session_id", "")
            await core.abort(session_id)
            return {"ok": True}

        elif method == "read_messages":
            session_id = params.get("session_id", "")
            limit = params.get("limit")
            offset = params.get("offset", 0)
            msgs = await core.read_messages(session_id, limit=limit, offset=offset)
            return {
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at,
                    }
                    for m in msgs
                ]
            }

        elif method == "list_sessions":
            limit = params.get("limit", 100)
            offset = params.get("offset", 0)
            sessions = await core.list_sessions(limit=limit, offset=offset)
            return {
                "sessions": [
                    {
                        "session_id": s.session_id,
                        "status": s.status,
                        "created_at": s.created_at,
                        "updated_at": s.updated_at,
                    }
                    for s in sessions
                ]
            }

        elif method == "get_session":
            session_id = params.get("session_id", "")
            session = await core.get_session(session_id)
            if session is None:
                raise ValueError(f"Session not found: {session_id}")
            return {
                "session_id": session.session_id,
                "status": session.status,
                "created_at": session.created_at,
            }

        elif method == "delete_session":
            session_id = params.get("session_id", "")
            await core.delete_session(session_id)
            return {"ok": True}

        elif method == "subscribe":
            session_id = params.get("session_id", "")
            # Send events as JSON-RPC notifications
            async def send_event(event: Dict[str, Any]) -> None:
                try:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "method": "event",
                        "params": {"session_id": session_id, "event": event},
                    }))
                except Exception:
                    pass

            unsubscribe = core.subscribe(session_id, send_event)
            return {"ok": True, "subscription_id": str(uuid.uuid4())}

        elif method == "ping":
            return {"pong": True}

        else:
            raise ValueError(f"Unknown method: {method}")
