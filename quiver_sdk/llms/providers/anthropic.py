"""
Anthropic provider implementation for the Quiver SDK LLM gateway.
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
from quiver_sdk.llms.providers.base import _messages_to_anthropic, _tools_to_anthropic


ANTHROPIC_MODELS: List[GatewayModelDefinition] = [
    GatewayModelDefinition(
        id="claude-opus-4-7",
        name="Claude Opus 4.7",
        provider_id="anthropic",
        context_window=200_000,
        max_output_tokens=32_000,
        capabilities=["text", "tools", "reasoning", "images"],
    ),
    GatewayModelDefinition(
        id="claude-sonnet-4-6",
        name="Claude Sonnet 4.6",
        provider_id="anthropic",
        context_window=200_000,
        max_output_tokens=16_000,
        capabilities=["text", "tools", "reasoning", "images"],
    ),
    GatewayModelDefinition(
        id="claude-haiku-4-5",
        name="Claude Haiku 4.5",
        provider_id="anthropic",
        context_window=200_000,
        max_output_tokens=8_096,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="claude-3-5-sonnet-20241022",
        name="Claude 3.5 Sonnet",
        provider_id="anthropic",
        context_window=200_000,
        max_output_tokens=8_096,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="claude-3-5-haiku-20241022",
        name="Claude 3.5 Haiku",
        provider_id="anthropic",
        context_window=200_000,
        max_output_tokens=8_096,
        capabilities=["text", "tools", "images"],
    ),
]

ANTHROPIC_MANIFEST = GatewayProviderManifest(
    id="anthropic",
    name="Anthropic",
    default_model_id="claude-sonnet-4-6",
    models=ANTHROPIC_MODELS,
    description="Anthropic Claude models",
    api_key_env=["ANTHROPIC_API_KEY"],
    docs_url="https://docs.anthropic.com",
)


async def stream_anthropic(
    request: GatewayStreamRequest,
    provider: GatewayProviderManifest,
    model: GatewayModelDefinition,
    config: GatewayProviderConfig,
) -> AsyncIterable[AgentModelEvent]:
    """Stream from Anthropic API."""
    try:
        import anthropic as anthropic_sdk
    except ImportError:
        raise ImportError(
            "anthropic package is required for Anthropic provider. "
            "Install it with: pip install anthropic"
        )

    api_key = config.api_key
    if not api_key:
        import os
        for env_var in (ANTHROPIC_MANIFEST.api_key_env or []):
            api_key = os.environ.get(env_var)
            if api_key:
                break

    client_kwargs: Dict[str, Any] = {}
    if api_key:
        client_kwargs["api_key"] = api_key
    if config.base_url:
        client_kwargs["base_url"] = config.base_url
    if config.headers:
        client_kwargs["default_headers"] = config.headers

    client = anthropic_sdk.AsyncAnthropic(**client_kwargs)

    messages = _messages_to_anthropic(request.messages)
    tools = _tools_to_anthropic(request.tools or [])

    kwargs: Dict[str, Any] = {
        "model": request.model_id,
        "messages": messages,
        "max_tokens": request.max_tokens or 8096,
    }
    if request.system_prompt:
        kwargs["system"] = request.system_prompt
    if tools:
        kwargs["tools"] = tools
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature

    # Reasoning/thinking support
    reasoning = request.reasoning
    if reasoning and reasoning.get("enabled"):
        budget = reasoning.get("budgetTokens", 8000)
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}

    async def _generate() -> AsyncIterable[AgentModelEvent]:
        try:
            async with client.messages.stream(**kwargs) as stream:
                current_tool_id: Optional[str] = None
                current_tool_name: Optional[str] = None
                current_tool_input = ""
                tool_index = 0

                async for event in stream:
                    event_type = type(event).__name__

                    if event_type == "RawContentBlockStartEvent":
                        block = event.content_block
                        block_type = getattr(block, "type", "")
                        if block_type == "text":
                            pass
                        elif block_type == "thinking":
                            pass
                        elif block_type == "tool_use":
                            current_tool_id = getattr(block, "id", None)
                            current_tool_name = getattr(block, "name", None)
                            current_tool_input = ""
                            yield {
                                "type": "tool-call-delta",
                                "index": tool_index,
                                "toolCallId": current_tool_id,
                                "toolName": current_tool_name,
                            }
                            tool_index += 1

                    elif event_type == "RawContentBlockDeltaEvent":
                        delta = event.delta
                        delta_type = getattr(delta, "type", "")
                        if delta_type == "text_delta":
                            yield {"type": "text-delta", "text": delta.text}
                        elif delta_type == "thinking_delta":
                            yield {
                                "type": "reasoning-delta",
                                "text": delta.thinking,
                                "redacted": False,
                            }
                        elif delta_type == "input_json_delta":
                            current_tool_input += delta.partial_json
                            yield {
                                "type": "tool-call-delta",
                                "toolCallId": current_tool_id,
                                "toolName": current_tool_name,
                                "inputText": delta.partial_json,
                            }

                    elif event_type == "RawContentBlockStopEvent":
                        if current_tool_id and current_tool_input:
                            try:
                                parsed_input = json.loads(current_tool_input)
                            except Exception:
                                parsed_input = {}
                            yield {
                                "type": "tool-call-delta",
                                "toolCallId": current_tool_id,
                                "toolName": current_tool_name,
                                "input": parsed_input,
                            }
                            current_tool_id = None
                            current_tool_name = None
                            current_tool_input = ""

                    elif event_type == "RawMessageDeltaEvent":
                        delta = event.delta
                        stop_reason = getattr(delta, "stop_reason", None)
                        usage = getattr(event, "usage", None)
                        if usage:
                            yield {
                                "type": "usage",
                                "usage": {
                                    "input_tokens": getattr(usage, "input_tokens", 0),
                                    "output_tokens": getattr(usage, "output_tokens", 0),
                                },
                            }

                    elif event_type == "RawMessageStopEvent":
                        pass

                # Get final message for usage
                try:
                    final = await stream.get_final_message()
                    usage = final.usage
                    yield {
                        "type": "usage",
                        "usage": {
                            "input_tokens": getattr(usage, "input_tokens", 0),
                            "output_tokens": getattr(usage, "output_tokens", 0),
                            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
                            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
                        },
                    }
                    stop_reason = final.stop_reason
                    if stop_reason == "end_turn":
                        yield {"type": "finish", "reason": "stop"}
                    elif stop_reason == "tool_use":
                        yield {"type": "finish", "reason": "tool-calls"}
                    elif stop_reason == "max_tokens":
                        yield {"type": "finish", "reason": "max-tokens"}
                    else:
                        yield {"type": "finish", "reason": "stop"}
                except Exception:
                    yield {"type": "finish", "reason": "stop"}

        except anthropic_sdk.APIStatusError as e:
            yield {"type": "finish", "reason": "error", "error": str(e)}
        except Exception as e:
            yield {"type": "finish", "reason": "error", "error": str(e)}

    return _generate()
