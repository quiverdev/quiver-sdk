"""
Tests for AgentRuntime / Agent core functionality.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import AsyncIterable, Dict, Any

from quiver_sdk import Agent
from quiver_sdk.agent import AgentRuntime
from quiver_sdk.types import (
    AgentMessage,
    AgentModelRequest,
    AgentRunResult,
    AgentRuntimeStateSnapshot,
    AgentStopControl,
    AgentUsage,
    AgentBeforeModelResult,
    AgentBeforeToolResult,
    AgentAfterToolResult,
    AgentToolResult,
)
from quiver_sdk import create_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_stream(*events: Dict[str, Any]) -> AsyncIterable[Dict[str, Any]]:
    """Create an async generator yielding the given events."""

    async def _gen():
        for event in events:
            yield event

    return _gen()


def make_model(events=None):
    """Create a mock AgentModel that yields the given events."""
    if events is None:
        events = [
            {"type": "text-delta", "text": "Hello, world!"},
            {"type": "finish", "reason": "stop"},
        ]

    model = MagicMock()
    model.stream = MagicMock(return_value=make_stream(*events))
    return model


def make_tool_model(tool_name: str, tool_input: dict, tool_id: str = "tc-001"):
    """Model that returns a single tool call, then a final text."""
    events_turn1 = [
        {
            "type": "tool-call-delta",
            "toolCallId": tool_id,
            "toolName": tool_name,
            "index": 0,
        },
        {
            "type": "tool-call-delta",
            "toolCallId": tool_id,
            "toolName": tool_name,
            "input": tool_input,
        },
        {"type": "finish", "reason": "tool-calls"},
    ]
    events_turn2 = [
        {"type": "text-delta", "text": "Task complete!"},
        {"type": "finish", "reason": "stop"},
    ]

    call_count = 0

    def stream_fn(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return make_stream(*events_turn1)
        return make_stream(*events_turn2)

    model = MagicMock()
    model.stream = MagicMock(side_effect=stream_fn)
    return model


# ---------------------------------------------------------------------------
# Basic run tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_run_simple_text():
    """Agent runs and returns text output."""
    model = make_model([
        {"type": "text-delta", "text": "Paris"},
        {"type": "finish", "reason": "stop"},
    ])

    agent = Agent(model=model, system_prompt="You are a helper.")
    result = await agent.run("What is the capital of France?")

    assert result.status == "completed"
    assert "Paris" in result.output_text
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_agent_run_returns_agent_run_result():
    """run() returns an AgentRunResult dataclass."""
    model = make_model()
    agent = Agent(model=model)
    result = await agent.run("Hello")

    assert isinstance(result, AgentRunResult)
    assert result.agent_id
    assert result.run_id
    assert isinstance(result.messages, list)
    assert isinstance(result.usage, AgentUsage)


@pytest.mark.asyncio
async def test_agent_run_accumulates_messages():
    """Messages are added to history after run()."""
    model = make_model()
    agent = Agent(model=model)
    result = await agent.run("Hello")

    assert len(result.messages) >= 2  # user + assistant
    roles = [m.role for m in result.messages]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_agent_has_run_property():
    """has_run is False before run(), True after."""
    model = make_model()
    agent = Agent(model=model)

    assert agent.has_run is False
    await agent.run("Hello")
    assert agent.has_run is True


@pytest.mark.asyncio
async def test_agent_continue_after_run():
    """continue_() continues the conversation."""
    model = make_model([
        {"type": "text-delta", "text": "First response"},
        {"type": "finish", "reason": "stop"},
    ])
    agent = Agent(model=model)
    r1 = await agent.run("First message")
    assert r1.status == "completed"

    model.stream.return_value = make_stream(
        {"type": "text-delta", "text": "Second response"},
        {"type": "finish", "reason": "stop"},
    )

    r2 = await agent.continue_("Second message")
    assert r2.status == "completed"
    assert "Second response" in r2.output_text


@pytest.mark.asyncio
async def test_agent_run_with_tool_call():
    """Agent executes a tool call and continues."""
    executed = []

    def my_execute(inp, ctx):
        executed.append(inp)
        return {"result": "tool_output"}

    tool = create_tool(
        name="my_tool",
        description="A test tool.",
        input_schema={
            "type": "object",
            "properties": {"x": {"type": "string"}},
        },
        execute=my_execute,
    )

    model = make_tool_model("my_tool", {"x": "hello"})
    agent = Agent(model=model, tools=[tool])
    result = await agent.run("Use the tool")

    assert result.status == "completed"
    assert len(executed) == 1
    assert executed[0]["x"] == "hello"


@pytest.mark.asyncio
async def test_agent_abort():
    """abort() stops the agent when called during a run via hook."""
    model = make_model([
        {"type": "text-delta", "text": "Starting..."},
        {"type": "finish", "reason": "stop"},
    ])
    agent = Agent(
        model=model,
        hooks={"before_model": lambda ctx: {"stop": True, "reason": "aborted by hook"}},
    )
    result = await agent.run("Do something")
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_agent_max_iterations():
    """Agent stops after max_iterations."""
    call_count = 0

    def stream_fn(request):
        nonlocal call_count
        call_count += 1
        return make_stream(
            {"type": "tool-call-delta", "toolCallId": f"tc-{call_count}", "toolName": "loop_tool", "index": 0},
            {"type": "tool-call-delta", "toolCallId": f"tc-{call_count}", "toolName": "loop_tool", "input": {}},
            {"type": "finish", "reason": "tool-calls"},
        )

    loop_tool = create_tool(
        name="loop_tool",
        description="A looping tool.",
        input_schema={"type": "object", "properties": {}},
        execute=lambda inp, ctx: {"ok": True},
    )

    model = MagicMock()
    model.stream = MagicMock(side_effect=stream_fn)

    agent = Agent(model=model, tools=[loop_tool], max_iterations=3)
    result = await agent.run("Loop forever")

    # Should fail after max_iterations
    assert result.status == "failed"
    assert result.iterations == 3


@pytest.mark.asyncio
async def test_agent_snapshot():
    """snapshot() returns current state."""
    model = make_model()
    agent = Agent(model=model)

    snap_before = agent.snapshot()
    assert snap_before.status == "idle"
    assert snap_before.iteration == 0

    await agent.run("Hello")

    snap_after = agent.snapshot()
    assert snap_after.status == "completed"
    assert snap_after.iteration == 1
    assert isinstance(snap_after, AgentRuntimeStateSnapshot)


@pytest.mark.asyncio
async def test_agent_restore():
    """restore() replaces message history."""
    model = make_model()
    agent = Agent(model=model)

    from quiver_sdk.utils import create_uid
    import time

    restored_messages = [
        AgentMessage(
            id=create_uid("msg"),
            role="user",
            content=[{"type": "text", "text": "Old message"}],
            created_at=int(time.time() * 1000),
        ),
        AgentMessage(
            id=create_uid("msg"),
            role="assistant",
            content=[{"type": "text", "text": "Old response"}],
            created_at=int(time.time() * 1000),
        ),
    ]

    agent.restore(restored_messages)
    snap = agent.snapshot()
    assert len(snap.messages) == 2
    assert snap.messages[0].role == "user"
    assert snap.messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_agent_subscribe_events():
    """subscribe() receives events during run."""
    events_received = []
    model = make_model([
        {"type": "text-delta", "text": "Hello"},
        {"type": "finish", "reason": "stop"},
    ])

    agent = Agent(model=model)
    unsubscribe = agent.subscribe(lambda e: events_received.append(e))
    await agent.run("Test")
    unsubscribe()

    event_types = [e["type"] for e in events_received]
    assert "run-started" in event_types
    assert "assistant-text-delta" in event_types
    assert "run-finished" in event_types


@pytest.mark.asyncio
async def test_agent_text_delta_events():
    """assistant-text-delta events have correct fields."""
    deltas = []
    model = make_model([
        {"type": "text-delta", "text": "Hello"},
        {"type": "text-delta", "text": " world"},
        {"type": "finish", "reason": "stop"},
    ])

    agent = Agent(model=model)
    agent.subscribe(lambda e: deltas.append(e) if e["type"] == "assistant-text-delta" else None)
    await agent.run("Test")

    assert len(deltas) == 2
    assert deltas[0]["text"] == "Hello"
    assert deltas[0]["accumulatedText"] == "Hello"
    assert deltas[1]["text"] == " world"
    assert deltas[1]["accumulatedText"] == "Hello world"


@pytest.mark.asyncio
async def test_completion_tool_ends_run():
    """A lifecycle=completes_run tool ends the loop on success."""
    finish_tool = create_tool(
        name="finish",
        description="Finish the run.",
        input_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
        lifecycle={"completes_run": True},
        execute=lambda inp, ctx: {"answer": inp.get("answer", "")},
    )

    model = make_tool_model("finish", {"answer": "42"})
    agent = Agent(model=model, tools=[finish_tool])
    result = await agent.run("Give me the answer")

    assert result.status == "completed"


@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    """Calling a tool not in the registry returns an error result."""
    model = make_tool_model("nonexistent_tool", {})
    agent = Agent(model=model)
    result = await agent.run("Call the tool")

    # Agent should still complete (or fail gracefully)
    assert result.status in ("completed", "failed", "aborted")


@pytest.mark.asyncio
async def test_emit_status_notice():
    """emit_status_notice() emits a status-notice event."""
    notices = []
    model = make_model()
    agent = Agent(model=model)
    agent.subscribe(lambda e: notices.append(e) if e["type"] == "status-notice" else None)

    await agent.emit_status_notice("Working...", {"detail": "step 1"})

    assert len(notices) == 1
    assert notices[0]["text"] == "Working..."
    assert notices[0]["metadata"]["detail"] == "step 1"


@pytest.mark.asyncio
async def test_usage_tracked():
    """Token usage is tracked from usage events."""
    model = make_model([
        {"type": "text-delta", "text": "Hello"},
        {"type": "usage", "usage": {"input_tokens": 100, "output_tokens": 50}},
        {"type": "finish", "reason": "stop"},
    ])

    agent = Agent(model=model)
    result = await agent.run("Test")

    assert result.usage.input_tokens >= 100
    assert result.usage.output_tokens >= 50


@pytest.mark.asyncio
async def test_on_event_constructor_param():
    """on_event= constructor param receives events."""
    events = []
    model = make_model()
    agent = Agent(model=model, on_event=lambda e: events.append(e))
    await agent.run("Hello")

    assert any(e["type"] == "run-finished" for e in events)
