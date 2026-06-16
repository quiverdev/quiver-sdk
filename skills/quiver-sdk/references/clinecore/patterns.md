# QuiverCore Patterns

## Basic Session with Built-in Tools

```python
import asyncio
from src import QuiverCore

async def main():
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful coding assistant.",
        enable_tools=True,
        db_path="/tmp/quiver.db",
    ) as core:
        session = await core.start()
        result = await core.send(
            session.session_id,
            "List all Python files in the current directory, then tell me which is largest."
        )
        print(result.output_text)

asyncio.run(main())
```

## Multi-Turn Session

```python
import asyncio
from src import QuiverCore

async def main():
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful assistant.",
    ) as core:
        session = await core.start()
        sid = session.session_id

        r1 = await core.send(sid, "What is the capital of Japan?")
        print("Turn 1:", r1.output_text)

        r2 = await core.send(sid, "What is the population of that city?")
        print("Turn 2:", r2.output_text)

        r3 = await core.send(sid, "Compare it to New York City.")
        print("Turn 3:", r3.output_text)

asyncio.run(main())
```

## Streaming Events

```python
import asyncio
from src import QuiverCore

async def main():
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful assistant.",
    )

    session = await core.start()
    sid = session.session_id

    def handle_event(event: dict):
        match event.get("type"):
            case "assistant-text-delta":
                print(event["text"], end="", flush=True)
            case "tool-started":
                print(f"\n[Tool: {event['toolCall']['toolName']}]")
            case "tool-finished":
                print("[Done]")
            case "run-finished":
                print(f"\nStatus: {event['result']['status']}")

    unsubscribe = core.subscribe(sid, handle_event)
    result = await core.send(sid, "Write a haiku about Python programming.")
    unsubscribe()

    await core.dispose()

asyncio.run(main())
```

## Session Resume Across Restarts

```python
import asyncio
from src import QuiverCore

DB_PATH = "/var/lib/myapp/sessions.db"
SESSION_ID = "sess-abc123"  # persisted from a previous run

async def resume():
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        db_path=DB_PATH,
    ) as core:
        # Check if session exists
        record = await core.get(SESSION_ID)
        if record is None:
            session = await core.start()
            session_id = session.session_id
            print(f"New session: {session_id}")
        else:
            session_id = SESSION_ID
            await core.restore(session_id)
            print(f"Resumed session: {session_id}")

        result = await core.send(session_id, "Continue from where we left off.")
        print(result.output_text)

asyncio.run(resume())
```

## Custom Tools per Session

```python
import asyncio
from src import QuiverCore, create_tool

deploy_tool = create_tool(
    name="deploy",
    description="Deploy the application to staging.",
    input_schema={
        "type": "object",
        "properties": {"service": {"type": "string"}},
        "required": ["service"],
    },
    execute=lambda inp, ctx: {"status": "deployed", "service": inp["service"]},
)

async def main():
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a DevOps assistant.",
        enable_tools=True,
    ) as core:
        session = await core.start({
            "tools": [deploy_tool],
            "system_prompt": "You are a DevOps assistant with deploy access.",
        })
        result = await core.send(session.session_id, "Deploy the auth service.")
        print(result.output_text)

asyncio.run(main())
```

## Hub Server (Multi-process)

```python
# server.py
import asyncio
from src import QuiverCore

async def main():
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful assistant.",
        db_path="/var/lib/quiver.db",
    )
    addr = await core.start_hub(host="127.0.0.1", port=8765, token="secret")
    print(f"Hub: {addr}")
    await asyncio.Event().wait()

asyncio.run(main())
```

```python
# client.py
import asyncio
from src import HubClient

async def main():
    client = HubClient("ws://127.0.0.1:8765", token="secret")
    await client.connect()

    sessions = await client.list_sessions()
    session_id = sessions[0].session_id if sessions else (
        await client.start_session()
    ).session_id

    result = await client.send(session_id, "What is 2 + 2?")
    print(result.output_text)

asyncio.run(main())
```

## Session List and Cleanup

```python
import asyncio
from src import QuiverCore
from datetime import datetime, timedelta

async def cleanup_old_sessions():
    async with QuiverCore.create(db_path="/var/lib/quiver.db") as core:
        sessions = await core.list(limit=1000)
        cutoff = (datetime.now() - timedelta(days=30)).timestamp() * 1000  # ms

        for s in sessions:
            if s.created_at < cutoff and s.status in ("completed", "aborted", "failed"):
                await core.delete(s.session_id)
                print(f"Deleted session: {s.session_id}")

asyncio.run(cleanup_old_sessions())
```

## MCP Server Integration

```python
import asyncio
from src import QuiverCore, McpServer

async def main():
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a Git-aware coding assistant.",
        mcp_servers=[
            McpServer(name="git", command="uvx", args=["mcp-server-git", "--repository", "."]),
            McpServer(name="fs", command="npx", args=["@modelcontextprotocol/server-filesystem", "/tmp"]),
        ],
    ) as core:
        session = await core.start()
        result = await core.send(session.session_id, "Show me the last 5 commits.")
        print(result.output_text)

asyncio.run(main())
```
