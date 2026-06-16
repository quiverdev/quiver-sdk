"""
AWS Bedrock provider implementation for the Quiver SDK LLM gateway.
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


BEDROCK_MODELS: List[GatewayModelDefinition] = [
    GatewayModelDefinition(
        id="anthropic.claude-opus-4-7",
        name="Claude Opus 4.7 (Bedrock)",
        provider_id="bedrock",
        context_window=200_000,
        max_output_tokens=32_000,
        capabilities=["text", "tools", "reasoning", "images"],
    ),
    GatewayModelDefinition(
        id="anthropic.claude-sonnet-4-6",
        name="Claude Sonnet 4.6 (Bedrock)",
        provider_id="bedrock",
        context_window=200_000,
        max_output_tokens=16_000,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        name="Claude 3.5 Sonnet v2 (Bedrock)",
        provider_id="bedrock",
        context_window=200_000,
        max_output_tokens=8_096,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="meta.llama3-70b-instruct-v1:0",
        name="Llama 3 70B (Bedrock)",
        provider_id="bedrock",
        context_window=128_000,
        max_output_tokens=8_192,
        capabilities=["text", "tools"],
    ),
]

BEDROCK_MANIFEST = GatewayProviderManifest(
    id="bedrock",
    name="AWS Bedrock",
    default_model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
    models=BEDROCK_MODELS,
    description="AWS Bedrock hosted models",
    api_key_env=["AWS_ACCESS_KEY_ID"],
    docs_url="https://aws.amazon.com/bedrock/",
)


async def stream_bedrock(
    request: GatewayStreamRequest,
    provider: GatewayProviderManifest,
    model: GatewayModelDefinition,
    config: GatewayProviderConfig,
) -> AsyncIterable[AgentModelEvent]:
    """Stream from AWS Bedrock API using boto3."""
    try:
        import boto3
        import botocore
    except ImportError:
        raise ImportError(
            "boto3 package is required for AWS Bedrock provider. "
            "Install it with: pip install boto3"
        )

    import asyncio
    import os

    region = (config.options or {}).get("region") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    session_kwargs: Dict[str, Any] = {"region_name": region}
    if config.api_key:
        session_kwargs["aws_access_key_id"] = config.api_key
        secret = (config.options or {}).get("aws_secret_access_key") or os.environ.get("AWS_SECRET_ACCESS_KEY")
        if secret:
            session_kwargs["aws_secret_access_key"] = secret
        session_token = (config.options or {}).get("aws_session_token") or os.environ.get("AWS_SESSION_TOKEN")
        if session_token:
            session_kwargs["aws_session_token"] = session_token

    model_id = request.model_id

    async def _generate() -> AsyncIterable[AgentModelEvent]:
        try:
            session = boto3.Session(**session_kwargs)
            bedrock = session.client("bedrock-runtime")

            messages = _messages_to_anthropic(request.messages)
            tools = _tools_to_anthropic(request.tools or [])

            body: Dict[str, Any] = {
                "anthropic_version": "bedrock-2023-05-31",
                "messages": messages,
                "max_tokens": request.max_tokens or 8096,
            }
            if request.system_prompt:
                body["system"] = request.system_prompt
            if tools:
                body["tools"] = tools
            if request.temperature is not None:
                body["temperature"] = request.temperature

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: bedrock.invoke_model_with_response_stream(
                    modelId=model_id,
                    body=json.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )
            )

            current_tool_id: Optional[str] = None
            current_tool_name: Optional[str] = None
            current_tool_input = ""
            tool_index = 0

            stream = response.get("body")
            for event in stream:
                chunk = event.get("chunk")
                if not chunk:
                    continue
                data = json.loads(chunk["bytes"])
                event_type = data.get("type", "")

                if event_type == "content_block_start":
                    block = data.get("content_block", {})
                    if block.get("type") == "tool_use":
                        current_tool_id = block.get("id")
                        current_tool_name = block.get("name")
                        current_tool_input = ""
                        yield {
                            "type": "tool-call-delta",
                            "index": tool_index,
                            "toolCallId": current_tool_id,
                            "toolName": current_tool_name,
                        }
                        tool_index += 1

                elif event_type == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield {"type": "text-delta", "text": delta["text"]}
                    elif delta.get("type") == "thinking_delta":
                        yield {"type": "reasoning-delta", "text": delta["thinking"]}
                    elif delta.get("type") == "input_json_delta":
                        current_tool_input += delta.get("partial_json", "")
                        yield {
                            "type": "tool-call-delta",
                            "toolCallId": current_tool_id,
                            "inputText": delta.get("partial_json", ""),
                        }

                elif event_type == "content_block_stop":
                    if current_tool_id and current_tool_input:
                        try:
                            parsed = json.loads(current_tool_input)
                        except Exception:
                            parsed = {}
                        yield {
                            "type": "tool-call-delta",
                            "toolCallId": current_tool_id,
                            "toolName": current_tool_name,
                            "input": parsed,
                        }
                        current_tool_id = None
                        current_tool_name = None
                        current_tool_input = ""

                elif event_type == "message_delta":
                    usage = data.get("usage", {})
                    if usage:
                        yield {
                            "type": "usage",
                            "usage": {
                                "output_tokens": usage.get("output_tokens", 0),
                            },
                        }
                    stop_reason = data.get("delta", {}).get("stop_reason")
                    if stop_reason == "end_turn":
                        yield {"type": "finish", "reason": "stop"}
                    elif stop_reason == "tool_use":
                        yield {"type": "finish", "reason": "tool-calls"}
                    elif stop_reason == "max_tokens":
                        yield {"type": "finish", "reason": "max-tokens"}

                elif event_type == "message_start":
                    usage = data.get("message", {}).get("usage", {})
                    if usage:
                        yield {
                            "type": "usage",
                            "usage": {
                                "input_tokens": usage.get("input_tokens", 0),
                                "cache_read_tokens": usage.get("cache_read_input_tokens", 0) or 0,
                                "cache_write_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
                            },
                        }

        except Exception as e:
            yield {"type": "finish", "reason": "error", "error": str(e)}

    return _generate()
