# Agent Runtime

The `Agent` class (also exported as `AgentRuntime`) is the lightweight, stateless agent loop from `src`. It handles the core iteration cycle: send messages to an LLM, execute tool calls, collect results, and repeat until the task is done.

## When to Use Agent

| Use Agent when... | Use QuiverCore instead when... |
|---|---|
| You want a simple agent with custom tools | You need built-in tools (bash, editor, etc.) |
| You want minimal dependencies | You need session persistence (SQLite) |
| You're building a stateless worker | You need multi-process session sharing |
| You want full control over the runtime | You want batteries-included setup |

## Quick Start

```python
import asyncio
from src import Agent

async def main():
    agent = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful assistant.",
        tools=[],
    )

    result = await agent.run("What is the capital of France?")
    print(result.output_text)

asyncio.run(main())
```

## Core Concepts

The Agent operates in a loop:
1. Accept user input (string, message, or list of messages)
2. Build turn context (system prompt, messages, tools)
3. Call the LLM provider
4. If the model returns tool calls, execute them and loop back to step 3
5. If the model returns text without tool calls, the run completes
6. Emit events throughout for streaming

The agent is stateless in the sense that it does not persist anything to disk. Conversation history is held in memory and can be accessed via `snapshot()`.

## Key APIs

- `Agent(...)` or `AgentRuntime(...)` - Create an agent
- `await agent.run(input)` - Start a run with user input
- `await agent.continue_(input?)` - Continue an existing conversation
- `agent.abort(reason?)` - Cancel an active run
- `agent.subscribe(listener)` - Listen to streaming events (returns unsubscribe fn)
- `agent.snapshot()` - Get current runtime state
- `agent.restore(messages)` - Replace message history
- `agent.has_run` - `bool`: whether `run()` has been called

See `api.md` for full API details.

## Multi-Turn Conversations

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are a helpful assistant.",
)

first = await agent.run("What is 2 + 2?")
print(first.output_text)

second = await agent.continue_("Now multiply that by 3")
print(second.output_text)
```

Use `agent.has_run` to check if a run has already been executed, which determines whether to call `run()` or `continue_()`.

## Event Streaming

Use `agent.subscribe()` to stream events in real time. Register the listener before calling `run()` to avoid missing early events.

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are a helpful assistant.",
)

# Subscribe BEFORE run() to get all events
unsubscribe = agent.subscribe(lambda event: (
    print(event["text"], end="", flush=True)
    if event["type"] == "assistant-text-delta" else None
))

result = await agent.run("What is the capital of France?")
unsubscribe()
```

See `events/REFERENCE.md` for the full event type catalog.

## Next Steps

- `api.md` - Full Agent API reference
- `patterns.md` - Common patterns and best practices
- `gotchas.md` - Pitfalls and debugging
- `../tools/REFERENCE.md` - Creating custom tools
- `../events/REFERENCE.md` - Event system details
- `../providers/REFERENCE.md` - Provider configuration
