# QuiverCore API Reference

## Creating QuiverCore

```python
from src import QuiverCore

core = QuiverCore.create(
    provider_id="anthropic",          # str: default provider
    model_id="claude-sonnet-4-6",     # str: default model
    api_key=None,                     # str: provider API key
    base_url=None,                    # str: custom API endpoint
    headers=None,                     # dict: extra HTTP headers
    system_prompt=None,               # str: default system prompt
    cwd=None,                         # str: working directory for tools
    enable_tools=True,                # bool: enable built-in tools
    max_iterations=None,              # int: default max iterations
    db_path=":memory:",               # str: SQLite path (":memory:" or file path)
    mcp_servers=None,                 # List[McpServer]
    extra_tools=None,                 # List[AgentTool]: additional tools
    gateway_provider_configs=None,    # List[GatewayProviderConfig]: multi-provider
    hub=None,                         # HubOptions
    logger=None,                      # logging logger
)
```

Use as async context manager to auto-dispose:

```python
async with QuiverCore.create(...) as core:
    session = await core.start()
    # ... use core ...
# core.dispose() called automatically
```

## Session Lifecycle Methods

### `await core.start(config?)`

Create a new session. Config overrides the QuiverCore defaults.

```python
session = await core.start({
    "provider_id": "openai",         # override default provider
    "model_id": "gpt-4o",
    "system_prompt": "Custom prompt for this session",
    "max_iterations": 15,
    "enable_tools": False,
    "tools": [my_custom_tool],
})
print(session.session_id)
print(session.agent_id)
```

Returns: `StartSessionResult(session_id, agent_id)`

### `await core.send(session_id, message)`

Send a user message to a session and wait for completion.

```python
result = await core.send(session_id, "What files are in this directory?")
print(result.output_text)
print(result.status)       # "completed" | "aborted" | "failed"
print(result.iterations)
```

Returns: `AgentRunResult`

### `await core.continue_session(session_id, message?)`

Continue a session with an optional new message.

```python
result = await core.continue_session(session_id, "Now summarize what you found.")
```

Returns: `AgentRunResult`

### `await core.abort(session_id)`

Cancel an actively running session.

```python
await core.abort(session_id)
```

### `await core.restore(session_id, messages?)`

Restore a session's message history (from DB or provided messages).

```python
await core.restore(session_id)              # reload from SQLite
await core.restore(session_id, messages)   # use provided messages
```

### `await core.dispose()`

Dispose all resources: abort running agents, close DB, stop hub, disconnect MCP servers.

```python
await core.dispose()
```

## Session Query Methods

### `await core.get(session_id)`

Get a session record by ID.

```python
record = await core.get(session_id)
print(record.status)       # "completed" | "running" | etc.
print(record.created_at)   # Unix timestamp ms
```

Returns: `Optional[SessionRecord]`

### `await core.list(limit?, offset?, status?)`

List session records.

```python
sessions = await core.list(limit=50, offset=0)
active = await core.list(status="running")
for s in sessions:
    print(s.session_id, s.status, s.message_count)
```

Returns: `List[SessionRecord]`

### `await core.read_messages(session_id, limit?, offset?, after_id?)`

Read persisted messages for a session.

```python
messages = await core.read_messages(session_id)
last_10 = await core.read_messages(session_id, limit=10)
```

Returns: `List[AgentMessage]`

### `await core.get_accumulated_usage(session_id)`

Get the cumulative token usage for an active session.

```python
usage = await core.get_accumulated_usage(session_id)
print(usage.input_tokens, usage.output_tokens)
```

Returns: `AgentUsage`

### `await core.delete(session_id)`

Delete a session and all its persisted messages.

```python
await core.delete(session_id)
```

### `await core.update(session_id, metadata?, status?)`

Update session metadata.

```python
await core.update(session_id, metadata={"task": "code-review"})
```

### `core.get_agent(session_id)`

Get the `AgentRuntime` for a session (for advanced use).

```python
agent = core.get_agent(session_id)
if agent:
    snap = agent.snapshot()
```

## Events

### `core.subscribe(session_id, listener)`

Subscribe to events for a specific session. Returns an unsubscribe function.

```python
def handle(event: dict):
    if event["type"] == "assistant-text-delta":
        print(event["text"], end="", flush=True)

unsubscribe = core.subscribe(session_id, handle)
result = await core.send(session_id, "Hello")
unsubscribe()
```

## Hub Mode

### `await core.start_hub(host?, port?, token?)`

Start the WebSocket hub server.

```python
address = await core.start_hub(host="127.0.0.1", port=8765, token="secret")
print(f"Hub running at {address}")  # "ws://127.0.0.1:8765"
```

### `await core.stop_hub()`

Stop the hub server.

```python
await core.stop_hub()
```

## Types

### `SessionRecord`

```python
@dataclass
class SessionRecord:
    session_id: str
    created_at: int         # Unix timestamp ms
    updated_at: int
    status: str             # "running" | "completed" | "aborted" | "failed"
    config: Optional[dict] = None
    metadata: Optional[dict] = None
    message_count: int = 0
```

### `StartSessionResult`

```python
@dataclass
class StartSessionResult:
    session_id: str
    agent_id: str
```

### `McpServer`

```python
from src import McpServer

McpServer(
    name="my-server",
    command="uvx",               # for stdio transport
    args=["mcp-server-git"],
    env={"HOME": "/tmp"},
    url=None,                    # for SSE/HTTP transport
    transport="stdio",           # "stdio" | "sse" | "http"
)
```
