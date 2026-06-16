# Events

The Quiver SDK emits real-time events during agent execution. Both `Agent` and `QuiverCore` use the same event system — `AgentRuntimeEvent` dicts.

## How to Subscribe

### Agent

```python
from src import Agent

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are a helpful assistant.",
)

# Subscribe BEFORE run() to capture all events
unsubscribe = agent.subscribe(lambda event: print(event["type"]))
result = await agent.run("Hello!")
unsubscribe()
```

### QuiverCore

```python
from src import QuiverCore

core = QuiverCore.create(provider_id="anthropic", model_id="claude-sonnet-4-6")
session = await core.start()

unsubscribe = core.subscribe(session.session_id, lambda event: print(event["type"]))
result = await core.send(session.session_id, "Hello!")
unsubscribe()
```

### Via `on_event` constructor arg

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    on_event=lambda event: print(event["type"]),
)
```

## Event Type Reference

### `run-started`

Emitted when the agent loop begins.

```python
{
    "type": "run-started",
    "snapshot": AgentRuntimeStateSnapshot,
}
```

### `turn-started`

Emitted at the start of each LLM iteration.

```python
{
    "type": "turn-started",
    "snapshot": AgentRuntimeStateSnapshot,
    "iteration": 1,
}
```

### `assistant-text-delta`

Streaming text chunk from the model.

```python
{
    "type": "assistant-text-delta",
    "snapshot": AgentRuntimeStateSnapshot,
    "iteration": 1,
    "text": "Hello",              # the new chunk
    "accumulatedText": "Hello",   # full text so far
}
```

### `assistant-reasoning-delta`

Streaming reasoning/thinking chunk (models with extended thinking).

```python
{
    "type": "assistant-reasoning-delta",
    "snapshot": AgentRuntimeStateSnapshot,
    "iteration": 1,
    "text": "Let me think...",
    "accumulatedText": "Let me think...",
    "redacted": False,
}
```

### `assistant-message`

Emitted when the full assistant message is complete.

```python
{
    "type": "assistant-message",
    "snapshot": AgentRuntimeStateSnapshot,
    "iteration": 1,
    "message": {
        "id": "msg-abc",
        "role": "assistant",
        "content": [...],          # list of parts
        "createdAt": 1234567890,
    },
    "finishReason": "tool-calls",  # "stop" | "tool-calls" | "max-tokens" | "error"
}
```

### `tool-started`

Emitted when a tool call begins executing.

```python
{
    "type": "tool-started",
    "snapshot": AgentRuntimeStateSnapshot,
    "iteration": 1,
    "toolCall": {
        "type": "tool-call",
        "toolCallId": "tc-abc",
        "toolName": "run_commands",
        "input": {"commands": ["ls -la"]},
    },
}
```

### `tool-updated`

Progress update from a tool's `ctx.emit_update()` call.

```python
{
    "type": "tool-updated",
    "snapshot": AgentRuntimeStateSnapshot,
    "iteration": 1,
    "toolCall": {...},
    "update": "Processing file 3/10...",
}
```

### `tool-finished`

Emitted when a tool call completes.

```python
{
    "type": "tool-finished",
    "snapshot": AgentRuntimeStateSnapshot,
    "iteration": 1,
    "toolCall": {"toolName": "run_commands", ...},
    "message": {
        "role": "tool",
        "content": [{
            "type": "tool-result",
            "toolCallId": "tc-abc",
            "toolName": "run_commands",
            "output": "file1.py\nfile2.py",
            "isError": False,
        }],
        ...
    },
}
```

### `usage-updated`

Emitted after token usage changes.

```python
{
    "type": "usage-updated",
    "snapshot": AgentRuntimeStateSnapshot,
    "usage": {
        "input_tokens": 1234,
        "output_tokens": 567,
        "cache_read_tokens": 100,
        "cache_write_tokens": 50,
        "total_cost": 0.002,
    },
}
```

### `turn-finished`

Emitted at the end of each LLM iteration.

```python
{
    "type": "turn-finished",
    "snapshot": AgentRuntimeStateSnapshot,
    "iteration": 1,
    "toolCallCount": 2,
}
```

### `message-added`

Emitted when any message is appended to the conversation.

```python
{
    "type": "message-added",
    "snapshot": AgentRuntimeStateSnapshot,
    "message": {...},
}
```

### `status-notice`

Informational status text for display.

```python
{
    "type": "status-notice",
    "snapshot": AgentRuntimeStateSnapshot,
    "text": "Analyzing large file...",
    "metadata": {"file": "main.py"},
}
```

### `run-finished`

Emitted when the agent loop completes (any status).

```python
{
    "type": "run-finished",
    "snapshot": AgentRuntimeStateSnapshot,
    "result": {
        "agentId": "agent-abc",
        "runId": "run-xyz",
        "status": "completed",
        "iterations": 3,
        "outputText": "Here is the result...",
        "usage": {"inputTokens": 1234, "outputTokens": 567, ...},
        "error": None,
    },
}
```

### `run-failed`

Emitted when the agent loop fails with an unrecoverable error.

```python
{
    "type": "run-failed",
    "snapshot": AgentRuntimeStateSnapshot,
    "error": "Connection refused",
}
```

## Practical Examples

### Print streaming text

```python
agent.subscribe(lambda e: (
    print(e["text"], end="", flush=True)
    if e["type"] == "assistant-text-delta" else None
))
```

### Log all tool calls

```python
def log_tools(event: dict):
    if event["type"] == "tool-started":
        name = event["toolCall"]["toolName"]
        inp = event["toolCall"].get("input", {})
        print(f"[TOOL] {name}: {inp}")
    elif event["type"] == "tool-finished":
        name = event["toolCall"]["toolName"]
        result = event["message"]["content"][0] if event["message"]["content"] else {}
        is_err = result.get("isError", False)
        print(f"[TOOL] {name} {'ERROR' if is_err else 'OK'}")

agent.subscribe(log_tools)
```

### Track total cost

```python
total_cost = 0.0

def track_cost(event: dict):
    global total_cost
    if event["type"] == "usage-updated":
        total_cost = event["usage"].get("total_cost") or 0.0

agent.subscribe(track_cost)
result = await agent.run("Do the task")
print(f"Cost: ${total_cost:.4f}")
```

### Abort on budget

```python
def check_budget(event: dict):
    if event["type"] == "usage-updated":
        cost = event["usage"].get("total_cost") or 0
        if cost > 0.10:
            agent.abort("Budget exceeded")

agent.subscribe(check_budget)
```
