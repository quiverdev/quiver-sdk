# Agent Patterns

## Interactive CLI Agent

A multi-turn conversational agent in the terminal with streaming output:

```python
import asyncio
import sys
from src import Agent

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are a helpful assistant.",
)

async def chat():
    print("Agent ready. Type 'quit' to exit.\n")
    first = True

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("quit", "exit"):
            break
        if not user_input:
            continue

        print("Agent: ", end="", flush=True)

        unsubscribe = agent.subscribe(lambda e: (
            print(e["text"], end="", flush=True)
            if e["type"] == "assistant-text-delta" else None
        ))

        if first:
            result = await agent.run(user_input)
            first = False
        else:
            result = await agent.continue_(user_input)

        unsubscribe()
        print()

        if result.status != "completed":
            print(f"[{result.status}]")

asyncio.run(chat())
```

## File Analyzer Agent

An agent with a custom tool that reads files and reports on them:

```python
import asyncio
from pathlib import Path
from src import Agent, create_tool

read_file_tool = create_tool(
    name="read_file",
    description="Read the content of a file at the given path.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path"},
        },
        "required": ["path"],
    },
    execute=lambda inp, ctx: {
        "content": Path(inp["path"]).read_text(encoding="utf-8"),
        "size": Path(inp["path"]).stat().st_size,
    } if Path(inp["path"]).exists() else {"error": f"File not found: {inp['path']}"},
)

async def analyze(file_path: str) -> str:
    agent = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a code reviewer. Analyze the provided files and give feedback.",
        tools=[read_file_tool],
        max_iterations=5,
    )
    result = await agent.run(f"Please review the file at {file_path} and provide feedback.")
    return result.output_text

print(asyncio.run(analyze("src/main.py")))
```

## Agent with Completion Tool

An agent that explicitly signals completion via a terminal tool:

```python
import asyncio
from src import Agent, create_tool, AgentToolContext

submit_tool = create_tool(
    name="submit_answer",
    description="Submit the final answer. Call this when you have the complete answer ready.",
    input_schema={
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "The complete final answer"},
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Confidence level in the answer",
            },
        },
        "required": ["answer"],
    },
    lifecycle={"completes_run": True},
    execute=lambda inp, ctx: {
        "submitted": True,
        "answer": inp["answer"],
        "confidence": inp.get("confidence", "medium"),
    },
)

async def ask(question: str) -> dict:
    agent = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt=(
            "Answer the user's question thoroughly. "
            "When you have the final answer, call submit_answer."
        ),
        tools=[submit_tool],
        max_iterations=3,
    )
    result = await agent.run(question)
    return {"text": result.output_text, "iterations": result.iterations}

print(asyncio.run(ask("What is the Pythagorean theorem?")))
```

## Streaming Usage Monitor

Monitor cost in real time and abort if over budget:

```python
import asyncio
from src import Agent

MAX_COST = 0.05  # $0.05 USD

async def run_with_budget(prompt: str):
    agent = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful assistant.",
        max_iterations=20,
    )

    def monitor(event: dict):
        if event["type"] == "usage-updated":
            cost = event["usage"].get("total_cost") or 0
            if cost > MAX_COST:
                agent.abort(f"Budget exceeded: ${cost:.4f}")
        elif event["type"] == "assistant-text-delta":
            print(event["text"], end="", flush=True)

    agent.subscribe(monitor)
    result = await agent.run(prompt)
    print(f"\n[{result.status}] ${result.usage.total_cost or 0:.4f}")
    return result

asyncio.run(run_with_budget("Write a detailed technical spec for a search engine."))
```

## Parallel Tool Execution

Run all tool calls in each turn concurrently:

```python
from src import Agent

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    tools=[fetch_tool, search_tool, read_tool],
    tool_execution="parallel",   # "sequential" is default
)
```

## Agent Restoration

Save and restore agent state across process restarts:

```python
import asyncio
import json
from src import Agent

async def save_and_restore():
    agent = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful assistant.",
    )

    result = await agent.run("Hello! My name is Alice.")
    snap = agent.snapshot()

    # Serialize messages to JSON
    saved = json.dumps([
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
        for m in snap.messages
    ])

    # ... restart process ...

    # Restore
    agent2 = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful assistant.",
    )
    from src.types import AgentMessage
    messages = [AgentMessage(**m) for m in json.loads(saved)]
    agent2.restore(messages)

    result2 = await agent2.continue_("What's my name?")
    print(result2.output_text)  # "Your name is Alice."

asyncio.run(save_and_restore())
```

## Hook: Log Tool Calls

```python
import logging

def before_tool(ctx: dict):
    tool_name = ctx["toolCall"].get("toolName", "unknown")
    logging.info(f"Tool call: {tool_name} with input: {ctx['input']}")

def after_tool(ctx: dict):
    tool_name = ctx["toolCall"].get("toolName", "unknown")
    logging.info(f"Tool {tool_name} completed in {ctx['durationMs']}ms")

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    hooks={"before_tool": before_tool, "after_tool": after_tool},
)
```

## Hook: Block Dangerous Commands

```python
BLOCKED = ["rm -rf", "sudo rm", "mkfs", "> /dev/"]

def before_tool(ctx: dict):
    if ctx["toolCall"].get("toolName") == "run_commands":
        cmd = str(ctx.get("input", {}).get("commands", ""))
        for danger in BLOCKED:
            if danger in cmd:
                return {"stop": True, "reason": f"Blocked dangerous command: {danger}"}

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    hooks={"before_tool": before_tool},
)
```
