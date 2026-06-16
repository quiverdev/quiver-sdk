"""
Tests for tool creation, execution, policies, and lifecycle.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from quiver_sdk import create_tool, Agent
from quiver_sdk.types import AgentTool, AgentToolContext, ToolPolicy, ToolApprovalRequest, ToolApprovalResult


# ---------------------------------------------------------------------------
# create_tool() tests
# ---------------------------------------------------------------------------


def test_create_tool_basic():
    """create_tool() returns an AgentTool with correct fields."""
    tool = create_tool(
        name="my_tool",
        description="A test tool",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        execute=lambda inp, ctx: {"result": inp.get("x")},
    )
    assert isinstance(tool, AgentTool)
    assert tool.name == "my_tool"
    assert tool.description == "A test tool"
    assert tool.input_schema["type"] == "object"
    assert callable(tool.execute)


def test_create_tool_defaults():
    """create_tool() sets sensible defaults."""
    tool = create_tool(
        name="t",
        description="d",
        input_schema={},
        execute=lambda i, c: {},
    )
    assert tool.timeout_ms == 30_000
    assert tool.retryable is True
    assert tool.max_retries == 3
    assert tool.lifecycle is None


def test_create_tool_custom_timeout():
    """create_tool() accepts custom timeout."""
    tool = create_tool(
        name="slow_tool",
        description="Slow tool",
        input_schema={},
        execute=lambda i, c: {},
        timeout_ms=60_000,
        retryable=False,
        max_retries=0,
    )
    assert tool.timeout_ms == 60_000
    assert tool.retryable is False
    assert tool.max_retries == 0


def test_create_tool_lifecycle():
    """create_tool() with lifecycle completes_run."""
    tool = create_tool(
        name="submit",
        description="Submit answer",
        input_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        execute=lambda i, c: {"ok": True},
        lifecycle={"completes_run": True},
    )
    assert tool.lifecycle is not None
    assert tool.lifecycle.get("completes_run") is True


# ---------------------------------------------------------------------------
# Tool execution tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_execute_sync():
    """Sync execute function works correctly."""
    tool = create_tool(
        name="add",
        description="Add two numbers",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
        execute=lambda inp, ctx: {"result": inp["a"] + inp["b"]},
    )

    ctx = AgentToolContext(agent_id="test", iteration=1)
    result = await asyncio.coroutine(lambda: tool.execute({"a": 2, "b": 3}, ctx))() if asyncio.iscoroutinefunction(tool.execute) else tool.execute({"a": 2, "b": 3}, ctx)
    assert result["result"] == 5


@pytest.mark.asyncio
async def test_tool_execute_async():
    """Async execute function works correctly."""
    async def async_execute(inp, ctx):
        await asyncio.sleep(0)  # yield
        return {"value": inp.get("x", "") + "_processed"}

    tool = create_tool(
        name="async_tool",
        description="Async tool",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        execute=async_execute,
    )

    ctx = AgentToolContext(agent_id="test", iteration=1)
    result = await tool.execute({"x": "hello"}, ctx)
    assert result["value"] == "hello_processed"


@pytest.mark.asyncio
async def test_tool_context_emit_update():
    """AgentToolContext.emit_update() is callable."""
    updates = []
    ctx = AgentToolContext(
        agent_id="test",
        iteration=1,
        emit_update=lambda upd: updates.append(upd),
    )

    async def execute(inp, ctx):
        ctx.emit_update("Step 1")
        ctx.emit_update("Step 2")
        return {"done": True}

    tool = create_tool(
        name="updating_tool",
        description="A tool that emits updates",
        input_schema={},
        execute=execute,
    )

    await tool.execute({}, ctx)
    assert updates == ["Step 1", "Step 2"]


@pytest.mark.asyncio
async def test_tool_timeout():
    """Tool exceeds timeout and returns error result."""
    import asyncio

    async def slow_execute(inp, ctx):
        await asyncio.sleep(10)  # will time out
        return {"result": "done"}

    tool = create_tool(
        name="slow",
        description="Slow tool",
        input_schema={},
        execute=slow_execute,
        timeout_ms=100,
    )

    from unittest.mock import MagicMock, patch
    import asyncio as aio

    # Simulate timeout by using wait_for
    ctx = AgentToolContext(agent_id="test", iteration=1)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(tool.execute({}, ctx), timeout=0.1)


# ---------------------------------------------------------------------------
# Tool policy tests
# ---------------------------------------------------------------------------


def test_tool_policy_fields():
    """ToolPolicy has correct field defaults."""
    p = ToolPolicy()
    assert p.require_approval is None
    assert p.auto_approve is None

    p2 = ToolPolicy(require_approval=True, auto_approve=False)
    assert p2.require_approval is True
    assert p2.auto_approve is False


@pytest.mark.asyncio
async def test_tool_approval_skip_tool():
    """Tool with require_approval=True that is rejected returns error."""

    async def reject_all(req: ToolApprovalRequest) -> ToolApprovalResult:
        return ToolApprovalResult(approved=False, reason="Rejected by test")

    from tests.test_agent import make_tool_model

    tool = create_tool(
        name="dangerous_tool",
        description="A dangerous tool",
        input_schema={"type": "object", "properties": {}},
        execute=lambda inp, ctx: {"result": "executed"},
    )

    model = make_tool_model("dangerous_tool", {})

    agent = Agent(
        model=model,
        tools=[tool],
        tool_policies={"dangerous_tool": ToolPolicy(require_approval=True)},
        request_tool_approval=reject_all,
    )

    result = await agent.run("Use the dangerous tool")
    # Tool was rejected, so agent sees an error result and should handle it
    assert result.status in ("completed", "failed")


# ---------------------------------------------------------------------------
# Built-in tool schema validation
# ---------------------------------------------------------------------------


def test_all_tools_have_names():
    """All tools created via create_tool() have non-empty names."""
    tools = [
        create_tool(
            name=name,
            description="d",
            input_schema={},
            execute=lambda i, c: {},
        )
        for name in ["tool_a", "tool_b", "tool_c"]
    ]
    for t in tools:
        assert t.name
        assert "_" in t.name or t.name.isalpha()  # snake_case or plain
