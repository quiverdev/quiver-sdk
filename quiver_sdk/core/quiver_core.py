"""
QuiverCore — session-managed, persistent agent engine.

Mirrors the QuiverCore class from @quiver/core:
  create(), start(), send(), abort(), stop(), dispose(),
  get(), list(), delete(), update(), readMessages(), restore()
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from quiver_sdk.agent import AgentRuntime
from quiver_sdk.core.storage.sqlite_store import SqliteStore
from quiver_sdk.core.tools.definitions import DefaultToolsConfig, create_default_tools
from quiver_sdk.exceptions import SessionNotFoundError
from quiver_sdk.llms.gateway import DefaultGateway, GatewayModelAdapter, create_gateway
from quiver_sdk.types import (
    AgentMessage,
    AgentRunResult,
    AgentTool,
    GatewayProviderConfig,
    HubOptions,
    McpServer,
    SessionConfig,
    SessionRecord,
    StartSessionResult,
)
from quiver_sdk.utils import create_uid


@dataclass
class CoreSession:
    """Runtime session state."""

    session_id: str
    agent: AgentRuntime
    config: SessionConfig
    unsubscribe: Optional[Callable[[], None]] = None


@dataclass
class QuiverCoreConfig:
    """Configuration for QuiverCore."""

    # Storage
    db_path: str = ":memory:"
    # Default provider settings
    provider_id: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    # Default session settings
    system_prompt: Optional[str] = None
    cwd: Optional[str] = None
    enable_tools: bool = True
    max_iterations: Optional[int] = None
    # Hub settings
    hub: Optional[HubOptions] = None
    # MCP servers
    mcp_servers: Optional[List[McpServer]] = None
    # Extra tools
    extra_tools: Optional[List[AgentTool]] = None
    # Gateway config
    gateway_provider_configs: Optional[List[GatewayProviderConfig]] = None
    # Logger
    logger: Optional[Any] = None
    telemetry: Optional[Any] = None


class QuiverCore:
    """
    Session-managed, persistent agent engine.

    Manages multiple concurrent agent sessions backed by SQLite.
    Each session is an independent agent conversation.

    Usage::

        core = QuiverCore.create(
            provider_id="anthropic",
            model_id="claude-sonnet-4-6",
            api_key="sk-ant-...",
            system_prompt="You are a helpful assistant.",
        )
        session = await core.start({
            "provider_id": "anthropic",
            "model_id": "claude-sonnet-4-6",
        })
        result = await core.send(session.session_id, "Hello!")
        print(result.output_text)

    Hub mode::

        core = QuiverCore.create(...)
        await core.start_hub(port=8765)
    """

    def __init__(self, config: QuiverCoreConfig) -> None:
        self._config = config
        self._store = SqliteStore(config.db_path)
        self._sessions: Dict[str, CoreSession] = {}
        self._global_event_listeners: Dict[str, List[Callable]] = {}

        # Build gateway
        self._gateway = create_gateway(
            provider_configs=config.gateway_provider_configs or [],
        )
        if config.api_key and config.provider_id:
            self._gateway.configure_provider(GatewayProviderConfig(
                provider_id=config.provider_id,
                api_key=config.api_key,
                base_url=config.base_url,
                headers=config.headers,
            ))

        # MCP manager (lazy init on first use)
        self._mcp_manager = None
        if config.mcp_servers:
            from quiver_sdk.core.mcp.manager import McpManager
            self._mcp_manager = McpManager(config.mcp_servers)

        self._hub_server = None
        self._hub_started = False

    # -------------------------------------------------------------------------
    # Factory
    # -------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        system_prompt: Optional[str] = None,
        cwd: Optional[str] = None,
        enable_tools: bool = True,
        max_iterations: Optional[int] = None,
        db_path: str = ":memory:",
        mcp_servers: Optional[List[McpServer]] = None,
        extra_tools: Optional[List[AgentTool]] = None,
        gateway_provider_configs: Optional[List[GatewayProviderConfig]] = None,
        hub: Optional[HubOptions] = None,
        logger: Optional[Any] = None,
        telemetry: Optional[Any] = None,
    ) -> "QuiverCore":
        """
        Create a new QuiverCore instance.

        Example::

            core = QuiverCore.create(
                provider_id="anthropic",
                model_id="claude-sonnet-4-6",
                api_key="sk-ant-...",
                system_prompt="You are a helpful coding assistant.",
                enable_tools=True,
                db_path="/tmp/quiver.db",
            )
        """
        cfg = QuiverCoreConfig(
            db_path=db_path,
            provider_id=provider_id,
            model_id=model_id,
            api_key=api_key,
            base_url=base_url,
            headers=headers,
            system_prompt=system_prompt,
            cwd=cwd,
            enable_tools=enable_tools,
            max_iterations=max_iterations,
            hub=hub,
            mcp_servers=mcp_servers,
            extra_tools=extra_tools,
            gateway_provider_configs=gateway_provider_configs,
            logger=logger,
            telemetry=telemetry,
        )
        return cls(cfg)

    # -------------------------------------------------------------------------
    # Session lifecycle
    # -------------------------------------------------------------------------

    async def start(self, config: Optional[Dict[str, Any]] = None) -> StartSessionResult:
        """
        Create and start a new session.

        Args:
            config: Optional per-session overrides (provider_id, model_id, api_key,
                    system_prompt, cwd, max_iterations, tools, etc.)

        Returns:
            StartSessionResult with session_id and agent_id
        """
        cfg = config or {}

        # Build SessionConfig from core defaults + overrides
        session_config = SessionConfig(
            provider_id=cfg.get("provider_id") or self._config.provider_id or "",
            model_id=cfg.get("model_id") or self._config.model_id,
            api_key=cfg.get("api_key") or self._config.api_key,
            base_url=cfg.get("base_url") or self._config.base_url,
            system_prompt=cfg.get("system_prompt") or self._config.system_prompt,
            cwd=cfg.get("cwd") or self._config.cwd or os.getcwd(),
            enable_tools=cfg.get("enable_tools", self._config.enable_tools),
            max_iterations=cfg.get("max_iterations") or self._config.max_iterations,
            tools=cfg.get("tools"),
            headers=cfg.get("headers") or self._config.headers,
            options=cfg.get("options"),
        )

        session_id = create_uid("sess")
        agent_id = create_uid("agent")

        # Build tools
        tools = self._build_tools(session_config)

        # Build model
        model = self._build_model(session_config)

        # Build agent
        def make_on_event(sid: str) -> Callable:
            async def on_event(event: Dict[str, Any]) -> None:
                await self._dispatch_event(sid, event)
            return on_event

        agent = AgentRuntime(
            model=model,
            system_prompt=session_config.system_prompt,
            tools=tools,
            max_iterations=session_config.max_iterations,
            agent_id=agent_id,
            session_id=session_id,
            on_event=make_on_event(session_id),
        )

        # Persist session
        self._store.create_session(
            session_id=session_id,
            config=json.loads(json.dumps({
                "provider_id": session_config.provider_id,
                "model_id": session_config.model_id,
                "system_prompt": session_config.system_prompt,
                "cwd": session_config.cwd,
            }, default=str)),
            metadata={"agent_id": agent_id},
        )

        self._sessions[session_id] = CoreSession(
            session_id=session_id,
            agent=agent,
            config=session_config,
        )

        return StartSessionResult(session_id=session_id, agent_id=agent_id)

    # Alias matching TypeScript API
    async def create_session(
        self, config: Optional[Dict[str, Any]] = None
    ) -> StartSessionResult:
        return await self.start(config)

    async def start_session(
        self, config: Optional[Dict[str, Any]] = None
    ) -> StartSessionResult:
        return await self.start(config)

    async def send(self, session_id: str, message: str) -> AgentRunResult:
        """
        Send a message to a session and wait for the result.

        Args:
            session_id: Session to send to
            message: User message text

        Returns:
            AgentRunResult
        """
        session = self._get_session_or_raise(session_id)

        # Run the agent
        result = await session.agent.run(message)

        # Persist messages
        for msg in result.messages:
            try:
                self._store.append_message(session_id, msg)
            except Exception:
                pass

        # Update session status
        self._store.update_session(session_id, status=result.status)

        return result

    async def continue_session(
        self, session_id: str, message: Optional[str] = None
    ) -> AgentRunResult:
        """Continue a session, optionally with a new user message."""
        session = self._get_session_or_raise(session_id)
        result = await session.agent.continue_(message)

        for msg in result.messages:
            try:
                self._store.append_message(session_id, msg)
            except Exception:
                pass

        self._store.update_session(session_id, status=result.status)
        return result

    async def abort(self, session_id: str) -> None:
        """Abort a running session."""
        session = self._sessions.get(session_id)
        if session:
            session.agent.abort("Session aborted by user")
        self._store.update_session(session_id, status="aborted")

    async def stop(self, session_id: str) -> None:
        """Alias for abort."""
        await self.abort(session_id)

    async def restore(
        self, session_id: str, messages: Optional[List[AgentMessage]] = None
    ) -> None:
        """Restore a session from its persisted messages (or provided messages)."""
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session '{session_id}' not found in memory")

        msgs = messages or self._store.get_messages(session_id)
        session.agent.restore(msgs)
        self._store.update_session(session_id, status="idle")

    async def dispose(self) -> None:
        """Dispose of all sessions and resources."""
        for session in list(self._sessions.values()):
            session.agent.abort("QuiverCore disposed")
        self._sessions.clear()

        if self._hub_server:
            await self._hub_server.stop()

        if self._mcp_manager:
            await self._mcp_manager.disconnect_all()

        self._store.close()

    # -------------------------------------------------------------------------
    # Session queries
    # -------------------------------------------------------------------------

    async def get(self, session_id: str) -> Optional[SessionRecord]:
        """Get a session record by ID."""
        return self._store.get_session(session_id)

    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        return await self.get(session_id)

    async def list(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> List[SessionRecord]:
        """List session records."""
        return self._store.list_sessions(limit=limit, offset=offset, status=status)

    async def list_sessions(
        self, limit: int = 100, offset: int = 0
    ) -> List[SessionRecord]:
        return await self.list(limit=limit, offset=offset)

    async def delete(self, session_id: str) -> None:
        """Delete a session and all its messages."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.agent.abort("Session deleted")
        self._store.delete_session(session_id)

    async def delete_session(self, session_id: str) -> None:
        return await self.delete(session_id)

    async def update(
        self,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> None:
        """Update session metadata."""
        self._store.update_session(
            session_id=session_id,
            status=status,
            metadata=metadata,
        )

    async def read_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
        after_id: Optional[str] = None,
    ) -> List[AgentMessage]:
        """Read messages from a session."""
        return self._store.get_messages(
            session_id=session_id,
            limit=limit,
            offset=offset,
            after_id=after_id,
        )

    async def get_accumulated_usage(self, session_id: str) -> Any:
        """Return the accumulated token usage for a session from its in-memory agent."""
        from quiver_sdk.types import AgentUsage
        session = self._sessions.get(session_id)
        if session:
            return session.agent.snapshot().usage
        return AgentUsage()

    def get_agent(self, session_id: str) -> Optional[AgentRuntime]:
        """Get the AgentRuntime for a session (for advanced use)."""
        session = self._sessions.get(session_id)
        return session.agent if session else None

    # -------------------------------------------------------------------------
    # Events
    # -------------------------------------------------------------------------

    def subscribe(
        self,
        session_id: str,
        listener: Callable[[Dict[str, Any]], None],
    ) -> Callable[[], None]:
        """
        Subscribe to events for a specific session.

        Returns an unsubscribe function.
        """
        if session_id not in self._global_event_listeners:
            self._global_event_listeners[session_id] = []
        self._global_event_listeners[session_id].append(listener)

        # Also subscribe directly on the agent if it exists
        session = self._sessions.get(session_id)
        if session:
            unsub_agent = session.agent.subscribe(listener)
        else:
            unsub_agent = None

        def unsubscribe():
            listeners = self._global_event_listeners.get(session_id, [])
            if listener in listeners:
                listeners.remove(listener)
            if unsub_agent:
                unsub_agent()

        return unsubscribe

    async def _dispatch_event(
        self, session_id: str, event: Dict[str, Any]
    ) -> None:
        """Dispatch an event to all listeners for a session."""
        for listener in list(self._global_event_listeners.get(session_id, [])):
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Hub mode
    # -------------------------------------------------------------------------

    async def start_hub(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: Optional[str] = None,
    ) -> str:
        """
        Start the WebSocket hub server.

        Returns the server address (ws://host:port).
        """
        from quiver_sdk.core.hub.server import HubServer

        self._hub_server = HubServer(self, host=host, port=port, token=token)
        await self._hub_server.start()
        self._hub_started = True
        return self._hub_server.address

    async def stop_hub(self) -> None:
        """Stop the hub server."""
        if self._hub_server:
            await self._hub_server.stop()
            self._hub_server = None
            self._hub_started = False

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _get_session_or_raise(self, session_id: str) -> CoreSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(
                f"Session '{session_id}' not found. "
                "Create one with await core.start()."
            )
        return session

    def _build_model(self, config: SessionConfig) -> GatewayModelAdapter:
        provider_id = config.provider_id or self._config.provider_id or ""
        if not provider_id:
            raise ValueError(
                "provider_id is required. "
                "Pass it to start() or set it in QuiverCore.create()."
            )

        # Apply per-session API key if different from global
        if config.api_key and config.api_key != self._config.api_key:
            self._gateway.configure_provider(GatewayProviderConfig(
                provider_id=provider_id,
                api_key=config.api_key,
                base_url=config.base_url,
                headers=config.headers,
            ))

        return self._gateway.create_agent_model(
            provider_id=provider_id,
            model_id=config.model_id,
            options=config.options,
        )

    def _build_tools(self, config: SessionConfig) -> List[AgentTool]:
        tools: List[AgentTool] = []

        if config.enable_tools:
            default_tools_cfg = DefaultToolsConfig(
                cwd=config.cwd or os.getcwd(),
            )
            tools.extend(create_default_tools(default_tools_cfg))

        # Session-specific tools
        if config.tools:
            tools.extend(config.tools)

        # Global extra tools
        if self._config.extra_tools:
            tools.extend(self._config.extra_tools)

        # MCP tools
        if self._mcp_manager and self._mcp_manager._connected:
            tools.extend(self._mcp_manager.get_agent_tools())

        return tools

    # -------------------------------------------------------------------------
    # Context manager support
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "QuiverCore":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.dispose()
