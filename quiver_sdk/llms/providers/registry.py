"""
Provider registry for the Quiver SDK LLM gateway.
"""

from __future__ import annotations

from typing import Any, AsyncIterable, Callable, Dict, List, Optional, Tuple

from quiver_sdk.types import (
    AgentModelEvent,
    GatewayModelDefinition,
    GatewayProviderConfig,
    GatewayProviderManifest,
    GatewayStreamRequest,
)
from quiver_sdk.exceptions import ModelNotFoundError, ProviderNotFoundError

StreamFn = Callable[
    [GatewayStreamRequest, GatewayProviderManifest, GatewayModelDefinition, GatewayProviderConfig],
    Any,  # AsyncIterable[AgentModelEvent]
]


class ProviderRegistry:
    """Registry of LLM providers."""

    def __init__(self) -> None:
        self._manifests: Dict[str, GatewayProviderManifest] = {}
        self._stream_fns: Dict[str, StreamFn] = {}
        self._configs: Dict[str, GatewayProviderConfig] = {}

    def register(
        self,
        manifest: GatewayProviderManifest,
        stream_fn: StreamFn,
        defaults: Optional[GatewayProviderConfig] = None,
    ) -> None:
        """Register a provider."""
        self._manifests[manifest.id] = manifest
        self._stream_fns[manifest.id] = stream_fn
        if defaults:
            self._configs[manifest.id] = defaults

    def configure(self, config: GatewayProviderConfig) -> None:
        """Apply provider-level configuration."""
        provider_id = config.provider_id
        existing = self._configs.get(provider_id)
        if existing:
            merged = GatewayProviderConfig(
                provider_id=provider_id,
                api_key=config.api_key or existing.api_key,
                base_url=config.base_url or existing.base_url,
                headers={**(existing.headers or {}), **(config.headers or {})},
                timeout_ms=config.timeout_ms or existing.timeout_ms,
                options={**(existing.options or {}), **(config.options or {})},
                enabled=config.enabled if config.enabled is not None else existing.enabled,
                default_model_id=config.default_model_id or existing.default_model_id,
                models=config.models or existing.models,
            )
            self._configs[provider_id] = merged
        else:
            self._configs[provider_id] = config

    def list_providers(self) -> List[GatewayProviderManifest]:
        """List all registered providers."""
        return list(self._manifests.values())

    def list_models(self, provider_id: Optional[str] = None) -> List[GatewayModelDefinition]:
        """List all models, optionally filtered by provider."""
        models = []
        for pid, manifest in self._manifests.items():
            if provider_id and pid != provider_id:
                continue
            config = self._configs.get(pid)
            if config and config.models:
                models.extend(config.models)
            else:
                models.extend(manifest.models)
        return models

    def resolve_model(
        self, provider_id: str, model_id: Optional[str] = None
    ) -> Tuple[GatewayProviderManifest, GatewayModelDefinition]:
        """Resolve provider and model."""
        manifest = self._manifests.get(provider_id)
        if not manifest:
            raise ProviderNotFoundError(
                f"Provider '{provider_id}' not found. "
                f"Available providers: {list(self._manifests.keys())}"
            )

        config = self._configs.get(provider_id)
        all_models = (config.models if config and config.models else None) or manifest.models

        effective_model_id = (
            model_id
            or (config.default_model_id if config else None)
            or manifest.default_model_id
        )

        model = next((m for m in all_models if m.id == effective_model_id), None)
        if not model:
            # Create a synthetic model definition for unknown model IDs
            model = GatewayModelDefinition(
                id=effective_model_id,
                name=effective_model_id,
                provider_id=provider_id,
            )

        return manifest, model

    def get_config(self, provider_id: str) -> GatewayProviderConfig:
        """Get the resolved config for a provider."""
        return self._configs.get(provider_id) or GatewayProviderConfig(
            provider_id=provider_id
        )

    def get_stream_fn(self, provider_id: str) -> StreamFn:
        """Get the stream function for a provider."""
        fn = self._stream_fns.get(provider_id)
        if not fn:
            raise ProviderNotFoundError(f"Provider '{provider_id}' not found.")
        return fn


def _build_builtin_registry() -> ProviderRegistry:
    """Build the registry with all built-in providers."""
    from quiver_sdk.llms.providers.anthropic import ANTHROPIC_MANIFEST, stream_anthropic
    from quiver_sdk.llms.providers.openai import OPENAI_MANIFEST, stream_openai
    from quiver_sdk.llms.providers.openai_compatible import (
        OPENAI_COMPATIBLE_MANIFEST,
        stream_openai_compatible,
    )
    from quiver_sdk.llms.providers.google import GOOGLE_MANIFEST, stream_google
    from quiver_sdk.llms.providers.bedrock import BEDROCK_MANIFEST, stream_bedrock
    from quiver_sdk.llms.providers.mistral import MISTRAL_MANIFEST, stream_mistral

    registry = ProviderRegistry()
    registry.register(ANTHROPIC_MANIFEST, stream_anthropic)
    registry.register(OPENAI_MANIFEST, stream_openai)
    registry.register(OPENAI_COMPATIBLE_MANIFEST, stream_openai_compatible)
    registry.register(GOOGLE_MANIFEST, stream_google)
    registry.register(BEDROCK_MANIFEST, stream_bedrock)
    registry.register(MISTRAL_MANIFEST, stream_mistral)

    # Register alias providers
    from quiver_sdk.llms.providers.anthropic import ANTHROPIC_MODELS
    # Quiver provider (proxies through Anthropic)
    quiver_manifest = GatewayProviderManifest(
        id="quiver",
        name="Quiver",
        default_model_id="claude-sonnet-4-6",
        models=ANTHROPIC_MODELS,
        description="Quiver provider (powered by Anthropic)",
        api_key_env=["QUIVER_API_KEY", "ANTHROPIC_API_KEY"],
    )
    registry.register(quiver_manifest, stream_anthropic)

    # OpenRouter
    openrouter_manifest = GatewayProviderManifest(
        id="openrouter",
        name="OpenRouter",
        default_model_id="anthropic/claude-3.5-sonnet",
        models=[
            GatewayModelDefinition(
                id="anthropic/claude-3.5-sonnet",
                name="Claude 3.5 Sonnet (OpenRouter)",
                provider_id="openrouter",
            ),
            GatewayModelDefinition(
                id="openai/gpt-4o",
                name="GPT-4o (OpenRouter)",
                provider_id="openrouter",
            ),
        ],
        description="OpenRouter API gateway",
        api_key_env=["OPENROUTER_API_KEY"],
    )
    from quiver_sdk.llms.providers.openai_compatible import stream_openai_compatible

    async def stream_openrouter(req, prov, mod, cfg):
        if not cfg.base_url:
            cfg = GatewayProviderConfig(
                provider_id=cfg.provider_id,
                api_key=cfg.api_key,
                base_url="https://openrouter.ai/api/v1",
                headers=cfg.headers,
                options=cfg.options,
            )
        return await stream_openai_compatible(req, prov, mod, cfg)

    registry.register(openrouter_manifest, stream_openrouter)

    return registry


BUILTIN_PROVIDERS: ProviderRegistry = _build_builtin_registry()
