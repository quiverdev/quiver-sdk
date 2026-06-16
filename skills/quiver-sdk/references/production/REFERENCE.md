# Going to Production

Guidelines for deploying Quiver SDK Python agents in production environments.

## Error Handling

Always check the result status:

```python
result = await agent.run(input)

match result.status:
    case "completed":
        print("Success:", result.output_text)
    case "aborted":
        print("Cancelled:", result.error)
    case "failed":
        print("Failed:", result.error)
```

For QuiverCore, check the `AgentRunResult` from `send()`:

```python
result = await core.send(session_id, message)

if result.status == "failed":
    # Agent failed — log, alert, cleanup
    logger.error("Agent failed: %s", result.error)
    await core.delete(session_id)
    # Re-create session for retry
    session = await core.start()
```

## Cost Control

### Token Limits

Set maximum tokens per turn and iteration limits:

```python
from src import Agent

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    max_iterations=10,
    model_options={"max_tokens": 4096},
)
```

### Model Selection

Use cheaper models for simple tasks:

```python
# Simple classification or formatting
Agent(provider_id="anthropic", model_id="claude-haiku-4-5")

# Complex reasoning and code generation
Agent(provider_id="anthropic", model_id="claude-sonnet-4-6")

# Hardest tasks requiring deep reasoning
Agent(provider_id="anthropic", model_id="claude-opus-4-7")
```

### Usage Tracking

Monitor spending in real time:

```python
MAX_BUDGET = 0.10  # USD

def check_budget(event: dict):
    if event["type"] == "usage-updated":
        cost = event["usage"].get("total_cost") or 0
        if cost > MAX_BUDGET:
            agent.abort("Budget exceeded")

agent.subscribe(check_budget)
```

## Observability

### Structured Logging

```python
import logging
import json

def log_event(event: dict):
    etype = event.get("type", "")
    if etype in ("tool-started", "tool-finished", "run-finished", "run-failed"):
        logging.info(json.dumps({
            "event": etype,
            "iteration": event.get("iteration"),
            "tool": event.get("toolCall", {}).get("toolName") if "toolCall" in event else None,
        }))

agent.subscribe(log_event)
```

### Custom Metrics via Plugins

```python
from src import AgentRuntimePluginContext, AgentRuntimePluginSetup

class MetricsPlugin:
    name = "metrics"

    async def setup(self, ctx: AgentRuntimePluginContext):
        def before_run(c):
            metrics.increment("agent.runs.started")

        def after_run(c):
            result = c.get("result")
            if result:
                metrics.increment(f"agent.runs.{result.status}")
                metrics.histogram("agent.iterations", result.iterations)
                metrics.histogram("agent.tokens.output", result.usage.output_tokens)

        def before_tool(c):
            name = c["toolCall"].get("toolName", "unknown")
            metrics.increment(f"agent.tools.{name}")

        def after_tool(c):
            metrics.histogram("agent.tool.duration_ms", c.get("durationMs", 0))

        return AgentRuntimePluginSetup(hooks={
            "before_run": before_run,
            "after_run": after_run,
            "before_tool": before_tool,
            "after_tool": after_tool,
        })
```

## Security

### Sandbox Tool Execution

Validate tool inputs to prevent path traversal and injection:

```python
import os

WORKSPACE_ROOT = "/var/workspace"

async def safe_read(inp: dict, ctx) -> dict:
    path = inp.get("path", "")
    safe_path = os.path.realpath(os.path.join(WORKSPACE_ROOT, path))
    if not safe_path.startswith(WORKSPACE_ROOT):
        return {"error": "Path traversal attempt blocked"}
    if not os.path.isfile(safe_path):
        return {"error": f"File not found: {path}"}
    with open(safe_path, "r", encoding="utf-8") as f:
        return {"content": f.read()}
```

### API Key Management

- Use environment variables, never hardcode keys
- Rotate keys regularly
- Use different keys for development and production

```python
import os
Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    api_key=os.environ["ANTHROPIC_API_KEY"],   # never a literal string
)
```

### Tool Policy Hardening

Disable tools you don't need and require approval for dangerous ones:

```python
from src import ToolPolicy

tool_policies = {
    "read_files": ToolPolicy(auto_approve=True),
    "search_codebase": ToolPolicy(auto_approve=True),
    "run_commands": ToolPolicy(require_approval=True),   # require approval
    "edit_file": ToolPolicy(require_approval=True),
    "apply_patch": ToolPolicy(require_approval=True),
}
```

### Block Dangerous Commands via Hooks

```python
BLOCKED = ["rm -rf", "sudo", "curl | sh", "> /dev/"]

def before_tool(ctx: dict):
    if ctx["toolCall"].get("toolName") == "run_commands":
        cmd = str(ctx.get("input", {}).get("commands", ""))
        for danger in BLOCKED:
            if danger in cmd:
                return {"skip": True}

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    hooks={"before_tool": before_tool},
)
```

## Deployment Patterns

### Stateless Worker

For request/response workloads (API endpoints, queue consumers):

```python
from fastapi import FastAPI
from src import Agent

app = FastAPI()

@app.post("/agent")
async def run_agent(body: dict):
    agent = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful assistant.",
        max_iterations=10,
    )
    result = await agent.run(body["prompt"])
    return {"text": result.output_text, "status": result.status}
```

### Persistent Service

For long-running services with session management:

```python
import asyncio, signal
from src import QuiverCore

async def main():
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        db_path="/var/lib/quiver.db",
    )

    def shutdown():
        asyncio.create_task(core.dispose())

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, shutdown)

    # ... serve requests ...
    await asyncio.Event().wait()

asyncio.run(main())
```

### Scheduled Automation

See `../scheduling/REFERENCE.md` for recurring agent tasks.

## Retry and Resilience

- Tool `execute` functions support `retryable=True` (default) and `max_retries=3` (default)
- Use `timeout_ms` on tools to prevent hanging
- Monitor agent `status == "failed"` to detect systematic failures
- Implement circuit breakers for external dependencies

## See Also

- `../agent/REFERENCE.md` — Agent overview
- `../quivercore/REFERENCE.md` — QuiverCore overview
- `../tools/REFERENCE.md` — Tool configuration
- `../plugins/REFERENCE.md` — Metrics plugins
- `../scheduling/REFERENCE.md` — Scheduled agents
