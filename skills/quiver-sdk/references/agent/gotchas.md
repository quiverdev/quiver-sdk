# Agent Gotchas

## Agent Loop Never Stops

If the agent keeps iterating without completing:

- Make sure at least one tool has `lifecycle={"completes_run": True}` if you want the agent to explicitly finish.
- Without any tools, the agent will complete after the model returns text without tool calls.
- If using tools, ensure the system prompt guides the model toward calling the completion tool when done.
- Check that `completes_run` tools return successfully (not raising exceptions).
- Set `max_iterations` as a hard cap: `Agent(..., max_iterations=20)`.

## Must Use `await` — Agent is Async

All run methods are coroutines. You must `await` them:

```python
# WRONG — returns coroutine object, not result
result = agent.run("Hello")

# CORRECT
result = await agent.run("Hello")

# For scripts, use asyncio.run()
import asyncio
result = asyncio.run(agent.run("Hello"))
```

## `continue` is a Reserved Keyword — Use `continue_`

Python's `continue` keyword is reserved. The method is named `continue_`:

```python
# WRONG
result = await agent.continue("More input")

# CORRECT
result = await agent.continue_("More input")
```

## Subscribe BEFORE `run()`, Not After

Events emitted during `run()` are lost if you subscribe after:

```python
# WRONG — misses early events
result = await agent.run("Hello")
agent.subscribe(listener)   # too late

# CORRECT
agent.subscribe(listener)   # before run()
result = await agent.run("Hello")
```

## Tool `execute` Must Not Raise Exceptions

Throwing from a tool counts as a "mistake" against the agent's mistake limit. Return errors as structured data:

```python
# WRONG — counts as a mistake
async def execute(inp, ctx):
    data = fetch_data(inp["url"])  # may raise
    return data

# CORRECT — return error dict
async def execute(inp, ctx):
    try:
        data = fetch_data(inp["url"])
        return {"result": data}
    except Exception as e:
        return {"error": str(e)}
```

## Only One Active `run()` at a Time

Calling `run()` while another run is active raises `RuntimeError`:

```python
# WRONG — concurrent runs on same agent
async def bad():
    t1 = asyncio.create_task(agent.run("Task 1"))
    t2 = asyncio.create_task(agent.run("Task 2"))  # raises RuntimeError
    await asyncio.gather(t1, t2)

# CORRECT — create separate agents
async def good():
    agent1 = Agent(provider_id="anthropic", model_id="claude-sonnet-4-6")
    agent2 = Agent(provider_id="anthropic", model_id="claude-sonnet-4-6")
    t1 = asyncio.create_task(agent1.run("Task 1"))
    t2 = asyncio.create_task(agent2.run("Task 2"))
    await asyncio.gather(t1, t2)
```

## Hook Results Must Use Correct Field Names

Hook return values use `snake_case` fields (matching Python conventions). However, `"isError"` in tool result dicts uses camelCase (for internal compatibility):

```python
# beforeTool hook: return skip/stop/input
def before_tool(ctx):
    return {"skip": True}           # skip this tool call
    return {"stop": True}           # abort the run
    return {"input": {"key": "v"}}  # modify input

# afterTool hook: return modified result
def after_tool(ctx):
    return {
        "result": {"output": "modified", "isError": False}  # note: isError (camelCase)
    }
    # OR return an AgentAfterToolResult dataclass:
    from src.types import AgentAfterToolResult, AgentToolResult
    return AgentAfterToolResult(result=AgentToolResult(output="modified", is_error=False))
```

## `api_key` vs Environment Variables

If `api_key` is not set, the SDK reads from environment variables automatically:
- `ANTHROPIC_API_KEY` for Anthropic
- `OPENAI_API_KEY` for OpenAI
- `GOOGLE_API_KEY` for Gemini
- `MISTRAL_API_KEY` for Mistral

```python
import os
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-..."

# api_key not needed if env var is set
agent = Agent(provider_id="anthropic", model_id="claude-sonnet-4-6")
```

## Tool Input Arrives as a Dict

Even if the JSON Schema defines the shape, the input is always a plain Python `dict`. Access keys with `.get()` to avoid `KeyError`:

```python
async def execute(inp: dict, ctx):
    path = inp.get("path", "")     # safe
    path = inp["path"]              # raises KeyError if missing
```

## Agent State is Reset Between `run()` Calls

Each `run()` call resets internal state (`_usage`, `_iteration`, `_run_id`). Messages persist, but usage counters are per-run. Use `result.usage` for per-run totals.

## `model_options` Keys are Provider-Specific

`model_options` is passed through to the provider. Use the correct option names:

```python
# Anthropic
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    model_options={"max_tokens": 4096, "temperature": 0.7},
)

# OpenAI
agent = Agent(
    provider_id="openai",
    model_id="gpt-4o",
    model_options={"max_tokens": 2048, "temperature": 0.5},
)
```
