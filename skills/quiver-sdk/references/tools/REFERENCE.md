# Tools

Tools are how agents interact with the world. The Quiver SDK supports both built-in tools (via QuiverCore) and custom tools you define.

## Creating Custom Tools

Use `create_tool()` from `src`:

```python
from src import create_tool

my_tool = create_tool(
    name="get_weather",
    description="Get the current weather for a city. Returns temperature in Celsius and conditions.",
    input_schema={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name, e.g. 'London' or 'New York'",
            },
            "units": {
                "type": "string",
                "enum": ["celsius", "fahrenheit"],
                "description": "Temperature units (default: celsius)",
            },
        },
        "required": ["city"],
    },
    execute=fetch_weather,
    timeout_ms=10_000,
    retryable=True,
    max_retries=2,
)
```

## Tool `execute` Function

The execute function receives `(input: dict, context: AgentToolContext)` and can be sync or async:

```python
from src import AgentToolContext

async def fetch_weather(inp: dict, ctx: AgentToolContext) -> dict:
    city = inp.get("city", "")
    units = inp.get("units", "celsius")

    # ctx provides:
    # ctx.agent_id       — the agent's ID
    # ctx.iteration      — current agent loop iteration
    # ctx.session_id     — session context (if using QuiverCore)
    # ctx.tool_call_id   — unique ID for this tool call
    # ctx.emit_update()  — send a progress update event

    ctx.emit_update(f"Fetching weather for {city}...")

    try:
        data = await call_weather_api(city, units)
        return {"temperature": data["temp"], "conditions": data["desc"], "city": city}
    except Exception as e:
        return {"error": str(e)}   # return errors — don't raise!
```

**Important:** Never raise exceptions from `execute`. Return `{"error": "..."}` instead. Exceptions count as "mistakes" against the agent's mistake limit.

## Completion Tools (Terminal Tools)

A completion tool ends the agent loop when it succeeds. Add `lifecycle={"completes_run": True}`:

```python
submit_tool = create_tool(
    name="submit_answer",
    description="Submit the final answer. Call this when you have the complete answer.",
    input_schema={
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "The final answer"},
        },
        "required": ["answer"],
    },
    lifecycle={"completes_run": True},
    execute=lambda inp, ctx: {"submitted": True, "answer": inp["answer"]},
)
```

Without a completion tool, the agent loop ends when the model returns text with no tool calls.

## Tool Configuration Options

```python
create_tool(
    name="my_tool",             # snake_case name (required)
    description="...",          # LLM reads this — be specific (required)
    input_schema={...},         # JSON Schema (required)
    execute=my_fn,              # Callable (required)
    lifecycle=None,             # {"completes_run": True} for terminal tools
    timeout_ms=30_000,          # Execution timeout in ms (default: 30s)
    retryable=True,             # Auto-retry on failure (default: True)
    max_retries=3,              # Max retry count (default: 3)
)
```

## Built-in Tools (QuiverCore)

When using `QuiverCore(enable_tools=True)`, these tools are available automatically:

| Tool | Description |
|---|---|
| `run_commands` | Execute shell commands in the workspace |
| `edit_file` | Create, view, and str_replace files |
| `read_files` | Read file contents with line ranges |
| `search_codebase` | Ripgrep-based regex search |
| `fetch_web_content` | HTTP fetch with content extraction |
| `apply_patch` | Apply structured patches (ADD/UPDATE/DELETE/MOVE) |

## Tool Policies (Approval)

Require explicit approval before tools execute:

```python
from src import Agent, ToolPolicy, ToolApprovalRequest, ToolApprovalResult

async def my_approval_handler(req: ToolApprovalRequest) -> ToolApprovalResult:
    print(f"Approve tool: {req.tool_name}?")
    print(f"Input: {req.input}")
    answer = input("[y/n]: ")
    if answer.lower() == "y":
        return ToolApprovalResult(approved=True)
    return ToolApprovalResult(approved=False, reason="User rejected")

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    tools=[read_tool, write_tool, exec_tool],
    tool_policies={
        "read_data": ToolPolicy(auto_approve=True),        # no prompt
        "write_data": ToolPolicy(require_approval=True),   # prompt required
        "run_commands": ToolPolicy(require_approval=True), # prompt required
    },
    request_tool_approval=my_approval_handler,
)
```

### `ToolPolicy` Fields

```python
ToolPolicy(
    require_approval=True,    # bool: force approval for this tool
    auto_approve=False,       # bool: skip approval (overrides require_approval)
)
```

Use `"*"` as a wildcard policy that applies to all tools not specifically listed:

```python
tool_policies={
    "*": ToolPolicy(require_approval=True),   # approve all by default
    "read_files": ToolPolicy(auto_approve=True),  # except read_files
}
```

## Tool Execution Order

By default tools are executed sequentially. To run all tool calls from a single turn in parallel:

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    tools=[fetch_url, read_file, search_code],
    tool_execution="parallel",   # run all tool calls concurrently
)
```

**Caution:** Parallel execution can cause conflicts if tools write to the same resources.

## Tool Progress Updates

Emit progress updates from long-running tools:

```python
async def execute(inp: dict, ctx: AgentToolContext) -> dict:
    ctx.emit_update("Starting analysis...")

    files = get_files(inp["directory"])
    for i, f in enumerate(files):
        ctx.emit_update(f"Processing {i+1}/{len(files)}: {f}")
        process_file(f)

    return {"files_processed": len(files)}
```

Progress updates emit `tool-updated` events to subscribers.

## Tool Input Types

The `input` dict matches your JSON Schema. Common patterns:

```python
# Single string input
execute=lambda inp, ctx: {"result": process(inp.get("text", ""))}

# Multiple fields
async def execute(inp: dict, ctx):
    path = inp.get("path", "")
    mode = inp.get("mode", "read")
    lines = inp.get("lines", 100)
    ...

# Flexible input — handle list or dict
async def execute(inp: dict, ctx):
    items = inp.get("items") or inp.get("item") or []
    if isinstance(items, str):
        items = [items]
    ...
```

## `AgentToolContext` Reference

```python
@dataclass
class AgentToolContext:
    agent_id: str                            # Agent ID
    iteration: int                           # Current loop iteration
    session_id: Optional[str] = None         # QuiverCore session ID
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None
    tool_call_id: Optional[str] = None       # Unique ID for this call
    signal: Optional[Any] = None             # Cancellation signal
    metadata: Optional[dict] = None
    snapshot: Optional[AgentRuntimeStateSnapshot] = None
    emit_update: Optional[Callable] = None   # Call to emit tool-updated event
```
