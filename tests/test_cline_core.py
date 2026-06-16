"""
Tests for QuiverCore session management, persistence, events, and hub.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from quiver_sdk import QuiverCore, create_tool
from quiver_sdk.types import AgentMessage, AgentUsage, SessionRecord, StartSessionResult
from tests.test_agent import make_model, make_stream


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_mock_model(events=None):
    """Create a mock model for QuiverCore sessions."""
    if events is None:
        events = [
            {"type": "text-delta", "text": "Done"},
            {"type": "finish", "reason": "stop"},
        ]
    model = MagicMock()
    model.stream = MagicMock(return_value=make_stream(*events))
    return model


@pytest.fixture
def mock_gateway():
    """Patch the gateway so no real API calls are made."""
    with patch("quiver_sdk.core.quiver_core.create_gateway") as mock_create:
        gw = MagicMock()
        model = make_mock_model()
        gw.create_agent_model.return_value = model
        gw.configure_provider = MagicMock()
        mock_create.return_value = gw
        yield gw, model


# ---------------------------------------------------------------------------
# QuiverCore.create() tests
# ---------------------------------------------------------------------------


def test_create_returns_quiver_core(mock_gateway):
    """QuiverCore.create() returns a QuiverCore instance."""
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    )
    assert isinstance(core, QuiverCore)


def test_create_in_memory_db_by_default(mock_gateway):
    """Default db_path is :memory:."""
    core = QuiverCore.create(provider_id="anthropic", model_id="claude-sonnet-4-6")
    assert core._config.db_path == ":memory:"


# ---------------------------------------------------------------------------
# Session lifecycle tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_session_result(mock_gateway):
    """start() returns StartSessionResult with session_id and agent_id."""
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    )
    result = await core.start()
    assert isinstance(result, StartSessionResult)
    assert result.session_id
    assert result.agent_id
    await core.dispose()


@pytest.mark.asyncio
async def test_send_returns_run_result(mock_gateway):
    """send() returns AgentRunResult."""
    gw, model = mock_gateway
    model.stream = MagicMock(return_value=make_stream(
        {"type": "text-delta", "text": "Response"},
        {"type": "finish", "reason": "stop"},
    ))

    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
        enable_tools=False,
    )
    session = await core.start()
    result = await core.send(session.session_id, "Hello")

    assert result.status == "completed"
    assert "Response" in result.output_text
    await core.dispose()


@pytest.mark.asyncio
async def test_send_unknown_session_raises(mock_gateway):
    """send() on unknown session raises SessionNotFoundError."""
    from quiver_sdk.exceptions import SessionNotFoundError

    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    )
    with pytest.raises(SessionNotFoundError):
        await core.send("nonexistent-session-id", "Hello")
    await core.dispose()


@pytest.mark.asyncio
async def test_multiple_sessions_independent(mock_gateway):
    """Multiple sessions are independent."""
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
        enable_tools=False,
    )

    s1 = await core.start()
    s2 = await core.start()

    assert s1.session_id != s2.session_id
    assert s1.agent_id != s2.agent_id
    await core.dispose()


# ---------------------------------------------------------------------------
# Session query tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_returns_record(mock_gateway):
    """get() returns SessionRecord for existing session."""
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    )
    session = await core.start()
    record = await core.get(session.session_id)

    assert record is not None
    assert isinstance(record, SessionRecord)
    assert record.session_id == session.session_id
    await core.dispose()


@pytest.mark.asyncio
async def test_get_unknown_session_returns_none(mock_gateway):
    """get() returns None for non-existent session."""
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    )
    record = await core.get("does-not-exist")
    assert record is None
    await core.dispose()


@pytest.mark.asyncio
async def test_list_sessions(mock_gateway):
    """list() returns created sessions."""
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    )
    s1 = await core.start()
    s2 = await core.start()

    sessions = await core.list()
    ids = [s.session_id for s in sessions]
    assert s1.session_id in ids
    assert s2.session_id in ids
    await core.dispose()


@pytest.mark.asyncio
async def test_delete_session(mock_gateway):
    """delete() removes session from store."""
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    )
    session = await core.start()
    await core.delete(session.session_id)

    record = await core.get(session.session_id)
    assert record is None
    await core.dispose()


@pytest.mark.asyncio
async def test_read_messages_after_send(mock_gateway):
    """read_messages() returns persisted messages after send."""
    gw, model = mock_gateway
    model.stream = MagicMock(return_value=make_stream(
        {"type": "text-delta", "text": "Response"},
        {"type": "finish", "reason": "stop"},
    ))

    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
        enable_tools=False,
    )
    session = await core.start()
    await core.send(session.session_id, "Hello")

    messages = await core.read_messages(session.session_id)
    assert len(messages) >= 2
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles
    await core.dispose()


@pytest.mark.asyncio
async def test_get_accumulated_usage(mock_gateway):
    """get_accumulated_usage() returns AgentUsage."""
    gw, model = mock_gateway
    model.stream = MagicMock(return_value=make_stream(
        {"type": "text-delta", "text": "Hi"},
        {"type": "usage", "usage": {"input_tokens": 10, "output_tokens": 5}},
        {"type": "finish", "reason": "stop"},
    ))

    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
        enable_tools=False,
    )
    session = await core.start()
    await core.send(session.session_id, "Hello")

    usage = await core.get_accumulated_usage(session.session_id)
    assert isinstance(usage, AgentUsage)
    assert usage.input_tokens >= 0
    await core.dispose()


# ---------------------------------------------------------------------------
# Events tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_receives_events(mock_gateway):
    """core.subscribe() receives events during send()."""
    gw, model = mock_gateway
    model.stream = MagicMock(return_value=make_stream(
        {"type": "text-delta", "text": "Hi"},
        {"type": "finish", "reason": "stop"},
    ))

    events = []
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
        enable_tools=False,
    )
    session = await core.start()
    core.subscribe(session.session_id, events.append)
    await core.send(session.session_id, "Hello")

    types = [e["type"] for e in events]
    assert "run-started" in types or "assistant-text-delta" in types
    await core.dispose()


@pytest.mark.asyncio
async def test_subscribe_returns_unsubscribe(mock_gateway):
    """subscribe() returns a callable unsubscribe function."""
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    )
    session = await core.start()
    unsub = core.subscribe(session.session_id, lambda e: None)
    assert callable(unsub)
    unsub()
    await core.dispose()


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_context_manager(mock_gateway):
    """QuiverCore works as async context manager (auto-disposes)."""
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    ) as core:
        session = await core.start()
        assert session.session_id


@pytest.mark.asyncio
async def test_abort_session(mock_gateway):
    """abort() updates session status."""
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="test-key",
    )
    session = await core.start()
    await core.abort(session.session_id)
    record = await core.get(session.session_id)
    assert record is not None
    assert record.status == "aborted"
    await core.dispose()
