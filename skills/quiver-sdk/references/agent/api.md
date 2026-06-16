# Agent API Reference

## Constructor

```python
from src import Agent

agent = Agent(
    provider_id="anthropic",          # str: provider ID
    model_id="claude-sonnet-4-6",     # str: model ID
    api_key=None,                     # str: provider API key (or env var)
    base_url=None,                    # str: custom API endpoint
    headers=None,                     # dict: extra HTTP headers
    model=None,                       # AgentModel: pre-built model (advanced)
    system_prompt=None,               # str: system prompt
    tools=None,                       # List[AgentTool]
    plugins=None,                     # List of plugin instances
    hooks=None,                       # dict of hook callbacks
    initial_messages=None,            # List[AgentMessage]: pre-loaded history
    max_iterations=None,              # int: max agent loop iterations
    tool_execution="sequential",      # "sequential" | "parallel"
    tool_policies=None,               # Dict[str, ToolPolicy]
    model_options=None,               # dict: model-specific options
    on_event=None,                    # Callable: single event listener
    agent_id=None,                    # str: custom agent ID
    agent_role=None,                  # str: agent role label
    session_id=None,                  # str: session context
)
```

`Agent` is an alias for `AgentRuntime`. Both are importable from `src`.

## Methods

### `await agent.run(input)`

Start a new agent run. If the agent has already run, this continues the conversation.

```python
result = await agent.run("What is the capital of France?")
```

`input` can be:
- `str` — user text message
- `dict` — message dict with `role` and `content`
- `list` — list of message dicts
- `None` — no new input (re-runs with existing history)

Returns: `AgentRunResult`

### `await agent.continue_(input?)`

Continue an existing conversation. Same signature as `run()`. Preferred over `run()` for subsequent turns.

```python
result = await agent.continue_("Now explain it in simpler terms.")
```

Note: Python uses `continue_` (with underscore) because `continue` is a reserved keyword.

### `agent.abort(reason?)`

Cancel an active run. Safe to call at any time.

```python
agent.abort("User cancelled")
```

### `agent.subscribe(listener)`

Subscribe to real-time events. Returns an unsubscribe function.

```python
def handle_event(event: dict):
    if event["type"] == "assistant-text-delta":
        print(event["text"], end="", flush=True)

unsubscribe = agent.subscribe(handle_event)
result = await agent.run("Hello!")
unsubscribe()
```

### `agent.snapshot()`

Get a point-in-time snapshot of the agent's state.

```python
snap = agent.snapshot()
print(snap.iteration)    # current iteration number
print(snap.status)       # "idle" | "running" | "completed" | "aborted" | "failed"
print(snap.messages)     # List[AgentMessage]
print(snap.usage)        # AgentUsage
```

Returns: `AgentRuntimeStateSnapshot`

### `agent.restore(messages)`

Replace the agent's message history. Used for session restoration.

```python
agent.restore(saved_messages)
```

### `await agent.emit_status_notice(text, metadata?)`

Emit a `status-notice` event to all subscribers.

```python
await agent.emit_status_notice("Processing large file...", {"file": "main.py"})
```

### Properties

```python
agent.has_run        # bool: True if run() has been called at least once
```

## Return Types

### `AgentRunResult`

```python
@dataclass
class AgentRunResult:
    agent_id: str
    run_id: str
    status: Literal["completed", "aborted", "failed"]
    iterations: int
    output_text: str
    messages: List[AgentMessage]
    usage: AgentUsage
    agent_role: Optional[str] = None
    error: Optional[Exception] = None
```

### `AgentUsage`

```python
@dataclass
class AgentUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_cost: Optional[float] = None
```

### `AgentRuntimeStateSnapshot`

```python
@dataclass
class AgentRuntimeStateSnapshot:
    agent_id: str
    status: str
    iteration: int
    messages: List[AgentMessage]
    pending_tool_calls: List[str]
    usage: AgentUsage
    agent_role: Optional[str] = None
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None
    last_error: Optional[str] = None
```

### `AgentMessage`

```python
@dataclass
class AgentMessage:
    id: str
    role: Literal["user", "assistant", "tool"]
    content: List[dict]     # list of part dicts (text, tool-call, etc.)
    created_at: int         # Unix timestamp ms
    metadata: Optional[dict] = None
    model_info: Optional[dict] = None
    metrics: Optional[dict] = None
```

## Config Types

### `ToolPolicy`

```python
from src import ToolPolicy

ToolPolicy(
    require_approval=True,   # bool: always prompt for approval
    auto_approve=False,      # bool: auto-approve without prompting
)
```

### Hook Callbacks

All hooks can be sync or async functions:

```python
hooks = {
    "before_run": lambda ctx: None,          # ctx["snapshot"]
    "after_run": lambda ctx: None,           # ctx["snapshot"], ctx["result"]
    "before_model": lambda ctx: None,        # ctx["snapshot"], ctx["request"]
    "after_model": lambda ctx: None,         # ctx["snapshot"], ctx["assistantMessage"], ctx["finishReason"]
    "before_tool": lambda ctx: None,         # ctx["snapshot"], ctx["toolCall"], ctx["tool"], ctx["input"]
    "after_tool": lambda ctx: None,          # ctx["snapshot"], ctx["tool"], ctx["toolCall"], ctx["input"], ctx["result"], ctx["durationMs"]
}
```

Hook return values:
- `before_model`: `{"stop": True}` | `{"messages": [...]}` | `{"tools": [...]}` | `{"options": {...}}` | `AgentBeforeModelResult`
- `before_tool`: `{"skip": True}` | `{"stop": True}` | `{"input": {...}}` | `AgentBeforeToolResult`
- `after_tool`: `{"stop": True}` | `{"result": AgentToolResult(...)}` | `AgentAfterToolResult`
- `before_run` / `after_run`: `{"stop": True, "reason": "..."}` | `AgentStopControl`
