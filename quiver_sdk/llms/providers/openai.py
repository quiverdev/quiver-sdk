"""
OpenAI provider implementation for the Quiver SDK LLM gateway.
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


OPENAI_MODELS: List[GatewayModelDefinition] = [
    GatewayModelDefinition(
        id="gpt-4o",
        name="GPT-4o",
        provider_id="openai",
        context_window=128_000,
        max_output_tokens=16_384,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="gpt-4o-mini",
        name="GPT-4o Mini",
        provider_id="openai",
        context_window=128_000,
        max_output_tokens=16_384,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="o1",
        name="o1",
        provider_id="openai",
        context_window=200_000,
        max_output_tokens=100_000,
        capabilities=["text", "tools", "reasoning"],
    ),
    GatewayModelDefinition(
        id="o1-mini",
        name="o1-mini",
        provider_id="openai",
        context_window=128_000,
        max_output_tokens=65_536,
        capabilities=["text", "tools", "reasoning"],
    ),
    GatewayModelDefinition(
        id="gpt-5.5",
        name="GPT-5.5",
        provider_id="openai",
        context_window=128_000,
        max_output_tokens=16_384,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="gpt-5.3",
        name="GPT-5.3 Codex",
        provider_id="openai",
        context_window=128_000,
        max_output_tokens=16_384,
        capabilities=["text", "tools"],
    ),
]

OPENAI_MANIFEST = GatewayProviderManifest(
    id="openai",
    name="OpenAI",
    default_model_id="gpt-4o",
    models=OPENAI_MODELS,
    description="OpenAI GPT models",
    api_key_env=["OPENAI_API_KEY"],
    docs_url="https://platform.openai.com/docs",
)


async def stream_openai(
    request: GatewayStreamRequest,
    provider: GatewayProviderManifest,
    model: GatewayModelDefinition,
    config: GatewayProviderConfig,
) -> AsyncIterable[AgentModelEvent]:
    """Stream from OpenAI API."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise ImportError(
            "openai package is required for OpenAI provider. "
            "Install it with: pip install openai"
        )

    api_key = config.api_key
    if not api_key:
        import os
        api_key = os.environ.get("OPENAI_API_KEY")

    client_kwargs: Dict[str, Any] = {}
    if api_key:
        client_kwargs["api_key"] = api_key
    if config.base_url:
        client_kwargs["base_url"] = config.base_url
    if config.headers:
        client_kwargs["default_headers"] = config.headers

    client = AsyncOpenAI(**client_kwargs)

    messages = _messages_to_openai(request.messages)
    if request.system_prompt:
        messages = [{"role": "system", "content": request.system_prompt}] + messages

    tools = _tools_to_openai(request.tools or [])

    kwargs: Dict[str, Any] = {
        "model": request.model_id,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
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

            async with await client.chat.completions.create(**kwargs) as stream:
                async for chunk in stream:
                    if not chunk.choices:
                        if chunk.usage:
                            yield {
                                "type": "usage",
                                "usage": {
                                    "input_tokens": chunk.usage.prompt_tokens or 0,
                                    "output_tokens": chunk.usage.completion_tokens or 0,
                                },
                            }
                        continue

                    choice = chunk.choices[0]
                    delta = choice.delta

                    if delta.content:
                        yield {"type": "text-delta", "text": delta.content}

                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_map:
                                tool_calls_map[idx] = {
                                    "id": tc_delta.id or "",
                                    "name": "",
                                    "input_text": "",
                                }
                            if tc_delta.id:
                                tool_calls_map[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tool_calls_map[idx]["name"] = tc_delta.function.name
                                    yield {
                                        "type": "tool-call-delta",
                                        "index": idx,
                                        "toolCallId": tool_calls_map[idx]["id"],
                                        "toolName": tc_delta.function.name,
                                    }
                                if tc_delta.function.arguments:
                                    tool_calls_map[idx]["input_text"] += tc_delta.function.arguments
                                    yield {
                                        "type": "tool-call-delta",
                                        "index": idx,
                                        "toolCallId": tool_calls_map[idx]["id"],
                                        "inputText": tc_delta.function.arguments,
                                    }

                    if choice.finish_reason:
                        # Emit complete tool calls
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
