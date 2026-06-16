"""
Tool creation helper for the Quiver SDK.
Mirrors createTool from @quiver/shared.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from quiver_sdk.types import AgentTool, AgentToolContext, AgentToolResult


def _normalize_tool_input_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a JSON schema for use as a tool input schema.
    Ensures the schema has a top-level type: "object" where needed.
    """
    schema = {k: v for k, v in schema.items() if k != "$schema"}

    if "type" in schema:
        return schema

    if any(k in schema for k in ("properties", "required", "additionalProperties")):
        return {"type": "object", **schema}

    for key in ("oneOf", "anyOf", "allOf"):
        branches = schema.get(key)
        if not isinstance(branches, list) or not branches:
            continue

        if key == "allOf":
            has_object = any(
                isinstance(b, dict) and b.get("type") == "object" for b in branches
            )
            if has_object:
                return {"type": "object", **schema}
            raise ValueError(
                f'Tool inputSchema must describe an object at the top level, but '
                f'the schema has a top-level "allOf" with no branch that asserts '
                f'type: "object".'
            )

        all_objects = all(
            isinstance(b, dict) and b.get("type") == "object" for b in branches
        )
        if all_objects:
            return {"type": "object", **schema}
        raise ValueError(
            f'Tool inputSchema must describe an object at the top level, but '
            f'the schema has a top-level "{key}" whose branches include non-object types.'
        )

    return schema


def create_tool(
    name: str,
    description: str,
    input_schema: Dict[str, Any],
    execute: Callable[..., Any],
    lifecycle: Optional[Dict[str, Any]] = None,
    timeout_ms: int = 30_000,
    retryable: bool = True,
    max_retries: int = 3,
) -> AgentTool:
    """
    Create an AgentTool.

    Args:
        name: Tool name (snake_case, e.g. "deploy_app")
        description: Description the model reads to decide when to call the tool
        input_schema: JSON Schema dict describing the input object
        execute: Async function called with (input, context) -> output
        lifecycle: Optional lifecycle config, e.g. {"completes_run": True}
        timeout_ms: Execution timeout in milliseconds (default 30s)
        retryable: Whether failed calls can be retried (default True)
        max_retries: Maximum retry count (default 3)

    Returns:
        AgentTool instance

    Example::

        tool = create_tool(
            name="deploy",
            description="Deploy the app to staging or production.",
            input_schema={
                "type": "object",
                "properties": {
                    "environment": {"type": "string", "enum": ["staging", "production"]},
                },
                "required": ["environment"],
            },
            execute=deploy_app,
        )
    """
    normalized_schema = _normalize_tool_input_schema(input_schema)
    return AgentTool(
        name=name,
        description=description,
        input_schema=normalized_schema,
        execute=execute,
        lifecycle=lifecycle,
        timeout_ms=timeout_ms,
        retryable=retryable,
        max_retries=max_retries,
    )
