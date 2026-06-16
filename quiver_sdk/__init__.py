"""
src — The Quiver Agent SDK for Python

A faithful Python port of the Quiver TypeScript monorepo (@quiver/sdk, @quiver/core,
@quiver/agents, @quiver/llms, @quiver/shared).

Quickstart::

    import asyncio
    from quiver_sdk import Agent, create_tool

    async def main():
        agent = Agent(
            provider_id="anthropic",
            model_id="claude-sonnet-4-6",
            api_key="sk-ant-...",
            system_prompt="You are a helpful assistant.",
        )
        result = await agent.run("What is 2 + 2?")
        print(result.output_text)

    asyncio.run(main())

QuiverCore (session-managed, persistent)::

    from quiver_sdk import QuiverCore

    async def main():
        core = QuiverCore.create(
            provider_id="anthropic",
            api_key="sk-ant-...",
            enable_tools=True,
        )
        session = await core.start()
        result = await core.send(session.session_id, "List the files here.")
        print(result.output_text)

    asyncio.run(main())
"""

from __future__ import annotations

# ---- Agent / Runtime ----
from quiver_sdk.agent import (
    Agent,
    AgentRuntime,
    create_agent,
    create_agent_runtime,
)

# ---- Tool creation ----
from quiver_sdk.tools import create_tool

# ---- Core types ----
from quiver_sdk.types import (
    AgentMessage,
    AgentMessagePart,
    AgentModelEvent,
    AgentModelFinishReason,
    AgentModelRequest,
    AgentRunResult,
    AgentRuntimeEvent,
    AgentRuntimePlugin,
    AgentRuntimePluginContext,
    AgentRuntimePluginSetup,
    AgentRuntimeStateSnapshot,
    AgentStopControl,
    AgentTool,
    AgentToolContext,
    AgentToolDefinition,
    AgentToolResult,
    AgentUsage,
    CronSpec,
    GatewayModelDefinition,
    GatewayProviderConfig,
    GatewayProviderManifest,
    GatewayProviderSettings,
    GatewayStreamRequest,
    HubOptions,
    McpServer,
    McpTool,
    SessionConfig,
    SessionRecord,
    StartSessionResult,
    ToolApprovalRequest,
    ToolApprovalResult,
    ToolPolicy,
)

# ---- Exceptions ----
from quiver_sdk.exceptions import (
    AgentRuntimeAbortError,
    CommandExitError,
    GatewayError,
    McpError,
    ModelNotFoundError,
    ProviderNotFoundError,
    SessionNotFoundError,
    StorageError,
    TimeoutError,
)

# ---- LLM Gateway ----
from quiver_sdk.llms.gateway import DefaultGateway, Gateway, create_gateway
from quiver_sdk.llms.providers.registry import BUILTIN_PROVIDERS

# ---- QuiverCore ----
from quiver_sdk.core.quiver_core import QuiverCore, QuiverCoreConfig

# ---- Built-in tools ----
from quiver_sdk.core.tools.definitions import DefaultToolsConfig, create_default_tools
from quiver_sdk.core.tools.bash import BashExecutorOptions, create_bash_executor
from quiver_sdk.core.tools.editor import EditorExecutorOptions, create_editor_executor
from quiver_sdk.core.tools.file_read import FileReadExecutorOptions, create_file_read_executor
from quiver_sdk.core.tools.search import SearchExecutorOptions, create_search_executor
from quiver_sdk.core.tools.web_fetch import WebFetchExecutorOptions, create_web_fetch_executor
from quiver_sdk.core.tools.apply_patch import create_apply_patch_executor

# ---- Storage ----
from quiver_sdk.core.storage.sqlite_store import SqliteStore

# ---- Hub ----
from quiver_sdk.core.hub.server import HubServer
from quiver_sdk.core.hub.client import HubClient

# ---- MCP ----
from quiver_sdk.core.mcp.client import McpClient
from quiver_sdk.core.mcp.manager import McpManager

# ---- Utilities ----
from quiver_sdk.utils import create_uid

__version__ = "1.0.0"

__all__ = [
    # Agent
    "Agent",
    "AgentRuntime",
    "create_agent",
    "create_agent_runtime",
    # Tools
    "create_tool",
    # Types
    "AgentMessage",
    "AgentMessagePart",
    "AgentModelEvent",
    "AgentModelFinishReason",
    "AgentModelRequest",
    "AgentRunResult",
    "AgentRuntimeEvent",
    "AgentRuntimePlugin",
    "AgentRuntimePluginContext",
    "AgentRuntimePluginSetup",
    "AgentRuntimeStateSnapshot",
    "AgentStopControl",
    "AgentTool",
    "AgentToolContext",
    "AgentToolDefinition",
    "AgentToolResult",
    "AgentUsage",
    "CronSpec",
    "GatewayModelDefinition",
    "GatewayProviderConfig",
    "GatewayProviderManifest",
    "GatewayProviderSettings",
    "GatewayStreamRequest",
    "HubOptions",
    "McpServer",
    "McpTool",
    "SessionConfig",
    "SessionRecord",
    "StartSessionResult",
    "ToolApprovalRequest",
    "ToolApprovalResult",
    "ToolPolicy",
    # Exceptions
    "AgentRuntimeAbortError",
    "CommandExitError",
    "GatewayError",
    "McpError",
    "ModelNotFoundError",
    "ProviderNotFoundError",
    "SessionNotFoundError",
    "StorageError",
    "TimeoutError",
    # Gateway
    "DefaultGateway",
    "Gateway",
    "create_gateway",
    "BUILTIN_PROVIDERS",
    # QuiverCore
    "QuiverCore",
    "QuiverCoreConfig",
    # Built-in tools
    "DefaultToolsConfig",
    "create_default_tools",
    "BashExecutorOptions",
    "create_bash_executor",
    "EditorExecutorOptions",
    "create_editor_executor",
    "FileReadExecutorOptions",
    "create_file_read_executor",
    "SearchExecutorOptions",
    "create_search_executor",
    "WebFetchExecutorOptions",
    "create_web_fetch_executor",
    "create_apply_patch_executor",
    # Storage
    "SqliteStore",
    # Hub
    "HubServer",
    "HubClient",
    # MCP
    "McpClient",
    "McpManager",
    # Utils
    "create_uid",
    # Version
    "__version__",
]
