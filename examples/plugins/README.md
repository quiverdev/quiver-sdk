# Plugin Examples

Python plugin examples for the Quiver SDK.

## Examples

### `metrics_plugin.py`

Tracks agent run statistics using hooks: total runs, tool usage frequency, token consumption, and tool execution durations.

**Key features:**
- `before_run` / `after_run` hooks for run-level metrics
- `before_tool` / `after_tool` hooks for tool-level metrics
- Shared `AgentStats` dataclass across multiple runs
- Formatted report output

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python examples/plugins/metrics_plugin.py
```

### `web_search_plugin.py`

Adds a `web_search` tool to the agent via a plugin. Uses the Brave Search API (or a mock fallback).

**Key features:**
- Async tool with `ctx.emit_update()` progress notifications
- Configurable number of results
- Graceful fallback to mock search without API key
- `after_run` hook for post-run reporting

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export BRAVE_SEARCH_API_KEY="BSA..."   # optional
python examples/plugins/web_search_plugin.py
```

### `safety_plugin.py`

Intercepts tool calls and blocks dangerous operations before they execute.

**Key features:**
- `before_tool` hook with `AgentBeforeToolResult(skip=True)` to block calls
- Regex-based command blocking (rm -rf, sudo, curl|sh, etc.)
- Path traversal detection
- Domain blocklist for URL fetching
- Block audit log printed after each run

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python examples/plugins/safety_plugin.py
```

## Writing Your Own Plugin

```python
from src import Agent, create_tool
from src.types import AgentRuntimePluginContext, AgentRuntimePluginSetup

class MyPlugin:
    name = "my-plugin"

    async def setup(self, ctx: AgentRuntimePluginContext):
        my_tool = create_tool(
            name="my_tool",
            description="My plugin tool.",
            input_schema={"type": "object", "properties": {}},
            execute=lambda inp, ctx: {"ok": True},
        )

        def before_tool(c):
            print(f"Tool: {c['toolCall']['toolName']}")

        return AgentRuntimePluginSetup(
            tools=[my_tool],
            hooks={"before_tool": before_tool},
        )

agent = Agent(
    provider_id="anthropic",
    model_id="claude-haiku-4-5",
    plugins=[MyPlugin()],
)
```

See [plugins/REFERENCE.md](../../skills/quiver-sdk/references/plugins/REFERENCE.md) for full plugin documentation.
