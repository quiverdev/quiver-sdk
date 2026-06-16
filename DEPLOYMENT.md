# Deployment Guide

This guide covers deploying `quiver-sdk` Python agents in production environments.

---

## Table of Contents

1. [Installation](#installation)
2. [Environment Variables](#environment-variables)
3. [Deployment Patterns](#deployment-patterns)
4. [Error Handling](#error-handling)
5. [Cost Control](#cost-control)
6. [Observability](#observability)
7. [Security](#security)
8. [Hub Mode (Multi-process)](#hub-mode-multi-process)
9. [Containerization](#containerization)
10. [Retry & Resilience](#retry--resilience)

---

## Installation

```bash
# Minimal — just Anthropic
pip install "quiver-sdk[anthropic]"

# Full production setup
pip install "quiver-sdk[anthropic,openai,hub,http]"

# All extras
pip install "quiver-sdk[all]"
```

For Docker/CI, pin the version:

```
quiver-sdk[anthropic]==0.1.0
```

---

## Environment Variables

Never hardcode API keys. Set them as environment variables:

```bash
# LLM providers
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GOOGLE_API_KEY="AIza..."
export MISTRAL_API_KEY="..."

# AWS Bedrock (uses credential chain: env, ~/.aws, IAM role)
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_DEFAULT_REGION="us-east-1"

# Hub token (optional)
export QUIVER_HUB_TOKEN="..."
```

The SDK reads provider keys automatically from environment when `api_key` is not set:

```python
from src import Agent

# Key read from ANTHROPIC_API_KEY env var automatically
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are a helpful assistant.",
)
```

---

## Deployment Patterns

### Stateless Worker (API endpoint)

For request/response workloads — FastAPI, Flask, queue consumers:

```python
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src import Agent, create_tool

app = FastAPI()

# Pre-build the agent (tools, prompts) at startup
agent_config = dict(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are a helpful assistant.",
    max_iterations=10,
)

class RunRequest(BaseModel):
    prompt: str

@app.post("/run")
async def run_agent(req: RunRequest):
    agent = Agent(**agent_config)
    result = await agent.run(req.prompt)
    if result.status == "failed":
        raise HTTPException(500, detail=str(result.error))
    return {
        "text": result.output_text,
        "status": result.status,
        "iterations": result.iterations,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        },
    }
```

### Persistent Service (QuiverCore)

For long-running services with multi-turn sessions:

```python
import asyncio
import signal
from src import QuiverCore

async def main():
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful coding assistant.",
        enable_tools=True,
        db_path="/var/lib/myapp/quiver.db",
        max_iterations=20,
    )

    loop = asyncio.get_event_loop()

    def shutdown():
        print("Shutting down...")
        asyncio.create_task(core.dispose())

    loop.add_signal_handler(signal.SIGTERM, shutdown)
    loop.add_signal_handler(signal.SIGINT, shutdown)

    # Session management loop
    session = await core.start()
    result = await core.send(session.session_id, "Analyze the current codebase.")
    print(result.output_text)

    await core.dispose()

asyncio.run(main())
```

### Scheduled Automation

Use `asyncio` or a scheduler like `APScheduler`:

```python
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src import QuiverCore

core = QuiverCore.create(
    provider_id="anthropic",
    model_id="claude-haiku-4-5",
    system_prompt="You are an automated code reviewer.",
    enable_tools=True,
    db_path="/var/lib/reviews.db",
)

async def daily_review():
    session = await core.start()
    result = await core.send(
        session.session_id,
        "Review all Python files changed in the last 24 hours."
    )
    print(f"Review complete: {result.output_text[:200]}")

scheduler = AsyncIOScheduler()
scheduler.add_job(daily_review, "cron", hour=9, minute=0)
scheduler.start()

asyncio.get_event_loop().run_forever()
```

### Queue Consumer (Celery / SQS / RQ)

```python
from celery import Celery
from src import Agent
import asyncio

app = Celery("tasks", broker="redis://localhost:6379/0")

@app.task
def process_task(prompt: str) -> dict:
    async def run():
        agent = Agent(
            provider_id="anthropic",
            model_id="claude-sonnet-4-6",
            system_prompt="You are a task processor.",
            max_iterations=15,
        )
        result = await agent.run(prompt)
        return {
            "status": result.status,
            "text": result.output_text,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        }
    return asyncio.run(run())
```

---

## Error Handling

Always check `result.status`:

```python
result = await agent.run(prompt)

match result.status:
    case "completed":
        # Normal completion
        print("Output:", result.output_text)

    case "aborted":
        # Manually cancelled or hook stopped it
        print("Cancelled:", result.error)

    case "failed":
        # Unrecoverable error (model error, network failure, etc.)
        print("Failed:", result.error)
        # Log and alert
        raise RuntimeError(f"Agent failed: {result.error}")
```

For `QuiverCore`, check the run result similarly:

```python
result = await core.send(session_id, message)

if result.status == "failed":
    # Re-create the session with fresh state
    await core.delete(session_id)
    session = await core.start()
```

### Handling max_iterations

Set a generous but bounded iteration limit:

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    max_iterations=20,
)

result = await agent.run(prompt)
if result.iterations >= 20 and result.status != "completed":
    # Agent hit the iteration limit
    log.warning("Agent hit max_iterations", iterations=result.iterations)
```

---

## Cost Control

### Set max_iterations

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    max_iterations=10,      # Hard cap on iterations
    model_options={"max_tokens": 4096},  # Cap per-turn tokens
)
```

### Monitor usage in real time

```python
MAX_COST_USD = 0.50

def check_budget(event: dict):
    if event["type"] == "usage-updated":
        usage = event["usage"]
        cost = usage.get("total_cost") or 0
        if cost > MAX_COST_USD:
            agent.abort(f"Budget exceeded: ${cost:.4f}")

agent.subscribe(check_budget)
result = await agent.run(prompt)
```

### Use cheaper models for simple tasks

```python
# Classification, extraction, simple Q&A
cheap_agent = Agent(provider_id="anthropic", model_id="claude-haiku-4-5")

# Code review, complex reasoning
medium_agent = Agent(provider_id="anthropic", model_id="claude-sonnet-4-6")

# Hardest tasks: deep research, complex architecture
premium_agent = Agent(provider_id="anthropic", model_id="claude-opus-4-7")
```

---

## Observability

### Structured Logging

```python
import logging
import json
from src import Agent

logger = logging.getLogger("quiver_agent")

def log_event(event: dict):
    etype = event.get("type", "")
    if etype in ("tool-started", "tool-finished", "run-finished", "run-failed"):
        logger.info(json.dumps({
            "event": etype,
            "iteration": event.get("iteration"),
            "tool": event.get("toolCall", {}).get("toolName") if "toolCall" in event else None,
            "status": event.get("result", {}).get("status") if "result" in event else None,
        }))

agent.subscribe(log_event)
```

### OpenTelemetry

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("quiver-agent")

async def run_with_trace(prompt: str):
    with tracer.start_as_current_span("agent.run") as span:
        agent = Agent(
            provider_id="anthropic",
            model_id="claude-sonnet-4-6",
            system_prompt="You are a helpful assistant.",
        )

        def record_event(event: dict):
            if event["type"] == "tool-started":
                span.add_event("tool.started", {"tool.name": event["toolCall"]["toolName"]})
            elif event["type"] == "usage-updated":
                span.set_attribute("tokens.input", event["usage"].get("input_tokens", 0))
                span.set_attribute("tokens.output", event["usage"].get("output_tokens", 0))

        agent.subscribe(record_event)
        result = await agent.run(prompt)

        span.set_attribute("agent.status", result.status)
        span.set_attribute("agent.iterations", result.iterations)
        return result
```

### Metrics Plugin

```python
from src import AgentRuntimePlugin, AgentRuntimePluginContext, AgentRuntimePluginSetup

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
                metrics.histogram("agent.tokens.input", result.usage.input_tokens)
                metrics.histogram("agent.tokens.output", result.usage.output_tokens)

        def before_tool(c):
            name = c.get("toolCall", {}).get("toolName", "unknown")
            metrics.increment(f"agent.tools.{name}")

        def after_tool(c):
            metrics.histogram("agent.tool.duration_ms", c.get("durationMs", 0))

        return AgentRuntimePluginSetup(
            hooks={
                "before_run": before_run,
                "after_run": after_run,
                "before_tool": before_tool,
                "after_tool": after_tool,
            }
        )
```

---

## Security

### Validate Tool Inputs

Protect against path traversal and injection attacks:

```python
import os
from src import create_tool

WORKSPACE_ROOT = "/var/workspace"

safe_read_tool = create_tool(
    name="read_file",
    description="Read a file from the workspace.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    execute=lambda inp, ctx: _safe_read(inp["path"]),
)

def _safe_read(path: str) -> dict:
    abs_path = os.path.realpath(os.path.join(WORKSPACE_ROOT, path))
    if not abs_path.startswith(WORKSPACE_ROOT):
        return {"error": "Path traversal attempt blocked"}
    if not os.path.isfile(abs_path):
        return {"error": f"File not found: {path}"}
    with open(abs_path, "r", encoding="utf-8") as f:
        return {"content": f.read()}
```

### Tool Policy Hardening

Disable tools not needed and require approval for dangerous ones:

```python
from src import ToolPolicy

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    tools=[read_tool, write_tool, exec_tool],
    tool_policies={
        "read_file": ToolPolicy(auto_approve=True),
        "write_file": ToolPolicy(require_approval=True),
        "run_commands": ToolPolicy(require_approval=True),
    },
    request_tool_approval=approval_handler,
)
```

### Block Dangerous Tool Calls via Hooks

```python
BLOCKED_COMMANDS = ["rm -rf", "sudo", "curl | sh", "> /dev/sda"]

def before_tool(ctx: dict):
    tool_name = ctx["toolCall"].get("toolName", "")
    inp = ctx.get("input", {})

    if tool_name == "run_commands":
        cmd = str(inp.get("commands", ""))
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd:
                return {
                    "skip": True,
                    "stop": False,
                }

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    hooks={"before_tool": before_tool},
)
```

### API Key Management

- Use environment variables, never hardcode
- Rotate keys regularly
- Use different keys for dev, staging, production
- Use AWS IAM roles for Bedrock instead of access keys where possible

---

## Hub Mode (Multi-process)

Share sessions between processes or services:

### Server process

```python
import asyncio
from src import QuiverCore

async def start_hub():
    core = QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a helpful assistant.",
        enable_tools=True,
        db_path="/var/lib/quiver.db",
    )
    address = await core.start_hub(
        host="0.0.0.0",
        port=8765,
        token="secret-hub-token",
    )
    print(f"Hub running at {address}")
    await asyncio.Event().wait()  # run forever

asyncio.run(start_hub())
```

### Client process

```python
import asyncio
from src import HubClient

async def main():
    client = HubClient(
        url="ws://hub-host:8765",
        token="secret-hub-token",
    )
    await client.connect()

    sessions = await client.list_sessions()
    session_id = sessions[0].session_id if sessions else (
        await client.start_session()
    ).session_id

    result = await client.send(session_id, "What is the status of the project?")
    print(result.output_text)

asyncio.run(main())
```

---

## Containerization

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir "quiver-sdk[anthropic,hub]"

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "myapp.worker"]
```

### docker-compose.yml

```yaml
version: "3.9"
services:
  quiver-hub:
    build: .
    command: python -m myapp.hub
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - QUIVER_HUB_TOKEN=${QUIVER_HUB_TOKEN}
    volumes:
      - quiver-data:/var/lib/quiver
    ports:
      - "8765:8765"
    restart: unless-stopped

  worker:
    build: .
    command: python -m myapp.worker
    environment:
      - QUIVER_HUB_URL=ws://quiver-hub:8765
      - QUIVER_HUB_TOKEN=${QUIVER_HUB_TOKEN}
    depends_on:
      - quiver-hub
    restart: unless-stopped

volumes:
  quiver-data:
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quiver-agent
spec:
  replicas: 3
  selector:
    matchLabels:
      app: quiver-agent
  template:
    metadata:
      labels:
        app: quiver-agent
    spec:
      containers:
        - name: agent
          image: myrepo/quiver-agent:latest
          env:
            - name: ANTHROPIC_API_KEY
              valueFrom:
                secretKeyRef:
                  name: api-secrets
                  key: anthropic-api-key
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

---

## Retry & Resilience

### Provider API retries

The SDK automatically retries transient provider failures. For custom retry logic:

```python
import asyncio
from src import Agent

async def run_with_retry(prompt: str, max_retries: int = 3) -> str:
    last_error = None
    for attempt in range(max_retries):
        try:
            agent = Agent(
                provider_id="anthropic",
                model_id="claude-sonnet-4-6",
                system_prompt="You are a helpful assistant.",
                max_iterations=10,
            )
            result = await agent.run(prompt)
            if result.status == "completed":
                return result.output_text
            last_error = result.error
        except Exception as e:
            last_error = e

        if attempt < max_retries - 1:
            wait = 2 ** attempt
            print(f"Attempt {attempt + 1} failed, retrying in {wait}s...")
            await asyncio.sleep(wait)

    raise RuntimeError(f"All {max_retries} attempts failed: {last_error}")
```

### Tool timeouts

Configure per-tool timeouts to prevent hanging:

```python
tool = create_tool(
    name="fetch_data",
    description="Fetch data from external API.",
    input_schema={...},
    execute=fetch_handler,
    timeout_ms=10_000,    # 10 second timeout
    retryable=True,
    max_retries=2,
)
```

### Circuit breaker pattern

```python
from datetime import datetime, timedelta

class CircuitBreaker:
    def __init__(self, threshold: int = 5, timeout_seconds: int = 60):
        self._failures = 0
        self._threshold = threshold
        self._timeout = timeout_seconds
        self._opened_at = None

    def is_open(self) -> bool:
        if self._opened_at and datetime.now() > self._opened_at + timedelta(seconds=self._timeout):
            self._failures = 0
            self._opened_at = None
        return self._failures >= self._threshold

    def record_failure(self):
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = datetime.now()

    def record_success(self):
        self._failures = 0
        self._opened_at = None

breaker = CircuitBreaker()

async def safe_run(prompt: str) -> str:
    if breaker.is_open():
        raise RuntimeError("Circuit breaker open — too many recent failures")
    try:
        agent = Agent(provider_id="anthropic", model_id="claude-sonnet-4-6")
        result = await agent.run(prompt)
        if result.status == "failed":
            breaker.record_failure()
            raise RuntimeError(str(result.error))
        breaker.record_success()
        return result.output_text
    except Exception:
        breaker.record_failure()
        raise
```

---

## See Also

- [README.md](README.md) — Installation, quick start, full API reference
- [TESTS.md](TESTS.md) — Testing guide
- [examples/](examples/) — Working example scripts
