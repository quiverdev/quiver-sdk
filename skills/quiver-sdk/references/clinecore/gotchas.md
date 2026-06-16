# QuiverCore Gotchas

## Always Call `dispose()` — Use `async with`

`QuiverCore` holds resources: database connections, running agents, hub server, MCP processes. Failing to call `dispose()` can leave orphan processes and file locks.

```python
# CORRECT — use context manager
async with QuiverCore.create(...) as core:
    session = await core.start()
    result = await core.send(session.session_id, "Hello")

# CORRECT — manual dispose in try/finally
core = QuiverCore.create(...)
try:
    session = await core.start()
    result = await core.send(session.session_id, "Hello")
finally:
    await core.dispose()

# WRONG — forgetting dispose()
core = QuiverCore.create(...)
result = await core.send(...)  # session never cleaned up
```

## `start()` Creates a New Session Every Time

Each call to `start()` creates a new session. To continue an existing session, use `send()` or `continue_session()` with the existing `session_id`:

```python
# WRONG — creates new session every time
for msg in messages:
    session = await core.start()                    # new session each time!
    await core.send(session.session_id, msg)

# CORRECT — reuse the session
session = await core.start()
for msg in messages:
    await core.send(session.session_id, msg)        # same session
```

## `send()` Runs a Full Agent Loop

`send()` runs the agent loop until completion (potentially many LLM turns + tool calls). It is NOT a single message exchange. If you want to inject a single user message and continue later, use `continue_session()`.

## `:memory:` Database Doesn't Survive Restarts

The default `db_path=":memory:"` means sessions are lost on process exit. For persistent sessions:

```python
core = QuiverCore.create(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    db_path="/var/lib/myapp/quiver.db",   # persistent
)
```

## Session Must Be In-Memory to `send()`

Sessions must be active (in `self._sessions`) to call `send()`. If a session was created in a previous process, you must recreate it:

```python
# Session from prior process — not in memory
# WRONG — raises SessionNotFoundError
await core.send("sess-old-id", "Hello")

# CORRECT — restore the session first (loads messages from DB)
session = await core.start()              # new runtime session
await core.restore(session.session_id)   # load from DB if needed
```

Or start a fresh session pointing to the same data:

```python
session = await core.start({"system_prompt": "..."})
messages = await core.read_messages("sess-old-id")   # load old messages
agent = core.get_agent(session.session_id)
if agent:
    agent.restore(messages)
```

## Built-in Tools Require `enable_tools=True`

The built-in tool suite (`run_commands`, `edit_file`, etc.) is only included when `enable_tools=True` (the default). If you pass `enable_tools=False`, you get no built-in tools:

```python
# Gets built-in tools
core = QuiverCore.create(provider_id="anthropic", model_id="claude-sonnet-4-6")

# No built-in tools
core = QuiverCore.create(provider_id="anthropic", model_id="claude-sonnet-4-6", enable_tools=False)
```

## Hub Mode Requires `websockets` Package

```bash
pip install "quiver-sdk[hub]"
# or
pip install websockets
```

## Subscribing After `send()` Misses Events

Always subscribe before calling `send()`:

```python
# WRONG
result = await core.send(session_id, "Hello")
core.subscribe(session_id, listener)   # too late

# CORRECT
core.subscribe(session_id, listener)
result = await core.send(session_id, "Hello")
```

## MCP Servers Must Be Running Before `start()`

MCP servers are initialized at QuiverCore creation time. If an MCP server fails to start, tools from that server won't be available — but QuiverCore won't raise an error (it silently skips failed MCP connections). Check logs for MCP connection errors.

## `db_path` Must Be Writable

If the database path is on a read-only filesystem or lacks write permissions, QuiverCore will fail with an `sqlite3.OperationalError`. Ensure the path is writable before creating QuiverCore.
