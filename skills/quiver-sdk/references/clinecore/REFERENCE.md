# QuiverCore Runtime

`QuiverCore` is the full-featured runtime from `src`. It wraps the `Agent` loop with session persistence (SQLite), built-in tools (bash, editor, file reading, search, web fetch), MCP server support, and optional hub-backed multi-process support.

## When to Use QuiverCore

| Use QuiverCore when... | Use Agent instead when... |
|---|---|
| You need built-in tools (bash, editor, etc.) | You only need custom tools |
| You want session persistence to disk | Stateless is fine |
| You need multi-turn sessions across restarts | Single-shot runs are enough |
| You need multi-process session sharing (hub) | Single-process is fine |
| You want MCP server integration | No MCP needed |

## Quick Start

```python
import asyncio
from src import QuiverCore

async def main():
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful coding assistant.",
        enable_tools=True,
        db_path="/tmp/quiver.db",
    ) as core:
        session = await core.start()
        result = await core.send(session.session_id, "List all .py files in this directory.")
        print(result.output_text)

asyncio.run(main())
```

## Core Concepts

- **Sessions** — Each call to `start()` creates a new conversation backed by SQLite. Sessions survive process restarts.
- **Built-in tools** — When `enable_tools=True`, the agent has `run_commands`, `edit_file`, `read_files`, `search_codebase`, `fetch_web_content`, and `apply_patch`.
- **Hub mode** — Start a WebSocket server with `start_hub()` for multi-process session sharing.
- **MCP** — Connect to Model Context Protocol servers for additional tool sets.

## Key APIs

- `QuiverCore.create(...)` — Factory (returns instance, use `async with` or call `dispose()`)
- `await core.start(config?)` — Create a new session → `StartSessionResult`
- `await core.send(session_id, message)` — Send a message, wait for result
- `await core.continue_session(session_id, message?)` — Continue an existing session
- `await core.abort(session_id)` — Cancel a running session
- `await core.read_messages(session_id)` — Get message history
- `await core.list()` — List all sessions
- `await core.delete(session_id)` — Delete a session
- `await core.dispose()` — Clean up all resources (always call this!)
- `core.subscribe(session_id, listener)` — Stream events for a session

See `api.md` for full API details.

## Session Lifecycle

```python
# Create core
core = QuiverCore.create(provider_id="anthropic", model_id="claude-sonnet-4-6")

# Start a session
session = await core.start()
session_id = session.session_id

# Multi-turn conversation
r1 = await core.send(session_id, "Read README.md")
r2 = await core.send(session_id, "Summarize what you read")

# Read persisted messages
messages = await core.read_messages(session_id)
print(f"{len(messages)} messages stored")

# Dispose when done
await core.dispose()
```

## Next Steps

- `api.md` — Full QuiverCore API reference
- `patterns.md` — Common patterns and best practices
- `gotchas.md` — Pitfalls and debugging
- `../tools/REFERENCE.md` — Tool configuration
- `../events/REFERENCE.md` — Event streaming
- `../production/REFERENCE.md` — Deployment patterns
