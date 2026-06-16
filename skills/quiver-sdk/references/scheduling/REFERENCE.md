# Scheduling and Automation

Run Quiver SDK agents on a schedule using Python's async ecosystem, APScheduler, or cron.

## Overview

Options for scheduled agent execution:

| Method | Best For | Dependencies |
|---|---|---|
| `asyncio` + `asyncio.sleep` | Simple intervals, always-on services | None (stdlib) |
| APScheduler | Cron expressions, multiple jobs | `pip install apscheduler` |
| System cron + `python script.py` | OS-level scheduling, simple scripts | None |
| Celery beat | Distributed, high-volume scheduling | `pip install celery` |

## `asyncio` Interval Loop

```python
import asyncio
from src import QuiverCore

async def daily_review():
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-haiku-4-5",
        system_prompt="You are an automated code reviewer.",
        enable_tools=True,
        db_path="/var/lib/reviews.db",
    ) as core:
        session = await core.start()
        result = await core.send(
            session.session_id,
            "Review all Python files changed in the last 24 hours and summarize findings."
        )
        print(f"Review: {result.output_text}")

async def main():
    while True:
        try:
            await daily_review()
        except Exception as e:
            print(f"Review failed: {e}")
        # Wait 24 hours
        await asyncio.sleep(24 * 60 * 60)

asyncio.run(main())
```

## APScheduler (Cron Expressions)

```python
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src import QuiverCore

# Shared core instance
core = QuiverCore.create(
    provider_id="anthropic",
    model_id="claude-haiku-4-5",
    system_prompt="You are an automated analyst.",
    enable_tools=True,
    db_path="/var/lib/automation.db",
)

async def daily_report():
    session = await core.start()
    result = await core.send(
        session.session_id,
        "Generate the daily metrics summary report."
    )
    # Send report somewhere...
    print(result.output_text)

async def weekly_cleanup():
    session = await core.start()
    result = await core.send(
        session.session_id,
        "Find and remove unused Python dependencies from requirements.txt."
    )
    print(result.output_text)

async def hourly_check():
    session = await core.start()
    result = await core.send(
        session.session_id,
        "Check for any failing tests and summarize the errors."
    )
    print(result.output_text)

def main():
    scheduler = AsyncIOScheduler()

    scheduler.add_job(daily_report, "cron", hour=9, minute=0)            # 9:00 AM daily
    scheduler.add_job(weekly_cleanup, "cron", day_of_week="mon", hour=8) # Mondays 8 AM
    scheduler.add_job(hourly_check, "interval", hours=1)                 # every hour

    scheduler.start()
    print("Scheduler started")

    asyncio.get_event_loop().run_forever()

main()
```

## System Cron + Python Script

Write a standalone script that runs once and exits:

```python
# scripts/daily_review.py
import asyncio
import sys
from src import QuiverCore

async def main():
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are an automated code reviewer.",
        enable_tools=True,
        db_path="/var/lib/quiver.db",
    ) as core:
        session = await core.start()
        result = await core.send(
            session.session_id,
            "Review today's commits and write a summary to /tmp/review.md"
        )
        if result.status != "completed":
            print(f"Review failed: {result.error}", file=sys.stderr)
            sys.exit(1)
        print("Daily review complete")

asyncio.run(main())
```

Add to crontab:

```
# Daily code review at 9 AM
0 9 * * * /usr/bin/python3 /opt/myapp/scripts/daily_review.py >> /var/log/reviews.log 2>&1
```

## Event-Driven Triggers

Run agents in response to events (file changes, webhooks, messages):

```python
import asyncio
from pathlib import Path
from src import Agent

async def on_file_change(path: str):
    agent = Agent(
        provider_id="anthropic",
        model_id="claude-haiku-4-5",
        system_prompt="You are a code reviewer.",
    )
    result = await agent.run(f"Review the changes in {path} and provide feedback.")
    print(f"Review for {path}:\n{result.output_text}")

# File watcher using watchdog
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import asyncio

loop = asyncio.new_event_loop()

class CodeChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith(".py"):
            asyncio.run_coroutine_threadsafe(
                on_file_change(event.src_path), loop
            )

observer = Observer()
observer.schedule(CodeChangeHandler(), path="./src", recursive=True)
observer.start()

loop.run_forever()
```

## Webhook Trigger (FastAPI)

```python
from fastapi import FastAPI, BackgroundTasks
from src import QuiverCore

app = FastAPI()

core = QuiverCore.create(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are an automated assistant.",
    enable_tools=True,
    db_path="/var/lib/quiver.db",
)

async def run_agent_task(prompt: str):
    session = await core.start()
    result = await core.send(session.session_id, prompt)
    print(f"Task complete: {result.output_text[:100]}")

@app.post("/webhook/github")
async def github_webhook(payload: dict, background_tasks: BackgroundTasks):
    if payload.get("action") == "opened" and "pull_request" in payload:
        pr = payload["pull_request"]
        prompt = f"Review pull request: {pr['title']}\n{pr['body']}"
        background_tasks.add_task(run_agent_task, prompt)
    return {"ok": True}
```

## Common Cron Automation Tasks

The `examples/cron/` directory contains pre-written cron specs for common tasks:

| File | Description |
|---|---|
| `daily-code-review.cron.md` | Review code changes daily |
| `changelog-generator.cron.md` | Generate changelogs from commits |
| `dependency-check.cron.md` | Audit and update dependencies |
| `documentation-check.cron.md` | Check doc coverage |
| `test-coverage-report.cron.md` | Generate test coverage reports |
| `weekly-metrics-summary.cron.md` | Weekly project metrics |
| `dead-code-finder.cron.md` | Find unused code |
| `performance-baseline.cron.md` | Track performance regressions |
| `code-style-audit.cron.md` | Enforce code style |
| `type-check-strict.cron.md` | Strict type checking |

## Tips

1. **Persist sessions** — use `db_path` with a file path so sessions survive between runs
2. **Set `max_iterations`** — prevent runaway automated agents
3. **Log everything** — use structured logging and subscribe to events
4. **Handle failures gracefully** — check `result.status`, alert on repeated failures
5. **Use idempotent prompts** — automation prompts should be safe to run multiple times
6. **Monitor costs** — automated agents can accumulate large bills if unchecked
