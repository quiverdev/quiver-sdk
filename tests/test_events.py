"""
Tests for the agent event system.
"""

import asyncio
import pytest

from quiver_sdk import Agent, create_tool
from tests.test_agent import make_model, make_tool_model, make_stream


@pytest.mark.asyncio
async def test_run_started_event():
    """run-started event is emitted at the beginning."""
    events = []
    agent = Agent(model=make_model(), on_event=events.append)
    await agent.run("Hello")
    types = [e["type"] for e in events]
    assert "run-started" in types


@pytest.mark.asyncio
async def test_turn_started_event():
    """turn-started event is emitted for each iteration."""
    events = []
    agent = Agent(model=make_model(), on_event=events.append)
    await agent.run("Hello")
    turns = [e for e in events if e["type"] == "turn-started"]
    assert len(turns) >= 1
    assert "iteration" in turns[0]


@pytest.mark.asyncio
async def test_assistant_text_delta_events():
    """assistant-text-delta events are emitted during streaming."""
    from unittest.mock import MagicMock

    deltas = []

    model = MagicMock()
    model.stream = MagicMock(return_value=make_stream(
        {"type": "text-delta", "text": "A"},
        {"type": "text-delta", "text": "B"},
        {"type": "text-delta", "text": "C"},
        {"type": "finish", "reason": "stop"},
    ))

    agent = Agent(model=model)
    agent.subscribe(lambda e: deltas.append(e) if e["type"] == "assistant-text-delta" else None)
    await agent.run("Test")

    assert len(deltas) == 3
    texts = [d["text"] for d in deltas]
    assert texts == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_assistant_reasoning_delta_events():
    """assistant-reasoning-delta events emitted during thinking."""
    from unittest.mock import MagicMock

    reasoning_events = []
    model = MagicMock()
    model.stream = MagicMock(return_value=make_stream(
        {"type": "reasoning-delta", "text": "Let me think...", "redacted": False},
        {"type": "text-delta", "text": "Answer"},
        {"type": "finish", "reason": "stop"},
    ))

    agent = Agent(model=model)
    agent.subscribe(
        lambda e: reasoning_events.append(e) if e["type"] == "assistant-reasoning-delta" else None
    )
    await agent.run("Think about this")

    assert len(reasoning_events) == 1
    assert reasoning_events[0]["text"] == "Let me think..."
    assert "accumulatedText" in reasoning_events[0]


@pytest.mark.asyncio
async def test_tool_started_and_finished_events():
    """tool-started and tool-finished events emitted around tool execution."""
    tool_events = []

    tool = create_tool(
        name="test_tool",
        description="Test",
        input_schema={},
        execute=lambda i, c: {"ok": True},
    )

    model = make_tool_model("test_tool", {})
    agent = Agent(model=model, tools=[tool])
    agent.subscribe(lambda e: tool_events.append(e) if e["type"] in ("tool-started", "tool-finished") else None)
    await agent.run("Use test_tool")

    types = [e["type"] for e in tool_events]
    assert "tool-started" in types
    assert "tool-finished" in types

    started = next(e for e in tool_events if e["type"] == "tool-started")
    assert started["toolCall"]["toolName"] == "test_tool"


@pytest.mark.asyncio
async def test_tool_updated_event():
    """tool-updated events are emitted from ctx.emit_update()."""
    update_events = []

    async def execute(inp, ctx):
        ctx.emit_update("Progress 50%")
        ctx.emit_update("Progress 100%")
        return {"done": True}

    tool = create_tool(name="t", description="d", input_schema={}, execute=execute)
    model = make_tool_model("t", {})
    agent = Agent(model=model, tools=[tool])
    agent.subscribe(lambda e: update_events.append(e) if e["type"] == "tool-updated" else None)
    await agent.run("Use t")

    assert len(update_events) == 2
    assert update_events[0]["update"] == "Progress 50%"
    assert update_events[1]["update"] == "Progress 100%"


@pytest.mark.asyncio
async def test_usage_updated_event():
    """usage-updated events contain usage data."""
    from unittest.mock import MagicMock

    usage_events = []
    model = MagicMock()
    model.stream = MagicMock(return_value=make_stream(
        {"type": "text-delta", "text": "Hi"},
        {"type": "usage", "usage": {"input_tokens": 50, "output_tokens": 10}},
        {"type": "finish", "reason": "stop"},
    ))

    agent = Agent(model=model)
    agent.subscribe(lambda e: usage_events.append(e) if e["type"] == "usage-updated" else None)
    await agent.run("Hello")

    assert len(usage_events) >= 1
    assert "usage" in usage_events[0]
    assert "input_tokens" in usage_events[0]["usage"]


@pytest.mark.asyncio
async def test_turn_finished_event():
    """turn-finished event emitted at end of each iteration."""
    events = []
    agent = Agent(model=make_model(), on_event=events.append)
    await agent.run("Hello")
    turn_finishes = [e for e in events if e["type"] == "turn-finished"]
    assert len(turn_finishes) >= 1
    assert "toolCallCount" in turn_finishes[0]


@pytest.mark.asyncio
async def test_message_added_events():
    """message-added events emitted when messages added."""
    events = []
    agent = Agent(model=make_model(), on_event=events.append)
    await agent.run("Hello")
    added = [e for e in events if e["type"] == "message-added"]
    assert len(added) >= 2  # user message + assistant message


@pytest.mark.asyncio
async def test_assistant_message_event():
    """assistant-message event emitted with complete message."""
    events = []
    agent = Agent(model=make_model(), on_event=events.append)
    await agent.run("Hello")
    ass_msgs = [e for e in events if e["type"] == "assistant-message"]
    assert len(ass_msgs) >= 1
    assert "message" in ass_msgs[0]
    assert "finishReason" in ass_msgs[0]


@pytest.mark.asyncio
async def test_run_finished_event():
    """run-finished event emitted with result."""
    events = []
    agent = Agent(model=make_model(), on_event=events.append)
    await agent.run("Hello")
    finished = [e for e in events if e["type"] == "run-finished"]
    assert len(finished) == 1
    assert "result" in finished[0]
    assert finished[0]["result"]["status"] == "completed"


@pytest.mark.asyncio
async def test_run_failed_event():
    """run-failed event emitted when agent fails."""
    from unittest.mock import MagicMock

    def raise_error(request):
        raise RuntimeError("Deliberate failure")

    model = MagicMock()
    model.stream = MagicMock(side_effect=raise_error)

    events = []
    agent = Agent(model=model, on_event=events.append)
    result = await agent.run("Hello")

    assert result.status == "failed"
    failed = [e for e in events if e["type"] == "run-failed"]
    assert len(failed) == 1
    assert "error" in failed[0]


@pytest.mark.asyncio
async def test_status_notice_event():
    """emit_status_notice() emits status-notice event."""
    notices = []
    model = make_model()
    agent = Agent(model=model)
    agent.subscribe(lambda e: notices.append(e) if e["type"] == "status-notice" else None)

    await agent.emit_status_notice("Working...", {"step": 1})

    assert len(notices) == 1
    assert notices[0]["text"] == "Working..."
    assert notices[0]["metadata"]["step"] == 1


@pytest.mark.asyncio
async def test_subscribe_returns_unsubscribe():
    """subscribe() returns a callable unsubscribe function."""
    events = []
    agent = Agent(model=make_model())
    unsub = agent.subscribe(events.append)
    assert callable(unsub)
    unsub()


@pytest.mark.asyncio
async def test_unsubscribe_stops_events():
    """After unsubscribing, listener receives no more events."""
    events = []
    model = make_model()
    agent = Agent(model=model)
    unsub = agent.subscribe(events.append)
    unsub()  # unsubscribe immediately

    await agent.run("Hello")
    assert len(events) == 0


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """Multiple listeners all receive events."""
    events1 = []
    events2 = []
    agent = Agent(model=make_model())
    agent.subscribe(events1.append)
    agent.subscribe(events2.append)
    await agent.run("Hello")

    assert len(events1) > 0
    assert len(events2) > 0
    assert len(events1) == len(events2)
