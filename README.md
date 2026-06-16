<h1 align="center">quiver-sdk</h1>

<div align="center">

[![PyPI version](https://img.shields.io/pypi/v/quiver-sdk.svg?style=flat-square)](https://pypi.org/project/quiver-sdk/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen?style=flat-square)](#testing)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](CONTRIBUTING.md)

**The official Python SDK for building AI agents with the Quiver runtime.**

Build agentic applications backed by any major LLM — with tools, hooks, sessions, MCP servers, and a WebSocket hub — all from Python.

[Installation](#installation) · [Quick Start](#quick-start) · [Providers](#providers) · [Tools](#tools) · [QuiverCore](#quivercore) · [API Reference](#api-reference)

</div>

---

## Features

- **Multi-provider LLM gateway** — Anthropic, OpenAI, Google Gemini, AWS Bedrock, Mistral, OpenAI-compatible, and more
- **Tool execution engine** — define custom tools with JSON Schema, automatic retries, timeouts, and approval flows
- **Built-in tools** — `run_commands`, `edit_file`, `read_files`, `search_codebase`, `fetch_web_content`, `apply_patch`
- **Session persistence** — SQLite-backed sessions with full message history via `QuiverCore`
- **Plugin & hook system** — intercept the agent loop at any stage (`before_run`, `before_tool`, `after_tool`, etc.)
- **MCP support** — connect to Model Context Protocol servers (stdio, SSE, HTTP)
- **WebSocket Hub** — multi-process session sharing via JSON-RPC over WebSocket
- **Streaming events** — real-time text deltas, tool call notifications, token usage
- **Async-first** — built entirely on `asyncio`; streaming via async generators

---

## Installation

```bash
pip install quiver-sdk
```

Install with optional provider extras:

```bash
# Anthropic (Claude)
pip install "quiver-sdk[anthropic]"

# OpenAI (GPT)
pip install "quiver-sdk[openai]"

# Google Gemini
pip install "quiver-sdk[google]"

# AWS Bedrock
pip install "quiver-sdk[bedrock]"

# Mistral
pip install "quiver-sdk[mistral]"

# All providers + HTTP + Hub
pip install "quiver-sdk[all]"
```

**Requirements:** Python 3.10+

---

## Quick Start

### Standalone Agent

The lightest way to run an agent. No persistence, no built-in tools — just a model and your custom tools.

```python
import asyncio
from src import Agent, create_tool

# Define a custom tool
calculator = create_tool(
    name="calculate",
    description="Evaluate a Python math expression and return the result.",
    input_schema={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Python math expression, e.g. '2 + 2'"}
        },
        "required": ["expression"],
    },
    execute=lambda inp, ctx: {"result": eval(inp["expression"])},
)

async def main():
    agent = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="sk-ant-...",          # or set ANTHROPIC_API_KEY env var
        system_prompt="You are a helpful assistant. Use the calculator tool for math.",
        tools=[calculator],
    )

    result = await agent.run("What is 17 * 23 + 144?")
    print(result.output_text)          # "The answer is 535."
    print(f"Tokens: {result.usage.input_tokens} in, {result.usage.output_tokens} out")

asyncio.run(main())
```

### QuiverCore (Persistent Sessions)

Full runtime with SQLite sessions, built-in tools, MCP, and hub support.

```python
import asyncio
from src import QuiverCore

async def main():
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        api_key="sk-ant-...",
        system_prompt="You are a helpful coding assistant.",
        enable_tools=True,
        db_path="/tmp/quiver.db",
    ) as core:
        # Start a new session
        session = await core.start()

        # Send a message
        result = await core.send(session.session_id, "List the Python files in this directory.")
        print(result.output_text)

        # Continue the conversation
        result2 = await core.send(session.session_id, "Which one is the largest?")
        print(result2.output_text)

        # Read persisted messages
        messages = await core.read_messages(session.session_id)
        print(f"Total messages: {len(messages)}")

asyncio.run(main())
```

---

## Providers

### Supported Providers

| Provider ID | Description | Install |
|---|---|---|
| `anthropic` | Claude Opus 4.7, Sonnet 4.6, Haiku 4.5 | `pip install anthropic` |
| `openai` | GPT-4o, GPT-4o-mini, o1, o3 | `pip install openai` |
| `openai-compatible` | vLLM, Together, Fireworks, Groq, Ollama, LiteLLM | `pip install openai` |
| `gemini` | Gemini 2.0 Flash, Gemini 1.5 Pro | `pip install google-generativeai` |
| `bedrock` | Claude, Llama, Titan via AWS | `pip install boto3` |
| `mistral` | Mistral Large, Codestral | `pip install mistralai` |
| `openrouter` | 200+ models via OpenRouter | `pip install openai` |
| `quiver` | Quiver-managed Anthropic models | `pip install anthropic` |

### Provider Configuration

```python
from src import Agent

# Anthropic
agent = Agent(provider_id="anthropic", model_id="claude-opus-4-7", api_key="sk-ant-...")

# OpenAI
agent = Agent(provider_id="openai", model_id="gpt-4o", api_key="sk-...")

# Google Gemini
agent = Agent(provider_id="gemini", model_id="gemini-2.0-flash", api_key="AIza...")

# AWS Bedrock (uses AWS credential chain)
agent = Agent(provider_id="bedrock", model_id="anthropic.claude-sonnet-4-6")

# Mistral
agent = Agent(provider_id="mistral", model_id="mistral-large-latest", api_key="...")

# OpenAI-compatible (vLLM, Together, Groq, Ollama, etc.)
agent = Agent(
    provider_id="openai-compatible",
    model_id="meta-llama/Llama-3-70b-chat-hf",
    api_key="...",
    base_url="https://api.together.xyz/v1",
)

# OpenRouter
agent = Agent(
    provider_id="openrouter",
    model_id="anthropic/claude-3.5-sonnet",
    api_key="sk-or-...",
)
```

### Advanced Gateway

Use `create_gateway()` for multi-provider setups:

```python
from src import create_gateway, GatewayProviderConfig

gateway = create_gateway(
    provider_configs=[
        GatewayProviderConfig(provider_id="anthropic", api_key="sk-ant-..."),
        GatewayProviderConfig(provider_id="openai", api_key="sk-..."),
    ]
)

# List all available models
for model in gateway.list_models():
    print(f"{model.provider_id}/{model.id}")

# Create a model adapter for use with Agent
model = gateway.create_agent_model("anthropic", "claude-sonnet-4-6")
agent = Agent(model=model, system_prompt="...", tools=[])
```

---

## Tools

### Creating Custom Tools

```python
from src import create_tool

deploy_tool = create_tool(
    name="deploy_app",
    description="Deploy the application to the specified environment. "
                "Returns the deployment URL and status.",
    input_schema={
        "type": "object",
        "properties": {
            "environment": {
                "type": "string",
                "enum": ["staging", "production"],
                "description": "Target deployment environment",
            },
            "version": {
                "type": "string",
                "description": "Version tag to deploy (defaults to latest)",
            },
        },
        "required": ["environment"],
    },
    execute=deploy_handler,
    timeout_ms=60_000,   # 60 second timeout
    retryable=True,
    max_retries=2,
)
```

### Tool Execute Function

The `execute` function receives `(input, context)`:

```python
from src import AgentToolContext

async def my_execute(input: dict, context: AgentToolContext) -> dict:
    # context provides: agent_id, iteration, session_id, tool_call_id, emit_update
    context.emit_update(f"Processing {input['path']}...")

    # Return structured data — don't raise exceptions
    try:
        result = await do_work(input)
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"error": str(e)}   # agent adjusts its approach
```

### Completion Tools (Terminal Tools)

A tool with `lifecycle={"completes_run": True}` ends the agent loop when it succeeds:

```python
submit_tool = create_tool(
    name="submit_answer",
    description="Submit the final answer and end the task.",
    input_schema={
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    },
    lifecycle={"completes_run": True},
    execute=lambda inp, ctx: {"submitted": True, "answer": inp["answer"]},
)
```

### Tool Policies (Approval)

```python
from src import ToolPolicy

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    tools=[read_tool, write_tool, delete_tool],
    tool_policies={
        "read_data": ToolPolicy(auto_approve=True),        # runs without asking
        "write_data": ToolPolicy(require_approval=True),   # triggers approval
        "delete_data": ToolPolicy(require_approval=True),
    },
    request_tool_approval=my_approval_handler,
)
```

---

## Built-in Tools (QuiverCore)

When using `QuiverCore` with `enable_tools=True`:

| Tool | Description |
|---|---|
| `run_commands` | Execute shell commands in the workspace |
| `edit_file` | Create, view, and edit files |
| `read_files` | Read file contents with line ranges |
| `search_codebase` | Ripgrep-based code search |
| `fetch_web_content` | HTTP fetch and content extraction |
| `apply_patch` | Apply structured patches (ADD/UPDATE/DELETE/MOVE) |

---

## Streaming Events

Subscribe to real-time events before calling `run()`:

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are a helpful assistant.",
)

# Subscribe before run() to catch all events
unsubscribe = agent.subscribe(lambda event: handle_event(event))

result = await agent.run("Explain quantum entanglement in simple terms.")
unsubscribe()

def handle_event(event: dict):
    match event["type"]:
        case "assistant-text-delta":
            print(event["text"], end="", flush=True)
        case "tool-started":
            print(f"\n[Tool: {event['toolCall']['toolName']}]")
        case "tool-finished":
            print("[Tool done]")
        case "usage-updated":
            u = event["usage"]
            print(f"\nTokens: {u['input_tokens']} in / {u['output_tokens']} out")
        case "run-finished":
            print(f"\nStatus: {event['result']['status']}")
```

### Event Types

| Event | Description |
|---|---|
| `run-started` | Agent loop begins |
| `turn-started` | New LLM iteration |
| `assistant-text-delta` | Streaming text chunk |
| `assistant-reasoning-delta` | Streaming reasoning/thinking chunk |
| `assistant-message` | Complete assistant message |
| `tool-started` | Tool call begins |
| `tool-updated` | Tool progress update |
| `tool-finished` | Tool call completes |
| `usage-updated` | Token/cost delta |
| `turn-finished` | Iteration complete |
| `message-added` | Message added to history |
| `status-notice` | Informational status message |
| `run-finished` | Agent loop complete |
| `run-failed` | Agent loop failed with error |

---

## Hooks & Plugins

### Hooks

Intercept the agent loop at any stage:

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    hooks={
        "before_run": lambda ctx: print("Run started!"),
        "before_tool": lambda ctx: (
            {"stop": True, "reason": "Blocked rm -rf"}
            if ctx["toolCall"].get("toolName") == "run_commands"
            and "rm -rf" in str(ctx.get("input", {}))
            else None
        ),
        "after_tool": lambda ctx: print(
            f"Tool {ctx['toolCall']['toolName']} done in {ctx['durationMs']}ms"
        ),
        "after_run": lambda ctx: print(f"Finished: {ctx['result'].status}"),
    },
)
```

### Plugins

Bundle tools and hooks into reusable plugins:

```python
from src import AgentRuntimePlugin, AgentRuntimePluginContext, AgentRuntimePluginSetup

class MetricsPlugin:
    name = "metrics"

    async def setup(self, ctx: AgentRuntimePluginContext):
        return AgentRuntimePluginSetup(
            tools=[my_metrics_tool],
            hooks={
                "before_run": lambda c: print(f"[metrics] run started"),
                "after_run": lambda c: print(f"[metrics] iterations={c['result'].iterations}"),
            },
        )

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    plugins=[MetricsPlugin()],
)
```

---

## QuiverCore

Full runtime for production applications.

```python
from src import QuiverCore, McpServer

async with QuiverCore.create(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    api_key="sk-ant-...",
    system_prompt="You are a helpful coding assistant.",
    enable_tools=True,
    db_path="/var/lib/myapp/quiver.db",
    mcp_servers=[
        McpServer(name="git", command="uvx", args=["mcp-server-git"]),
    ],
) as core:

    # Create a session
    session = await core.start()

    # Subscribe to events
    core.subscribe(session.session_id, lambda e: print(e["type"]))

    # Send messages
    result = await core.send(session.session_id, "Set up a GitHub Actions CI pipeline.")
    print(result.output_text)

    # Read message history
    messages = await core.read_messages(session.session_id)

    # List all sessions
    sessions = await core.list()

    # Delete a session
    await core.delete(session.session_id)
```

### Hub Mode (Multi-process)

Run a WebSocket hub to share sessions across processes:

```python
# Process A: start the hub
core = QuiverCore.create(provider_id="anthropic", api_key="...")
address = await core.start_hub(host="127.0.0.1", port=8765)
print(f"Hub running at {address}")

# Process B: connect as a client
from src import HubClient
client = HubClient("ws://127.0.0.1:8765")
await client.connect()

sessions = await client.list_sessions()
result = await client.send(session_id, "Continue the task.")
```

---

## MCP Servers

Connect to Model Context Protocol servers:

```python
from src import QuiverCore, McpServer

core = QuiverCore.create(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    mcp_servers=[
        McpServer(name="filesystem", command="npx", args=["@modelcontextprotocol/server-filesystem", "/tmp"]),
        McpServer(name="git", command="uvx", args=["mcp-server-git", "--repository", "."]),
        McpServer(name="my-api", url="http://localhost:3001/sse", transport="sse"),
    ],
)
```

---

## Multi-turn Conversations

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are a code reviewer.",
)

# First turn
result1 = await agent.run("Review this function: def add(a, b): return a + b")
print(result1.output_text)

# Continue conversation (uses existing message history)
result2 = await agent.continue_("Now suggest how to add type hints.")
print(result2.output_text)

# Check if agent has run before
if agent.has_run:
    result = await agent.continue_("One more improvement?")
else:
    result = await agent.run("Start fresh")

# Get current state
snapshot = agent.snapshot()
print(f"Messages: {len(snapshot.messages)}, Iterations: {snapshot.iteration}")
```

---

## Error Handling

```python
result = await agent.run("Do the task")

match result.status:
    case "completed":
        print("Success:", result.output_text)
    case "aborted":
        print("Cancelled:", result.error)
    case "failed":
        print("Error:", result.error)

# Abort a running agent
import asyncio

async def run_with_timeout():
    task = asyncio.create_task(agent.run("Long task..."))
    await asyncio.sleep(10)
    agent.abort("Time limit reached")
    result = await task
    return result
```

---

## API Reference

### `Agent` / `AgentRuntime`

```python
Agent(
    provider_id=None,           # LLM provider ("anthropic", "openai", etc.)
    model_id=None,              # Model identifier
    api_key=None,               # Provider API key
    base_url=None,              # Custom API endpoint
    headers=None,               # Extra HTTP headers
    model=None,                 # Pre-built AgentModel (advanced)
    system_prompt=None,         # System prompt
    tools=None,                 # List[AgentTool]
    plugins=None,               # List of plugins
    hooks=None,                 # Dict of hook callbacks
    initial_messages=None,      # Pre-loaded conversation history
    max_iterations=None,        # Max agent loop iterations
    tool_execution="sequential",# "sequential" or "parallel"
    tool_policies=None,         # Dict[str, ToolPolicy]
    model_options=None,         # Model-specific options (temperature, etc.)
    on_event=None,              # Single event listener function
)

# Methods
await agent.run(input)          # Start a new run
await agent.continue_(input?)   # Continue conversation
agent.abort(reason?)            # Cancel current run
agent.subscribe(listener)       # → unsubscribe function
agent.snapshot()                # → AgentRuntimeStateSnapshot
agent.restore(messages)         # Replace message history
agent.has_run                   # bool: has run() been called?
```

### `QuiverCore`

```python
QuiverCore.create(
    provider_id=None,
    model_id=None,
    api_key=None,
    system_prompt=None,
    enable_tools=True,
    db_path=":memory:",
    mcp_servers=None,
    extra_tools=None,
)

# Session lifecycle
await core.start(config?)       # → StartSessionResult
await core.send(sid, message)   # → AgentRunResult
await core.continue_session(sid, message?) # → AgentRunResult
await core.abort(sid)
await core.restore(sid, messages?)

# Queries
await core.get(sid)             # → SessionRecord
await core.list(limit, offset)  # → List[SessionRecord]
await core.read_messages(sid)   # → List[AgentMessage]
await core.get_accumulated_usage(sid) # → AgentUsage

# Mutations
await core.update(sid, metadata?, status?)
await core.delete(sid)
await core.dispose()

# Events
core.subscribe(sid, listener)   # → unsubscribe function

# Hub
await core.start_hub(host, port, token?) # → "ws://host:port"
await core.stop_hub()

# Context manager
async with QuiverCore.create(...) as core: ...
```

### `create_tool()`

```python
create_tool(
    name,           # str: snake_case tool name
    description,    # str: description the model reads
    input_schema,   # dict: JSON Schema for inputs
    execute,        # Callable[[dict, AgentToolContext], Any]
    lifecycle=None, # {"completes_run": True} to end loop on success
    timeout_ms=30000,
    retryable=True,
    max_retries=3,
)
```

---

## Testing

```bash
# Install dev dependencies
pip install "quiver-sdk[dev]"

# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_agent.py -v

# Run with live providers (requires API keys)
ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_live_providers.py -v
```

---

## Examples

See the [`examples/`](examples/) directory:

- `examples/hooks/` — Hook scripts (PreToolUse, PostToolUse, lifecycle events)
- `examples/plugins/` — Plugin examples (weather metrics, notifications, web search)
- `examples/cron/` — Cron automation specs (daily reviews, changelog generation)

---

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Install dev dependencies: `pip install -e ".[dev]"`
4. Make changes and write tests
5. Run tests: `pytest tests/`
6. Run linting: `ruff check src/ tests/`
7. Submit a pull request

---

## Author

**quiverdev**

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

## Links
- [GitHub](https://github.com/quiverdev/quiver-sdk)
- [PyPI](https://pypi.org/project/quiver-sdk/)
