"""
Base provider interface for LLM gateway providers.
"""

from __future__ import annotations

from typing import Any, AsyncIterable, Dict, List, Optional, Protocol, Union

from quiver_sdk.types import (
    AgentMessage,
    AgentModelEvent,
    AgentToolDefinition,
    GatewayModelDefinition,
    GatewayProviderConfig,
    GatewayProviderManifest,
    GatewayStreamRequest,
)


class GatewayProvider(Protocol):
    """Protocol for gateway provider implementations."""

    async def stream(
        self,
        request: GatewayStreamRequest,
        provider: GatewayProviderManifest,
        model: GatewayModelDefinition,
        config: GatewayProviderConfig,
    ) -> AsyncIterable[AgentModelEvent]:
        ...


def _messages_to_openai(messages: List[AgentMessage]) -> List[Dict[str, Any]]:
    """Convert AgentMessages to OpenAI-format messages."""
    result = []
    for msg in messages:
        role = msg.role if isinstance(msg, object) and hasattr(msg, "role") else msg["role"]
        content_parts = msg.content if hasattr(msg, "content") else msg["content"]

        text_parts = []
        tool_calls = []
        tool_results = []

        for part in content_parts:
            ptype = part.get("type") if isinstance(part, dict) else part.type
            if ptype == "text":
                text_parts.append(part.get("text", "") if isinstance(part, dict) else part.text)
            elif ptype == "reasoning":
                text_parts.append(part.get("text", "") if isinstance(part, dict) else part.text)
            elif ptype == "tool-call":
                tc = part if isinstance(part, dict) else vars(part)
                tool_calls.append({
                    "id": tc.get("toolCallId", tc.get("tool_call_id", "")),
                    "type": "function",
                    "function": {
                        "name": tc.get("toolName", tc.get("tool_name", "")),
                        "arguments": (
                            tc.get("input", "{}")
                            if isinstance(tc.get("input"), str)
                            else __import__("json").dumps(tc.get("input", {}))
                        ),
                    },
                })
            elif ptype == "tool-result":
                tc = part if isinstance(part, dict) else vars(part)
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.get("toolCallId", tc.get("tool_call_id", "")),
                    "content": (
                        tc.get("output", "")
                        if isinstance(tc.get("output"), str)
                        else __import__("json").dumps(tc.get("output", ""))
                    ),
                })

        if tool_results:
            result.extend(tool_results)
        elif tool_calls:
            oai_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else None,
                "tool_calls": tool_calls,
            }
            if oai_msg["content"] is None:
                del oai_msg["content"]
            result.append(oai_msg)
        else:
            result.append({
                "role": role,
                "content": "\n".join(text_parts),
            })

    return result


def _tools_to_openai(tools: List[AgentToolDefinition]) -> List[Dict[str, Any]]:
    """Convert AgentToolDefinitions to OpenAI-format tool specs."""
    result = []
    for tool in tools:
        name = tool.name if hasattr(tool, "name") else tool["name"]
        desc = tool.description if hasattr(tool, "description") else tool["description"]
        schema = tool.input_schema if hasattr(tool, "input_schema") else tool["input_schema"]
        result.append({
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": schema,
            },
        })
    return result


def _messages_to_anthropic(messages: List[AgentMessage]) -> List[Dict[str, Any]]:
    """Convert AgentMessages to Anthropic-format messages."""
    result = []
    for msg in messages:
        role = msg.role if hasattr(msg, "role") else msg["role"]
        content_parts = msg.content if hasattr(msg, "content") else msg["content"]

        anthropic_content = []
        for part in content_parts:
            ptype = part.get("type") if isinstance(part, dict) else getattr(part, "type", "")
            if ptype == "text":
                anthropic_content.append({
                    "type": "text",
                    "text": part.get("text", "") if isinstance(part, dict) else part.text,
                })
            elif ptype == "reasoning":
                anthropic_content.append({
                    "type": "text",
                    "text": part.get("text", "") if isinstance(part, dict) else part.text,
                })
            elif ptype == "tool-call":
                tc = part if isinstance(part, dict) else vars(part)
                anthropic_content.append({
                    "type": "tool_use",
                    "id": tc.get("toolCallId", tc.get("tool_call_id", "")),
                    "name": tc.get("toolName", tc.get("tool_name", "")),
                    "input": tc.get("input", {}),
                })
            elif ptype == "tool-result":
                tc = part if isinstance(part, dict) else vars(part)
                output = tc.get("output", "")
                if not isinstance(output, str):
                    output = __import__("json").dumps(output)
                anthropic_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc.get("toolCallId", tc.get("tool_call_id", "")),
                    "content": output,
                    "is_error": tc.get("isError", tc.get("is_error", False)),
                })

        if role == "tool":
            role = "user"

        if anthropic_content:
            result.append({"role": role, "content": anthropic_content})

    return result


def _tools_to_anthropic(tools: List[AgentToolDefinition]) -> List[Dict[str, Any]]:
    """Convert AgentToolDefinitions to Anthropic-format tool specs."""
    result = []
    for tool in tools:
        name = tool.name if hasattr(tool, "name") else tool["name"]
        desc = tool.description if hasattr(tool, "description") else tool["description"]
        schema = tool.input_schema if hasattr(tool, "input_schema") else tool["input_schema"]
        result.append({
            "name": name,
            "description": desc,
            "input_schema": schema,
        })
    return result
