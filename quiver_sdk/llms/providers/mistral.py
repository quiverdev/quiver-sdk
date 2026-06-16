"""
Mistral provider implementation for the Quiver SDK LLM gateway.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterable, Dict, List, Optional

from quiver_sdk.types import (
    AgentModelEvent,
    GatewayModelDefinition,
    GatewayProviderConfig,
    GatewayProviderManifest,
    GatewayStreamRequest,
)
from quiver_sdk.llms.providers.base import _messages_to_openai, _tools_to_openai


MISTRAL_MODELS: List[GatewayModelDefinition] = [
    GatewayModelDefinition(
        id="mistral-large-latest",
        name="Mistral Large",
        provider_id="mistral",
        context_window=128_000,
        max_output_tokens=8_192,
        capabilities=["text", "tools"],
    ),
    GatewayModelDefinition(
        id="codestral-latest",
        name="Codestral",
        provider_id="mistral",
        context_window=256_000,
        max_output_tokens=16_384,
        capabilities=["text", "tools"],
    ),
    GatewayModelDefinition(
        id="mistral-small-latest",
        name="Mistral Small",
        provider_id="mistral",
        context_window=128_000,
        max_output_tokens=8_192,
        capabilities=["text", "tools"],
    ),
    GatewayModelDefinition(
        id="open-mixtral-8x22b",
        name="Mixtral 8x22B",
        provider_id="mistral",
        context_window=65_536,
        max_output_tokens=8_192,
        capabilities=["text", "tools"],
    ),
]

MISTRAL_MANIFEST = GatewayProviderManifest(
    id="mistral",
    name="Mistral AI",
    default_model_id="mistral-large-latest",
    models=MISTRAL_MODELS,
    description="Mistral AI models",
    api_key_env=["MISTRAL_API_KEY"],
    docs_url="https://docs.mistral.ai",
)


async def stream_mistral(
    request: GatewayStreamRequest,
    provider: GatewayProviderManifest,
    model: GatewayModelDefinition,
    config: GatewayProviderConfig,
) -> AsyncIterable[AgentModelEvent]:
    """Stream from Mistral API."""
    try:
        from mistralai import Mistral
    except ImportError:
        raise ImportError(
            "mistralai package is required for Mistral provider. "
            "Install it with: pip install mistralai"
        )

    api_key = config.api_key
    if not api_key:
        import os
        api_key = os.environ.get("MISTRAL_API_KEY")

    client_kwargs: Dict[str, Any] = {}
    if api_key:
        client_kwargs["api_key"] = api_key
    if config.base_url:
        client_kwargs["server_url"] = config.base_url

    client = Mistral(**client_kwargs)

    messages = _messages_to_openai(request.messages)
    if request.system_prompt:
        messages = [{"role": "system", "content": request.system_prompt}] + messages

    tools = _tools_to_openai(request.tools or [])

    kwargs: Dict[str, Any] = {
        "model": request.model_id,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if request.max_tokens:
        kwargs["max_tokens"] = request.max_tokens
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature

    async def _generate() -> AsyncIterable[AgentModelEvent]:
        try:
            tool_calls_map: Dict[int, Dict[str, Any]] = {}

            stream = await client.chat.stream_async(**kwargs)
            async for event in stream:
                data = event.data
                if not data.choices:
                    if hasattr(data, "usage") and data.usage:
                        yield {
                            "type": "usage",
                            "usage": {
                                "input_tokens": data.usage.prompt_tokens or 0,
                                "output_tokens": data.usage.completion_tokens or 0,
                            },
                        }
                    continue

                choice = data.choices[0]
                delta = choice.delta

                if delta.content:
                    yield {"type": "text-delta", "text": delta.content}

                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for i, tc_delta in enumerate(delta.tool_calls):
                        idx = getattr(tc_delta, "index", i)
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {
                                "id": getattr(tc_delta, "id", "") or "",
                                "name": "",
                                "input_text": "",
                            }
                        if getattr(tc_delta, "id", None):
                            tool_calls_map[idx]["id"] = tc_delta.id
                        func = getattr(tc_delta, "function", None)
                        if func:
                            if getattr(func, "name", None):
                                tool_calls_map[idx]["name"] = func.name
                                yield {
                                    "type": "tool-call-delta",
                                    "index": idx,
                                    "toolCallId": tool_calls_map[idx]["id"],
                                    "toolName": func.name,
                                }
                            if getattr(func, "arguments", None):
                                tool_calls_map[idx]["input_text"] += func.arguments
                                yield {
                                    "type": "tool-call-delta",
                                    "index": idx,
                                    "toolCallId": tool_calls_map[idx]["id"],
                                    "inputText": func.arguments,
                                }

                if choice.finish_reason:
                    for idx, tc in tool_calls_map.items():
                        try:
                            parsed = json.loads(tc["input_text"]) if tc["input_text"] else {}
                        except Exception:
                            parsed = {}
                        yield {
                            "type": "tool-call-delta",
                            "index": idx,
                            "toolCallId": tc["id"],
                            "toolName": tc["name"],
                            "input": parsed,
                        }

                    reason = choice.finish_reason
                    if reason == "stop":
                        yield {"type": "finish", "reason": "stop"}
                    elif reason == "tool_calls":
                        yield {"type": "finish", "reason": "tool-calls"}
                    elif reason == "length":
                        yield {"type": "finish", "reason": "max-tokens"}
                    else:
                        yield {"type": "finish", "reason": "stop"}

        except Exception as e:
            yield {"type": "finish", "reason": "error", "error": str(e)}

    return _generate()
