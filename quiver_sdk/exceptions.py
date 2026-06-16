"""
Custom exceptions for the Quiver SDK.
"""

from __future__ import annotations


class AgentRuntimeAbortError(Exception):
    """Raised when an agent run is aborted."""

    def __init__(self, reason: object = None) -> None:
        if isinstance(reason, str):
            message = reason
        elif isinstance(reason, Exception):
            message = str(reason)
        elif reason is None:
            message = "Run aborted"
        else:
            message = str(reason)
        super().__init__(message)
        self.reason = reason


class ControlledStopError(Exception):
    """Raised internally to stop a run gracefully via a hook."""

    def __init__(self, reason: str | None = None) -> None:
        super().__init__(reason or "Run stopped by runtime control")
        self.reason = reason


class TimeoutError(Exception):
    """Raised when an operation times out."""

    def __init__(self, message: str, timeout_ms: int) -> None:
        super().__init__(message)
        self.timeout_ms = timeout_ms


class CommandExitError(Exception):
    """Raised when a shell command exits with a non-zero code."""

    def __init__(self, exit_code: int, output: str) -> None:
        super().__init__(f"Command exited with code {exit_code}")
        self.exit_code = exit_code
        self.output = output


class GatewayError(Exception):
    """Raised when an LLM gateway operation fails."""


class ProviderNotFoundError(GatewayError):
    """Raised when an LLM provider is not found."""


class ModelNotFoundError(GatewayError):
    """Raised when a model is not found for a provider."""


class McpError(Exception):
    """Raised when an MCP operation fails."""


class SessionNotFoundError(Exception):
    """Raised when a session is not found."""


class StorageError(Exception):
    """Raised when a storage operation fails."""
