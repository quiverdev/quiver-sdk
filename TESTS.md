# Tests

Comprehensive test suite for `quiver-sdk` (Python).

---

## Overview

| File | Tests | What it covers |
|---|---|---|
| `tests/test_agent.py` | 18 | Agent run, continue, abort, snapshot, restore, tools, events, completion tools |
| `tests/test_tools.py` | 10 | create_tool(), execute sync/async, timeout, tool policies |
| `tests/test_hooks.py` | 16 | before_run, after_run, before_model, before_tool, after_tool — dict + dataclass forms |
| `tests/test_events.py` | 16 | All event types: run-started, text-delta, reasoning-delta, tool events, usage, run-finished |
| `tests/test_plugins.py` | 12 | Plugin setup, tool registration, hooks, multiple plugins, context fields |
| `tests/test_quiver_core.py` | 16 | QuiverCore sessions, queries, events, context manager, abort |

**Total: ~88 tests** — all use mocked models, no real API calls required.

---

## Setup

```bash
# Install dev dependencies
pip install "quiver-sdk[dev]"

# Or manually
pip install pytest pytest-asyncio
```

The `pyproject.toml` already configures `asyncio_mode = "auto"` so all `async` test functions run automatically.

---

## Running Tests

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run a specific file
pytest tests/test_agent.py -v

# Run a specific test
pytest tests/test_hooks.py::test_before_tool_skip_dataclass -v

# Run tests matching a pattern
pytest tests/ -k "hook" -v

# Show test durations
pytest tests/ --durations=10

# Run with coverage
pip install pytest-cov
pytest tests/ --cov=src --cov-report=term-missing
```

---

## Test Design

### No Real API Calls

All tests use mock models that yield pre-defined event sequences. No API keys or network access needed.

```python
# How mock models work (from tests/test_agent.py)
def make_model(events=None):
    if events is None:
        events = [
            {"type": "text-delta", "text": "Hello, world!"},
            {"type": "finish", "reason": "stop"},
        ]
    model = MagicMock()
    model.stream = MagicMock(return_value=make_stream(*events))
    return model
```

### Async Tests

All tests that involve `await` are decorated with `@pytest.mark.asyncio`. The `pyproject.toml` sets `asyncio_mode = "auto"` so this marker is optional, but included for clarity.

### Fixture: `mock_gateway`

`tests/test_quiver_core.py` uses a `mock_gateway` fixture that patches `create_gateway` so `QuiverCore` creates mock model adapters instead of real ones:

```python
@pytest.fixture
def mock_gateway():
    with patch("src.core.quiver_core.create_gateway") as mock_create:
        gw = MagicMock()
        model = make_mock_model()
        gw.create_agent_model.return_value = model
        gw.configure_provider = MagicMock()
        mock_create.return_value = gw
        yield gw, model
```

---

## Test Coverage by Feature

### Agent Core (`test_agent.py`)

| Test | What it checks |
|---|---|
| `test_agent_run_simple_text` | Basic text output from run() |
| `test_agent_run_returns_agent_run_result` | Return type is AgentRunResult |
| `test_agent_run_accumulates_messages` | Messages added to history |
| `test_agent_has_run_property` | has_run flips after run() |
| `test_agent_continue_after_run` | continue_() continues conversation |
| `test_agent_run_with_tool_call` | Tool is executed during agent loop |
| `test_agent_abort` | abort() stops the agent |
| `test_agent_max_iterations` | Agent stops at max_iterations |
| `test_agent_snapshot` | snapshot() returns correct state |
| `test_agent_restore` | restore() replaces message history |
| `test_agent_subscribe_events` | subscribe() receives events |
| `test_agent_text_delta_events` | Text deltas have correct fields |
| `test_completion_tool_ends_run` | completes_run tool ends loop |
| `test_unknown_tool_returns_error` | Missing tool handled gracefully |
| `test_emit_status_notice` | status-notice event emitted |
| `test_usage_tracked` | Token usage accumulated |
| `test_on_event_constructor_param` | on_event= constructor arg works |

### Tools (`test_tools.py`)

| Test | What it checks |
|---|---|
| `test_create_tool_basic` | create_tool() returns AgentTool |
| `test_create_tool_defaults` | Default timeout/retryable/max_retries |
| `test_create_tool_custom_timeout` | Custom timeout accepted |
| `test_create_tool_lifecycle` | completes_run lifecycle set |
| `test_tool_execute_sync` | Sync execute function works |
| `test_tool_execute_async` | Async execute function works |
| `test_tool_context_emit_update` | ctx.emit_update() works |
| `test_tool_timeout` | Tool timeout raises TimeoutError |
| `test_tool_policy_fields` | ToolPolicy field defaults |
| `test_tool_approval_skip_tool` | Rejected tool returns error result |

### Hooks (`test_hooks.py`)

| Test | What it checks |
|---|---|
| `test_before_run_hook_called` | Hook called with snapshot context |
| `test_before_run_hook_stop_dict` | {"stop": True} aborts run |
| `test_before_run_hook_stop_dataclass` | AgentStopControl(stop=True) aborts run |
| `test_after_run_hook_called` | Hook called with result context |
| `test_after_run_hook_async` | Async hooks work |
| `test_before_model_hook_called` | Hook called before LLM |
| `test_before_model_stop_dict` | {"stop": True} aborts from beforeModel |
| `test_before_model_stop_dataclass` | AgentBeforeModelResult(stop=True) aborts |
| `test_before_model_mutate_options_dict` | Dict options mutation applied |
| `test_before_model_mutate_options_dataclass` | Dataclass options mutation applied |
| `test_before_tool_hook_called` | Hook called with tool context |
| `test_before_tool_skip_dict` | {"skip": True} skips tool |
| `test_before_tool_skip_dataclass` | AgentBeforeToolResult(skip=True) skips |
| `test_before_tool_modify_input_dict` | {"input": ...} modifies tool input |
| `test_before_tool_modify_input_dataclass` | AgentBeforeToolResult(input=...) modifies |
| `test_before_tool_stop_dataclass` | AgentBeforeToolResult(stop=True) aborts |
| `test_after_tool_hook_called` | Hook called after tool |
| `test_after_tool_modify_result_dict` | Dict result replacement |
| `test_after_tool_modify_result_dataclass` | AgentAfterToolResult replacement |
| `test_after_tool_stop_dataclass` | AgentAfterToolResult(stop=True) aborts |

### Events (`test_events.py`)

| Test | What it checks |
|---|---|
| `test_run_started_event` | run-started emitted |
| `test_turn_started_event` | turn-started has iteration field |
| `test_assistant_text_delta_events` | text deltas with accumulatedText |
| `test_assistant_reasoning_delta_events` | reasoning deltas emitted |
| `test_tool_started_and_finished_events` | tool-started, tool-finished emitted |
| `test_tool_updated_event` | tool-updated from emit_update() |
| `test_usage_updated_event` | usage-updated has usage dict |
| `test_turn_finished_event` | turn-finished has toolCallCount |
| `test_message_added_events` | message-added for each message |
| `test_assistant_message_event` | assistant-message event |
| `test_run_finished_event` | run-finished with result |
| `test_run_failed_event` | run-failed when model errors |
| `test_status_notice_event` | emit_status_notice() works |
| `test_subscribe_returns_unsubscribe` | subscribe() is callable |
| `test_unsubscribe_stops_events` | Events stop after unsubscribe |
| `test_multiple_subscribers` | Multiple listeners all fire |

### Plugins (`test_plugins.py`)

| Test | What it checks |
|---|---|
| `test_plugin_setup_called` | setup() called on init |
| `test_plugin_receives_context` | Context has agent_id |
| `test_plugin_adds_tools` | Plugin tools executable |
| `test_plugin_hooks_fire` | before_run / after_run hooks from plugin |
| `test_plugin_hooks_before_tool` | before_tool hook from plugin |
| `test_multiple_plugins_all_setup` | All plugins initialized |
| `test_plugins_combined_with_direct_tools` | Plugin + direct tools coexist |
| `test_plugin_none_setup_is_safe` | None return from setup() is safe |
| `test_plugin_context_has_agent_id` | Context fields correct |

### QuiverCore (`test_quiver_core.py`)

| Test | What it checks |
|---|---|
| `test_create_returns_quiver_core` | Factory returns instance |
| `test_create_in_memory_db_by_default` | Default :memory: db |
| `test_start_returns_session_result` | start() returns StartSessionResult |
| `test_send_returns_run_result` | send() returns AgentRunResult |
| `test_send_unknown_session_raises` | Unknown session raises error |
| `test_multiple_sessions_independent` | Sessions have unique IDs |
| `test_get_session_returns_record` | get() returns SessionRecord |
| `test_get_unknown_session_returns_none` | get() returns None for missing |
| `test_list_sessions` | list() includes created sessions |
| `test_delete_session` | delete() removes session |
| `test_read_messages_after_send` | Messages persisted after send() |
| `test_get_accumulated_usage` | get_accumulated_usage() returns AgentUsage |
| `test_subscribe_receives_events` | Events dispatched to listeners |
| `test_subscribe_returns_unsubscribe` | Returns callable |
| `test_async_context_manager` | async with works |
| `test_abort_session` | abort() updates status |

---

## Live Provider Tests

To test with real LLM providers, set API keys and run:

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_live_providers.py -v -s

# OpenAI
OPENAI_API_KEY=sk-... pytest tests/test_live_providers.py -v -s -k "openai"
```

Live provider tests are not run in CI (no API keys available). They verify end-to-end integration with real providers.

To run live tests manually:

```python
# tests/test_live_providers.py
import os
import asyncio
import pytest
from src import Agent

@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="No ANTHROPIC_API_KEY")
@pytest.mark.asyncio
async def test_anthropic_live():
    agent = Agent(
        provider_id="anthropic",
        model_id="claude-haiku-4-5",
        system_prompt="You are a helpful assistant.",
    )
    result = await agent.run("What is 2 + 2? Reply with just the number.")
    assert result.status == "completed"
    assert "4" in result.output_text
```

---

## Adding New Tests

1. Create a test function in the appropriate file (or a new `tests/test_<feature>.py`)
2. Use `@pytest.mark.asyncio` for async tests
3. Use `make_model()` / `make_tool_model()` from `tests/test_agent.py` for mock models
4. Patch `create_gateway` for QuiverCore tests (see `mock_gateway` fixture)
5. Return errors as dicts from tool execute functions — never raise

```python
# Example new test
@pytest.mark.asyncio
async def test_my_feature():
    model = make_model([
        {"type": "text-delta", "text": "Result"},
        {"type": "finish", "reason": "stop"},
    ])
    agent = Agent(model=model)
    result = await agent.run("Test my feature")
    assert result.status == "completed"
```

---

## CI Integration

Add to your CI pipeline (GitHub Actions example):

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install "quiver-sdk[dev]"
      - run: pytest tests/ -v --tb=short
```
