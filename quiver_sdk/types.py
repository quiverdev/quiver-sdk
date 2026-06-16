"""
Core type definitions for the Quiver SDK.

Mirrors the TypeScript types from @quiver/shared and @quiver/agents.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    Union,
    runtime_checkable,
)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Message parts
# ---------------------------------------------------------------------------

AgentTextPart = Dict[str, Any]  # {"type": "text", "text": str}
AgentReasoningPart = Dict[str, Any]  # {"type": "reasoning", "text": str, ...}
AgentImagePart = Dict[str, Any]  # {"type": "image", ...}
AgentFilePart = Dict[str, Any]  # {"type": "file", ...}
AgentToolCallPart = Dict[str, Any]  # {"type": "tool-call", ...}
AgentToolResultPart = Dict[str, Any]  # {"type": "tool-result", ...}

AgentMessagePart = Dict[str, Any]


@dataclass
class AgentMessage:
    """A single message in the agent conversation."""

    id: str
    role: Literal["user", "assistant", "tool"]
    content: List[AgentMessagePart]
    created_at: int  # Unix timestamp ms
    metadata: Optional[Dict[str, Any]] = None
    model_info: Optional[Dict[str, str]] = None  # {id, provider, family?}
    metrics: Optional[Dict[str, Any]] = None  # token usage per message


@dataclass
class AgentUsage:
    """Token usage tracking for agent runs."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_cost: Optional[float] = None


# ---------------------------------------------------------------------------
# Run result
# ---------------------------------------------------------------------------


@dataclass
class AgentRunResult:
    """Result returned from AgentRuntime.run() / Agent.run()."""

    agent_id: str
    run_id: str
    status: Literal["completed", "aborted", "failed"]
    iterations: int
    output_text: str
    messages: List[AgentMessage]
    usage: AgentUsage
    agent_role: Optional[str] = None
    error: Optional[Exception] = None


# ---------------------------------------------------------------------------
# Runtime state snapshot
# ---------------------------------------------------------------------------


@dataclass
class AgentRuntimeStateSnapshot:
    """Point-in-time snapshot of agent runtime state."""

    agent_id: str
    status: Literal["idle", "running", "completed", "aborted", "failed"]
    iteration: int
    messages: List[AgentMessage]
    pending_tool_calls: List[str]
    usage: AgentUsage
    agent_role: Optional[str] = None
    parent_agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None
    last_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Tool types
# ---------------------------------------------------------------------------


@dataclass
class AgentToolDefinition:
    """Schema definition for a tool (sent to the LLM)."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    lifecycle: Optional[Dict[str, Any]] = None


@dataclass
class AgentToolResult:
    """Result from executing a tool."""

    output: Any
    is_error: bool = False
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class AgentToolContext:
    """Execution context passed to tools."""

    agent_id: str
    iteration: int
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    signal: Optional[Any] = None  # asyncio.Event for cancellation
    metadata: Optional[Dict[str, Any]] = None
    snapshot: Optional[AgentRuntimeStateSnapshot] = None
    emit_update: Optional[Callable[[Any], None]] = None


@dataclass
class AgentTool:
    """A tool that the agent can call."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    execute: Callable[..., Any]
    lifecycle: Optional[Dict[str, Any]] = None
    timeout_ms: int = 30_000
    retryable: bool = True
    max_retries: int = 3


# ---------------------------------------------------------------------------
# Model types
# ---------------------------------------------------------------------------

AgentModelFinishReason = Literal["stop", "tool-calls", "max-tokens", "aborted", "error"]

# Model events (streamed from LLM)
AgentModelEvent = Dict[str, Any]
# Possible shapes:
#  {"type": "text-delta", "text": str}
#  {"type": "reasoning-delta", "text": str, ...}
#  {"type": "tool-call-delta", ...}
#  {"type": "usage", "usage": {...}}
#  {"type": "finish", "reason": str, "error"?: str}


@dataclass
class AgentModelRequest:
    """Request sent to the LLM model."""

    messages: List[AgentMessage]
    tools: List[AgentToolDefinition]
    system_prompt: Optional[str] = None
    signal: Optional[Any] = None
    options: Optional[Dict[str, Any]] = None


@runtime_checkable
class AgentModel(Protocol):
    """Protocol for LLM model adapters."""

    def stream(
        self, request: AgentModelRequest
    ) -> Union[AsyncIterable[AgentModelEvent], Awaitable[AsyncIterable[AgentModelEvent]]]:
        ...


# ---------------------------------------------------------------------------
# Hook types
# ---------------------------------------------------------------------------


@dataclass
class AgentStopControl:
    """Control object returned from hooks to stop the agent."""

    stop: bool = False
    reason: Optional[str] = None


@dataclass
class AgentBeforeModelResult:
    """Result from a before-model hook."""

    stop: bool = False
    reason: Optional[str] = None
    messages: Optional[List[AgentMessage]] = None
    tools: Optional[List[AgentToolDefinition]] = None
    options: Optional[Dict[str, Any]] = None


@dataclass
class AgentBeforeToolResult:
    """Result from a before-tool hook."""

    skip: bool = False
    stop: bool = False
    reason: Optional[str] = None
    input: Optional[Any] = None


@dataclass
class AgentAfterToolResult:
    """Result from an after-tool hook."""

    stop: bool = False
    reason: Optional[str] = None
    result: Optional[AgentToolResult] = None


# ---------------------------------------------------------------------------
# Plugin types
# ---------------------------------------------------------------------------


@dataclass
class AgentRuntimePluginContext:
    """Context passed to plugin setup."""

    agent_id: str
    agent_role: Optional[str] = None
    system_prompt: Optional[str] = None


@dataclass
class AgentRuntimePluginSetup:
    """Setup result from a plugin."""

    tools: Optional[List[AgentTool]] = None
    hooks: Optional[Dict[str, Any]] = None  # partial AgentRuntimeHooks


class AgentRuntimePlugin(Protocol):
    """Protocol for agent runtime plugins."""

    name: str

    async def setup(
        self, context: AgentRuntimePluginContext
    ) -> Optional[AgentRuntimePluginSetup]:
        ...


# ---------------------------------------------------------------------------
# Gateway / provider types
# ---------------------------------------------------------------------------


@dataclass
class GatewayModelDefinition:
    """Definition of a model provided by a gateway."""

    id: str
    name: str
    provider_id: str
    description: Optional[str] = None
    context_window: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    capabilities: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class GatewayProviderManifest:
    """Provider registration manifest."""

    id: str
    name: str
    default_model_id: str
    models: List[GatewayModelDefinition]
    description: Optional[str] = None
    capabilities: Optional[List[str]] = None
    api_key_env: Optional[List[str]] = None
    docs_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class GatewayProviderSettings:
    """Settings for a gateway provider."""

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout_ms: Optional[int] = None
    options: Optional[Dict[str, Any]] = None


@dataclass
class GatewayProviderConfig(GatewayProviderSettings):
    """Configuration for a specific provider."""

    provider_id: str = ""
    enabled: bool = True
    default_model_id: Optional[str] = None
    models: Optional[List[GatewayModelDefinition]] = None


@dataclass
class GatewayStreamRequest:
    """A streaming request to the gateway."""

    provider_id: str
    model_id: str
    messages: List[AgentMessage]
    system_prompt: Optional[str] = None
    tools: Optional[List[AgentToolDefinition]] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    reasoning: Optional[Dict[str, Any]] = None
    signal: Optional[Any] = None


# ---------------------------------------------------------------------------
# Tool approval
# ---------------------------------------------------------------------------


@dataclass
class ToolApprovalRequest:
    """Request for tool use approval."""

    tool_name: str
    tool_call_id: str
    input: Any
    agent_id: str
    iteration: int


@dataclass
class ToolApprovalResult:
    """Result of tool approval decision."""

    approved: bool
    reason: Optional[str] = None
    modified_input: Optional[Any] = None


@dataclass
class ToolPolicy:
    """Policy governing tool approval behavior."""

    require_approval: Optional[bool] = None
    auto_approve: Optional[bool] = None


# ---------------------------------------------------------------------------
# Session / QuiverCore types
# ---------------------------------------------------------------------------


@dataclass
class SessionConfig:
    """Configuration for a QuiverCore session."""

    provider_id: str
    model_id: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    system_prompt: Optional[str] = None
    cwd: Optional[str] = None
    enable_tools: bool = True
    max_iterations: Optional[int] = None
    tools: Optional[List[AgentTool]] = None
    headers: Optional[Dict[str, str]] = None
    options: Optional[Dict[str, Any]] = None


@dataclass
class SessionRecord:
    """Persisted session record."""

    session_id: str
    created_at: int
    updated_at: int
    status: str
    config: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    message_count: int = 0


@dataclass
class StartSessionResult:
    """Result from starting a QuiverCore session."""

    session_id: str
    agent_id: str


# ---------------------------------------------------------------------------
# MCP types
# ---------------------------------------------------------------------------


@dataclass
class McpServer:
    """MCP server configuration."""

    name: str
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None
    transport: Literal["stdio", "sse", "http"] = "stdio"


@dataclass
class McpTool:
    """A tool from an MCP server."""

    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    server_name: str = ""


# ---------------------------------------------------------------------------
# Hub / RPC types
# ---------------------------------------------------------------------------


@dataclass
class HubOptions:
    """Options for the QuiverCore Hub mode."""

    address: Optional[str] = None
    port: int = 8765
    token: Optional[str] = None
    auto_start: bool = True


# ---------------------------------------------------------------------------
# Cron / automation types
# ---------------------------------------------------------------------------


@dataclass
class CronSpec:
    """A cron automation spec."""

    id: str
    prompt: str
    schedule: Optional[str] = None  # cron expression
    enabled: bool = True
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Event types emitted during agent execution
# ---------------------------------------------------------------------------

AgentRuntimeEvent = Dict[str, Any]
# Possible types:
#   run-started, message-added, turn-started, assistant-text-delta,
#   assistant-reasoning-delta, assistant-message, tool-started, tool-updated,
#   tool-finished, usage-updated, turn-finished, status-notice,
#   run-finished, run-failed

AgentEventListener = Callable[[AgentRuntimeEvent], None]
