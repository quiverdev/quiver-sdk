---
name: quiver-sdk
description: Comprehensive Quiver SDK skill for building AI agents in Python. Covers the Agent runtime, QuiverCore sessions, custom tools, plugins, events, LLM providers, scheduling, multi-agent teams, and production deployment. Use for any task involving quiver-sdk (Python package).
metadata:
   references: agent, quivercore
---

# Quiver SDK Skill

Consolidated skill for building AI agents with the Python Quiver SDK. Use the decision trees below to find the right entry point and API surface, then load detailed references.

## Critical Rules

Follow these rules in all Quiver SDK code:

1. Install with `pip install quiver-sdk`. For provider support install extras: `pip install "quiver-sdk[anthropic]"`, `"quiver-sdk[openai]"`, `"quiver-sdk[all]"`, etc.
2. Requires Python 3.10 or later. The SDK is fully async — use `asyncio.run()` or `await` from within an async context.
3. Use `create_tool()` from `src` to define tools. Tool names must be `snake_case`. The `execute` function signature is `async def execute(input: dict, ctx: AgentToolContext) -> Any`.
4. Return errors as structured data from tool `execute` functions (e.g. `{"error": "reason"}`). Do NOT raise exceptions from tools — they count as mistakes against the agent's mistake limit.
5. Use `lifecycle={"completes_run": True}` on tools that should end the agent loop (e.g. a "submit answer" or "task_complete" tool).
6. When using `QuiverCore`, always call `await core.dispose()` (or use `async with QuiverCore.create(...) as core:`) to clean up resources.
7. The `Agent` and `QuiverCore` event systems both emit `AgentRuntimeEvent` dicts. Use `agent.subscribe(listener)` or `core.subscribe(session_id, listener)` to receive events. Text streaming is `event["type"] == "assistant-text-delta"` with `event["text"]`. Result text is `result.output_text`. Do not use TypeScript event names or camelCase field names — use the Python snake_case equivalents.
8. All imports are from `src`: `from src import Agent, QuiverCore, create_tool, AgentToolContext, ToolPolicy, ...`

## How to Use This Skill

### Reference File Structure

The two main API surfaces (`Agent` and `QuiverCore`) follow a 4-file pattern. Cross-cutting concepts are single-file guides.

Each main API surface in `./references/<api>/` contains:

| File | Purpose | When to Read |
|------|---------|--------------|
| `REFERENCE.md` | Overview, when to use, quick start | Always read first |
| `api.md` | Full API: classes, methods, config, types | Writing code |
| `patterns.md` | Common patterns, best practices | Implementation guidance |
| `gotchas.md` | Pitfalls, limitations, debugging | Troubleshooting |

Cross-cutting concepts in `./references/<concept>/` have `REFERENCE.md` as the entry point.

### Reading Order

1. Start with `REFERENCE.md` for your chosen API surface
2. Then read additional files relevant to your task:
   - Writing agent code → `api.md`
   - Common patterns → `patterns.md`
   - Creating tools → `tools/REFERENCE.md`
   - Adding plugins/hooks → `plugins/REFERENCE.md`
   - Configuring LLM providers → `providers/REFERENCE.md`
   - Streaming events → `events/REFERENCE.md`
   - Deploying to production → `production/REFERENCE.md`
   - Scheduling agents → `scheduling/REFERENCE.md`
   - Multi-agent orchestration → `multi-agent/REFERENCE.md`
   - Debugging → `gotchas.md`

### Example Paths

```
./references/agent/REFERENCE.md           # Start here for lightweight agents
./references/quivercore/REFERENCE.md       # Start here for full runtime
./references/agent/api.md                 # Agent class, config, methods
./references/tools/REFERENCE.md           # Creating and using tools
./references/plugins/REFERENCE.md         # Plugin system
./references/providers/REFERENCE.md       # LLM provider configuration
```

## Quick Decision Trees

### "Which API surface should I use?"

```
Which API?
+-- I want a simple, stateless agent with custom tools
|   +-- agent/ (Agent class from src)
+-- I need session persistence, built-in tools
|   +-- quivercore/ (QuiverCore from src)
+-- I want built-in file/shell/search/web tools
|   +-- quivercore/ (has built-in tools; Agent does not)
+-- I want scheduled or recurring agents
|   +-- quivercore/ (use with APScheduler or asyncio)
+-- I need multi-process or multi-client session sharing
|   +-- quivercore/ (hub-backed WebSocket runtime)
+-- I'm building a minimal async worker
|   +-- agent/ (no extra dependencies)
```

### "I need to create tools"

```
Tools?
+-- Define a custom tool with schema → tools/REFERENCE.md
+-- Use built-in tools (bash, editor, read_files) → tools/REFERENCE.md (built-in section)
+-- Control tool approval/policies → tools/REFERENCE.md (policies section)
+-- Tool that ends the agent loop → tools/REFERENCE.md (completion tools)
+-- Package tools as a reusable plugin → plugins/REFERENCE.md
```

### "I need to handle events"

```
Events?
+-- Stream text/reasoning in real time → events/REFERENCE.md
+-- Track token usage and costs → events/REFERENCE.md
+-- Watch tool calls → events/REFERENCE.md
+-- Detect completion/errors → events/REFERENCE.md
+-- Hook into lifecycle stages → plugins/REFERENCE.md
```

### "I need to configure a model provider"

```
Providers?
+-- Anthropic (Claude) → providers/REFERENCE.md
+-- OpenAI (GPT) → providers/REFERENCE.md
+-- Google (Gemini) → providers/REFERENCE.md
+-- AWS Bedrock → providers/REFERENCE.md
+-- Mistral → providers/REFERENCE.md
+-- OpenAI-compatible (vLLM, Together, Groq, Ollama) → providers/REFERENCE.md
+-- Custom/self-hosted provider → providers/REFERENCE.md
```

### "I need plugins or hooks"

```
Plugins?
+-- Package tools + hooks together → plugins/REFERENCE.md
+-- Observe tool calls (logging, metrics) → plugins/REFERENCE.md
+-- Intercept lifecycle events → plugins/REFERENCE.md
+-- Distribute as a Python package → plugins/REFERENCE.md
```

### "I need multi-agent coordination"

```
Multi-agent?
+-- Spawn one-off sub-agents → multi-agent/REFERENCE.md (sub-agents)
+-- Persistent cross-session teams → multi-agent/REFERENCE.md (teams)
+-- Parent-child delegation → multi-agent/REFERENCE.md (sub-agents)
```

### "I need scheduling or automation"

```
Scheduling?
+-- Recurring cron jobs → scheduling/REFERENCE.md
+-- One-off scheduled tasks → scheduling/REFERENCE.md
+-- Event-driven triggers → scheduling/REFERENCE.md
```

### "I need to go to production"

```
Production?
+-- Error handling and status checks → production/REFERENCE.md
+-- Cost control and token limits → production/REFERENCE.md
+-- Observability (OpenTelemetry) → production/REFERENCE.md
+-- Security and sandboxing → production/REFERENCE.md
+-- Deployment patterns → production/REFERENCE.md
```

### Troubleshooting Index

- Agent loop not stopping → `tools/REFERENCE.md` (completion tools)
- Tool errors crashing the agent → `agent/gotchas.md` or `quivercore/gotchas.md`
- Provider auth failures → `providers/REFERENCE.md`
- Session not persisting → `quivercore/gotchas.md`
- Token usage too high → `production/REFERENCE.md` (cost control)
- Hub connection issues → `quivercore/gotchas.md`
- Plugin not loading → `plugins/REFERENCE.md`
- Events not firing → `events/REFERENCE.md`
- asyncio errors → `agent/gotchas.md`

## Product Index

### API Surfaces
| API | Entry File | Description |
|-----|------------|-------------|
| Agent | `./references/agent/REFERENCE.md` | Lightweight stateless agent loop |
| QuiverCore | `./references/quivercore/REFERENCE.md` | Full runtime with sessions, persistence, built-in tools |

### Cross-Cutting Concepts
| Concept | Entry File | Description |
|---------|------------|-------------|
| Tools | `./references/tools/REFERENCE.md` | Built-in and custom tool creation |
| Plugins | `./references/plugins/REFERENCE.md` | Extension system with hooks |
| Events | `./references/events/REFERENCE.md` | Real-time streaming events |
| Providers | `./references/providers/REFERENCE.md` | LLM provider configuration |
| Production | `./references/production/REFERENCE.md` | Deployment, security, observability |
| Scheduling | `./references/scheduling/REFERENCE.md` | Cron jobs and automation |
| Multi-Agent | `./references/multi-agent/REFERENCE.md` | Teams and sub-agents |

### Package Map
| Import | What you get |
|--------|-------------|
| `from src import Agent` | Stateless agent loop |
| `from src import QuiverCore` | Sessions, persistence, built-in tools, hub |
| `from src import create_tool` | Tool factory |
| `from src import create_gateway, GatewayProviderConfig` | LLM provider gateway |
| `from src import HubClient` | WebSocket hub client |
| `from src import AgentToolContext, AgentUsage, AgentRunResult, ...` | Type definitions |
| `from src.types import *` | All type definitions |

## Resources

Repository: https://github.com/quiverdev/quiver-sdk
Documentation: https://docs.quiver.dev/sdk/overview
Discord: https://discord.gg/quiver
