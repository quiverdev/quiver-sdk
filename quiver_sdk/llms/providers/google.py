"""
Google Gemini provider implementation for the Quiver SDK LLM gateway.
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


GOOGLE_MODELS: List[GatewayModelDefinition] = [
    GatewayModelDefinition(
        id="gemini-2.5-pro-preview",
        name="Gemini 2.5 Pro Preview",
        provider_id="gemini",
        context_window=1_048_576,
        max_output_tokens=65_536,
        capabilities=["text", "tools", "reasoning", "images"],
    ),
    GatewayModelDefinition(
        id="gemini-2.5-flash-preview",
        name="Gemini 2.5 Flash Preview",
        provider_id="gemini",
        context_window=1_048_576,
        max_output_tokens=65_536,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="gemini-2.0-flash",
        name="Gemini 2.0 Flash",
        provider_id="gemini",
        context_window=1_048_576,
        max_output_tokens=8_192,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="gemini-1.5-pro",
        name="Gemini 1.5 Pro",
        provider_id="gemini",
        context_window=2_097_152,
        max_output_tokens=8_192,
        capabilities=["text", "tools", "images"],
    ),
    GatewayModelDefinition(
        id="gemini-3.1-pro-preview",
        name="Gemini 3.1 Pro Preview",
        provider_id="gemini",
        context_window=2_097_152,
        max_output_tokens=65_536,
        capabilities=["text", "tools", "reasoning", "images"],
    ),
    GatewayModelDefinition(
        id="gemini-3-flash-preview",
        name="Gemini 3 Flash Preview",
        provider_id="gemini",
        context_window=1_048_576,
        max_output_tokens=65_536,
        capabilities=["text", "tools", "images"],
    ),
]

GOOGLE_MANIFEST = GatewayProviderManifest(
    id="gemini",
    name="Google Gemini",
    default_model_id="gemini-2.5-pro-preview",
    models=GOOGLE_MODELS,
    description="Google Gemini models",
    api_key_env=["GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY"],
    docs_url="https://ai.google.dev/docs",
)


def _convert_messages_to_gemini(messages: list) -> list:
    """Convert AgentMessages to Gemini format."""
    result = []
    for msg in messages:
        role = msg.role if hasattr(msg, "role") else msg.get("role")
        content_parts = msg.content if hasattr(msg, "content") else msg.get("content", [])

        parts = []
        for part in content_parts:
            ptype = part.get("type") if isinstance(part, dict) else getattr(part, "type", "")
            if ptype == "text":
                text = part.get("text", "") if isinstance(part, dict) else part.text
                parts.append({"text": text})
            elif ptype == "reasoning":
                text = part.get("text", "") if isinstance(part, dict) else part.text
                parts.append({"text": text})
            elif ptype == "tool-call":
                tc = part if isinstance(part, dict) else vars(part)
                parts.append({
                    "function_call": {
                        "name": tc.get("toolName", tc.get("tool_name", "")),
                        "args": tc.get("input", {}),
                    }
                })
            elif ptype == "tool-result":
                tc = part if isinstance(part, dict) else vars(part)
                output = tc.get("output", "")
                if not isinstance(output, (str, dict)):
                    output = json.dumps(output)
                parts.append({
                    "function_response": {
                        "name": tc.get("toolName", tc.get("tool_name", "")),
                        "response": {"result": output},
                    }
                })

        gemini_role = "user" if role in ("user", "tool") else "model"
        if parts:
            result.append({"role": gemini_role, "parts": parts})

    return result


async def stream_google(
    request: GatewayStreamRequest,
    provider: GatewayProviderManifest,
    model: GatewayModelDefinition,
    config: GatewayProviderConfig,
) -> AsyncIterable[AgentModelEvent]:
    """Stream from Google Gemini API."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError(
            "google-generativeai package is required for Google provider. "
            "Install it with: pip install google-generativeai"
        )

    api_key = config.api_key
    if not api_key:
        import os
        for env_var in (GOOGLE_MANIFEST.api_key_env or []):
            api_key = os.environ.get(env_var)
            if api_key:
                break

    if api_key:
        genai.configure(api_key=api_key)

    tool_defs = []
    for tool in (request.tools or []):
        name = tool.name if hasattr(tool, "name") else tool["name"]
        desc = tool.description if hasattr(tool, "description") else tool["description"]
        schema = tool.input_schema if hasattr(tool, "input_schema") else tool["input_schema"]
        tool_defs.append(genai.protos.Tool(
            function_declarations=[
                genai.protos.FunctionDeclaration(
                    name=name,
                    description=desc,
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            k: genai.protos.Schema(type=genai.protos.Type.STRING)
                            for k in schema.get("properties", {})
                        },
                    ),
                )
            ]
        ))

    model_instance = genai.GenerativeModel(
        model_name=request.model_id,
        system_instruction=request.system_prompt,
        tools=tool_defs if tool_defs else None,
    )

    contents = _convert_messages_to_gemini(request.messages)
    gen_config: Dict[str, Any] = {}
    if request.max_tokens:
        gen_config["max_output_tokens"] = request.max_tokens
    if request.temperature is not None:
        gen_config["temperature"] = request.temperature

    async def _generate() -> AsyncIterable[AgentModelEvent]:
        try:
            response = await model_instance.generate_content_async(
                contents=contents,
                generation_config=gen_config if gen_config else None,
                stream=True,
            )
            tool_index = 0
            async for chunk in response:
                for part in chunk.parts:
                    if hasattr(part, "text") and part.text:
                        yield {"type": "text-delta", "text": part.text}
                    elif hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        call_id = f"gemini_tool_{tool_index}"
                        tool_index += 1
                        args = dict(fc.args) if fc.args else {}
                        yield {
                            "type": "tool-call-delta",
                            "index": tool_index - 1,
                            "toolCallId": call_id,
                            "toolName": fc.name,
                            "input": args,
                        }

            # Usage
            try:
                usage = response.usage_metadata
                if usage:
                    yield {
                        "type": "usage",
                        "usage": {
                            "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                            "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
                        },
                    }
            except Exception:
                pass

            yield {"type": "finish", "reason": "stop"}

        except Exception as e:
            yield {"type": "finish", "reason": "error", "error": str(e)}

    return _generate()
