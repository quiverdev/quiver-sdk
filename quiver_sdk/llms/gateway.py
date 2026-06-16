"""
LLM gateway for the Quiver SDK.
Mirrors DefaultGateway from @quiver/llms.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any, AsyncIterable, Dict, List, Optional

from quiver_sdk.types import (
    AgentMessage,
    AgentModel,
    AgentModelEvent,
    AgentModelRequest,
    AgentToolDefinition,
    GatewayModelDefinition,
    GatewayProviderConfig,
    GatewayProviderManifest,
    GatewayStreamRequest,
)
from quiver_sdk.llms.providers.registry import BUILTIN_PROVIDERS, ProviderRegistry
from quiver_sdk.utils import estimate_tokens, safe_json_stringify


class GatewayModelAdapter:
    """Adapts a gateway stream call into an AgentModel."""

    def __init__(
        self,
        gateway: "DefaultGateway",
        provider_id: str,
        model_id: Optional[str],
        defaults: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._gateway = gateway
        self._provider_id = provider_id
        self._model_id = model_id
        self._defaults = defaults or {}

    async def stream(
        self, request: AgentModelRequest
    ) -> AsyncIterable[AgentModelEvent]:
        opts = request.options or {}
        return await self._gateway.stream(
            GatewayStreamRequest(
                provider_id=self._provider_id,
                model_id=self._model_id or "",
                messages=list(request.messages),
                system_prompt=request.system_prompt,
                tools=list(request.tools),
                temperature=opts.get("temperature") or self._defaults.get("temperature"),
                max_tokens=opts.get("max_tokens") or self._defaults.get("max_tokens"),
                metadata=opts.get("metadata") or self._defaults.get("metadata"),
                reasoning=opts.get("reasoning") or self._defaults.get("reasoning"),
                signal=request.signal or self._defaults.get("signal"),
            )
        )


def _estimate_request_tokens(request: GatewayStreamRequest) -> int:
    """Estimate input token count for a stream request."""
    try:
        serialized = safe_json_stringify({
            "systemPrompt": request.system_prompt,
            "messages": [
                {"role": m.role if hasattr(m, "role") else m.get("role"),
                 "content": m.content if hasattr(m, "content") else m.get("content")}
                for m in request.messages
            ],
            "tools": [
                {"name": t.name if hasattr(t, "name") else t.get("name"),
                 "description": t.description if hasattr(t, "description") else t.get("description")}
                for t in (request.tools or [])
            ],
        })
        return estimate_tokens(len(serialized))
    except Exception:
        return 0


def _resolve_max_tokens(
    requested: Optional[int],
    model: GatewayModelDefinition,
    estimated_input: int,
    reserve: int = 1024,
) -> Optional[int]:
    """Resolve the effective max_tokens for a request."""
    if not requested or not isinstance(requested, int) or requested <= 0:
        return None

    caps = [requested]
    if model.max_output_tokens and model.max_output_tokens > 0:
        caps.append(model.max_output_tokens)
    if model.context_window and model.context_window > 0:
        remaining = model.context_window - estimated_input - reserve
        if remaining <= 0:
            return None
        caps.append(remaining)

    return max(1, min(caps))


class DefaultGateway:
    """
    The default LLM gateway.
    Routes requests to the appropriate provider based on provider_id.
    """

    def __init__(
        self,
        builtins: bool = True,
        provider_configs: Optional[List[GatewayProviderConfig]] = None,
        logger: Optional[Any] = None,
        telemetry: Optional[Any] = None,
    ) -> None:
        if builtins:
            self._registry = BUILTIN_PROVIDERS
        else:
            self._registry = ProviderRegistry()

        self._logger = logger
        self._telemetry = telemetry

        for cfg in (provider_configs or []):
            self._registry.configure(cfg)

    def register_provider(
        self,
        manifest: GatewayProviderManifest,
        stream_fn: Any,
        defaults: Optional[GatewayProviderConfig] = None,
    ) -> "DefaultGateway":
        """Register a custom provider."""
        self._registry.register(manifest, stream_fn, defaults)
        return self

    def configure_provider(self, config: GatewayProviderConfig) -> "DefaultGateway":
        """Apply provider-level configuration."""
        self._registry.configure(config)
        return self

    def list_providers(self) -> List[GatewayProviderManifest]:
        """List all registered providers."""
        return self._registry.list_providers()

    def list_models(self, provider_id: Optional[str] = None) -> List[GatewayModelDefinition]:
        """List all models."""
        return self._registry.list_models(provider_id)

    def create_agent_model(
        self,
        provider_id: str,
        model_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> GatewayModelAdapter:
        """Create an AgentModel adapter for the given provider/model."""
        return GatewayModelAdapter(self, provider_id, model_id, options)

    async def stream(
        self, request: GatewayStreamRequest
    ) -> AsyncIterable[AgentModelEvent]:
        """Route a stream request to the appropriate provider."""
        provider, model = self._registry.resolve_model(request.provider_id, request.model_id or None)
        stream_fn = self._registry.get_stream_fn(request.provider_id)
        config = self._registry.get_config(request.provider_id)

        # Resolve max_tokens
        max_tokens = request.max_tokens
        if max_tokens:
            estimated_input = _estimate_request_tokens(request)
            max_tokens = _resolve_max_tokens(max_tokens, model, estimated_input)

        resolved_request = GatewayStreamRequest(
            provider_id=request.provider_id,
            model_id=model.id,
            messages=request.messages,
            system_prompt=request.system_prompt,
            tools=request.tools,
            temperature=request.temperature,
            max_tokens=max_tokens,
            metadata=request.metadata,
            reasoning=request.reasoning,
            signal=request.signal,
        )

        return await stream_fn(resolved_request, provider, model, config)


Gateway = DefaultGateway


def create_gateway(
    builtins: bool = True,
    provider_configs: Optional[List[GatewayProviderConfig]] = None,
    logger: Optional[Any] = None,
    telemetry: Optional[Any] = None,
) -> DefaultGateway:
    """
    Create a new LLM gateway.

    Args:
        builtins: Whether to include built-in providers (default True)
        provider_configs: Optional per-provider configuration (API keys, base URLs, etc.)
        logger: Optional logger instance
        telemetry: Optional telemetry service

    Returns:
        DefaultGateway instance

    Example::

        gateway = create_gateway(
            provider_configs=[
                GatewayProviderConfig(
                    provider_id="anthropic",
                    api_key="sk-ant-...",
                )
            ]
        )
        model = gateway.create_agent_model("anthropic", "claude-sonnet-4-6")
    """
    return DefaultGateway(
        builtins=builtins,
        provider_configs=provider_configs,
        logger=logger,
        telemetry=telemetry,
    )
