"""
Tests for hook system: before_run, after_run, before_model, after_model,
before_tool, after_tool — both dict and dataclass result forms.
"""

import asyncio
import pytest
from unittest.mock import MagicMock

from quiver_sdk import Agent, create_tool
from quiver_sdk.types import (
    AgentBeforeModelResult,
    AgentBeforeToolResult,
    AgentAfterToolResult,
    AgentToolResult,
    AgentStopControl,
)
from tests.test_agent import make_model, make_tool_model


# ---------------------------------------------------------------------------
# before_run hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_before_run_hook_called():
    """before_run hook is called before the agent loop."""
    called = []

    agent = Agent(
        model=make_model(),
        hooks={"before_run": lambda ctx: called.append(ctx)},
    )
    await agent.run("Hello")
    assert len(called) == 1
    assert "snapshot" in called[0]


@pytest.mark.asyncio
async def test_before_run_hook_stop_dict():
    """before_run hook returning {"stop": True} aborts the run."""
    agent = Agent(
        model=make_model(),
        hooks={"before_run": lambda ctx: {"stop": True, "reason": "blocked"}},
    )
    result = await agent.run("Hello")
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_before_run_hook_stop_dataclass():
    """before_run hook returning AgentStopControl(stop=True) aborts the run."""
    agent = Agent(
        model=make_model(),
        hooks={"before_run": lambda ctx: AgentStopControl(stop=True, reason="blocked")},
    )
    result = await agent.run("Hello")
    assert result.status == "aborted"


# ---------------------------------------------------------------------------
# after_run hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_after_run_hook_called():
    """after_run hook is called after the run completes."""
    results_seen = []

    def after_run(ctx):
        results_seen.append(ctx.get("result"))

    agent = Agent(model=make_model(), hooks={"after_run": after_run})
    result = await agent.run("Hello")

    assert len(results_seen) == 1
    assert results_seen[0].status == "completed"


@pytest.mark.asyncio
async def test_after_run_hook_async():
    """after_run hook can be async."""
    called = []

    async def after_run(ctx):
        await asyncio.sleep(0)
        called.append(True)

    agent = Agent(model=make_model(), hooks={"after_run": after_run})
    await agent.run("Hello")
    assert called == [True]


# ---------------------------------------------------------------------------
# before_model hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_before_model_hook_called():
    """before_model hook is called before each LLM call."""
    calls = []
    agent = Agent(
        model=make_model(),
        hooks={"before_model": lambda ctx: calls.append(ctx)},
    )
    await agent.run("Hello")
    assert len(calls) >= 1
    assert "request" in calls[0]


@pytest.mark.asyncio
async def test_before_model_stop_dict():
    """before_model returning {"stop": True} aborts the run."""
    agent = Agent(
        model=make_model(),
        hooks={"before_model": lambda ctx: {"stop": True}},
    )
    result = await agent.run("Hello")
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_before_model_stop_dataclass():
    """before_model returning AgentBeforeModelResult(stop=True) aborts."""
    agent = Agent(
        model=make_model(),
        hooks={"before_model": lambda ctx: AgentBeforeModelResult(stop=True, reason="blocked")},
    )
    result = await agent.run("Hello")
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_before_model_mutate_options_dict():
    """before_model hook can mutate model options via dict."""
    received_options = []

    original_stream = None

    def stream_fn(request):
        received_options.append(request.options)
        return make_model().stream(request)

    model = MagicMock()
    model.stream = MagicMock(side_effect=stream_fn)

    agent = Agent(
        model=model,
        hooks={
            "before_model": lambda ctx: {"options": {"temperature": 0.1}}
        },
    )
    await agent.run("Hello")
    assert received_options[0] is not None
    assert received_options[0].get("temperature") == 0.1


@pytest.mark.asyncio
async def test_before_model_mutate_options_dataclass():
    """before_model hook can mutate model options via dataclass."""
    received_options = []

    def stream_fn(request):
        received_options.append(request.options)
        return make_model().stream(request)

    model = MagicMock()
    model.stream = MagicMock(side_effect=stream_fn)

    agent = Agent(
        model=model,
        hooks={
            "before_model": lambda ctx: AgentBeforeModelResult(options={"temperature": 0.5})
        },
    )
    await agent.run("Hello")
    assert received_options[0] is not None
    assert received_options[0].get("temperature") == 0.5


# ---------------------------------------------------------------------------
# before_tool hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_before_tool_hook_called():
    """before_tool hook is called before each tool execution."""
    calls = []
    tool = create_tool(
        name="t",
        description="d",
        input_schema={},
        execute=lambda i, c: {"ok": True},
    )
    agent = Agent(
        model=make_tool_model("t", {}),
        tools=[tool],
        hooks={"before_tool": lambda ctx: calls.append(ctx)},
    )
    await agent.run("Use t")
    assert len(calls) >= 1
    assert calls[0]["toolCall"]["toolName"] == "t"


@pytest.mark.asyncio
async def test_before_tool_skip_dict():
    """before_tool returning {"skip": True} skips the tool."""
    executed = []
    tool = create_tool(
        name="t",
        description="d",
        input_schema={},
        execute=lambda i, c: executed.append(True) or {"ok": True},
    )
    agent = Agent(
        model=make_tool_model("t", {}),
        tools=[tool],
        hooks={"before_tool": lambda ctx: {"skip": True}},
    )
    await agent.run("Use t")
    assert len(executed) == 0


@pytest.mark.asyncio
async def test_before_tool_skip_dataclass():
    """before_tool returning AgentBeforeToolResult(skip=True) skips the tool."""
    executed = []
    tool = create_tool(
        name="t",
        description="d",
        input_schema={},
        execute=lambda i, c: executed.append(True) or {"ok": True},
    )
    agent = Agent(
        model=make_tool_model("t", {}),
        tools=[tool],
        hooks={"before_tool": lambda ctx: AgentBeforeToolResult(skip=True)},
    )
    await agent.run("Use t")
    assert len(executed) == 0


@pytest.mark.asyncio
async def test_before_tool_modify_input_dict():
    """before_tool returning {"input": ...} modifies the tool input."""
    received = []

    async def execute(inp, ctx):
        received.append(inp)
        return {"ok": True}

    tool = create_tool(
        name="t",
        description="d",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        execute=execute,
    )
    agent = Agent(
        model=make_tool_model("t", {"x": "original"}),
        tools=[tool],
        hooks={"before_tool": lambda ctx: {"input": {"x": "modified"}}},
    )
    await agent.run("Use t")
    assert len(received) >= 1
    assert received[0]["x"] == "modified"


@pytest.mark.asyncio
async def test_before_tool_modify_input_dataclass():
    """before_tool returning AgentBeforeToolResult(input=...) modifies input."""
    received = []

    async def execute(inp, ctx):
        received.append(inp)
        return {"ok": True}

    tool = create_tool(
        name="t",
        description="d",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        execute=execute,
    )
    agent = Agent(
        model=make_tool_model("t", {"x": "original"}),
        tools=[tool],
        hooks={
            "before_tool": lambda ctx: AgentBeforeToolResult(input={"x": "from-dataclass"})
        },
    )
    await agent.run("Use t")
    assert len(received) >= 1
    assert received[0]["x"] == "from-dataclass"


@pytest.mark.asyncio
async def test_before_tool_stop_dataclass():
    """before_tool returning AgentBeforeToolResult(stop=True) aborts the run."""
    executed = []
    tool = create_tool(
        name="t",
        description="d",
        input_schema={},
        execute=lambda i, c: executed.append(True) or {"ok": True},
    )
    agent = Agent(
        model=make_tool_model("t", {}),
        tools=[tool],
        hooks={
            "before_tool": lambda ctx: AgentBeforeToolResult(stop=True, reason="blocked by test")
        },
    )
    result = await agent.run("Use t")
    assert result.status == "aborted"
    assert len(executed) == 0


# ---------------------------------------------------------------------------
# after_tool hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_after_tool_hook_called():
    """after_tool hook is called after tool execution."""
    calls = []
    tool = create_tool(
        name="t",
        description="d",
        input_schema={},
        execute=lambda i, c: {"ok": True},
    )
    agent = Agent(
        model=make_tool_model("t", {}),
        tools=[tool],
        hooks={"after_tool": lambda ctx: calls.append(ctx)},
    )
    await agent.run("Use t")
    assert len(calls) >= 1
    assert "durationMs" in calls[0]
    assert "result" in calls[0]


@pytest.mark.asyncio
async def test_after_tool_modify_result_dict():
    """after_tool can replace the tool result via dict."""
    seen_results = []

    def after_tool(ctx):
        return {"result": {"output": "overridden", "isError": False}}

    tool = create_tool(
        name="t",
        description="d",
        input_schema={},
        execute=lambda i, c: {"original": True},
    )
    agent = Agent(
        model=make_tool_model("t", {}),
        tools=[tool],
        hooks={"after_tool": after_tool},
    )
    result = await agent.run("Use t")
    assert result.status in ("completed", "aborted", "failed")


@pytest.mark.asyncio
async def test_after_tool_modify_result_dataclass():
    """after_tool can replace the tool result via AgentAfterToolResult."""

    def after_tool(ctx):
        return AgentAfterToolResult(
            result=AgentToolResult(output="overridden_by_dataclass", is_error=False)
        )

    tool = create_tool(
        name="t",
        description="d",
        input_schema={},
        execute=lambda i, c: {"original": True},
    )
    agent = Agent(
        model=make_tool_model("t", {}),
        tools=[tool],
        hooks={"after_tool": after_tool},
    )
    result = await agent.run("Use t")
    assert result.status in ("completed", "aborted", "failed")


@pytest.mark.asyncio
async def test_after_tool_stop_dataclass():
    """after_tool returning AgentAfterToolResult(stop=True) aborts the run."""
    tool = create_tool(
        name="t",
        description="d",
        input_schema={},
        execute=lambda i, c: {"ok": True},
    )
    agent = Agent(
        model=make_tool_model("t", {}),
        tools=[tool],
        hooks={
            "after_tool": lambda ctx: AgentAfterToolResult(stop=True, reason="post-tool stop")
        },
    )
    result = await agent.run("Use t")
    assert result.status == "aborted"
