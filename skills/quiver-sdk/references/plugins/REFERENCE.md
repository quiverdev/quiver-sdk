# Plugins

A Quiver plugin is a Python class or object that extends any agent built on the Quiver SDK. Plugins bundle tools and hooks into reusable, shareable units.

A plugin can:
- Add custom tools to the agent
- Register hooks for `before_run`, `after_run`, `before_tool`, `after_tool`, `before_model`, `after_model`
- Be distributed as a Python package

## Plugin Protocol

```python
from src.types import AgentRuntimePlugin, AgentRuntimePluginContext, AgentRuntimePluginSetup

class AgentRuntimePlugin(Protocol):
    name: str

    async def setup(
        self, context: AgentRuntimePluginContext
    ) -> Optional[AgentRuntimePluginSetup]:
        ...
```

### `AgentRuntimePluginContext`

```python
@dataclass
class AgentRuntimePluginContext:
    agent_id: str
    agent_role: Optional[str] = None
    system_prompt: Optional[str] = None
```

### `AgentRuntimePluginSetup`

```python
@dataclass
class AgentRuntimePluginSetup:
    tools: Optional[List[AgentTool]] = None
    hooks: Optional[Dict[str, Any]] = None
```

## Creating a Plugin

```python
from src import (
    AgentRuntimePluginContext,
    AgentRuntimePluginSetup,
    create_tool,
)

class WeatherPlugin:
    name = "weather"

    async def setup(self, ctx: AgentRuntimePluginContext):
        weather_tool = create_tool(
            name="get_weather",
            description="Get the current weather for a city.",
            input_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                },
                "required": ["city"],
            },
            execute=self._get_weather,
        )

        def before_tool(c):
            print(f"[weather] Tool called: {c['toolCall'].get('toolName')}")

        return AgentRuntimePluginSetup(
            tools=[weather_tool],
            hooks={"before_tool": before_tool},
        )

    async def _get_weather(self, inp: dict, ctx) -> dict:
        city = inp.get("city", "")
        # fetch weather data...
        return {"city": city, "temperature": 22, "conditions": "sunny"}
```

## Using a Plugin

```python
from src import Agent

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt="You are a helpful assistant with weather information.",
    plugins=[WeatherPlugin()],
)

result = await agent.run("What's the weather in Tokyo?")
print(result.output_text)
```

## Combining Plugins + Tools + Hooks

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    plugins=[MetricsPlugin(), LoggingPlugin()],
    tools=[my_custom_tool],
    hooks={"before_run": lambda c: print("Run starting...")},
)
```

## Metrics Plugin

```python
class MetricsPlugin:
    name = "metrics"

    def __init__(self):
        self.stats = {"runs": 0, "tools": {}, "total_tokens": 0}

    async def setup(self, ctx: AgentRuntimePluginContext):
        stats = self.stats

        def before_run(c):
            stats["runs"] += 1

        def after_run(c):
            result = c.get("result")
            if result:
                stats["total_tokens"] += result.usage.input_tokens + result.usage.output_tokens

        def before_tool(c):
            name = c["toolCall"].get("toolName", "?")
            stats["tools"][name] = stats["tools"].get(name, 0) + 1

        return AgentRuntimePluginSetup(hooks={
            "before_run": before_run,
            "after_run": after_run,
            "before_tool": before_tool,
        })
```

## Safety Plugin

Block specific tool calls:

```python
BLOCKED_TOOLS = {"drop_database", "format_drive"}

class SafetyPlugin:
    name = "safety"

    async def setup(self, ctx: AgentRuntimePluginContext):
        def before_tool(c):
            name = c["toolCall"].get("toolName", "")
            if name in BLOCKED_TOOLS:
                return {"stop": True, "reason": f"Tool '{name}' blocked by policy"}

        return AgentRuntimePluginSetup(hooks={"before_tool": before_tool})
```

## Logging Plugin

```python
import logging

class LoggingPlugin:
    name = "logging"

    def __init__(self, logger=None):
        self._log = logger or logging.getLogger("quiver.agent")

    async def setup(self, ctx: AgentRuntimePluginContext):
        log = self._log

        def before_run(c):
            log.info("Agent run started", extra={"agent_id": ctx.agent_id})

        def after_run(c):
            result = c.get("result")
            if result:
                log.info(
                    "Agent run finished",
                    extra={"status": result.status, "iterations": result.iterations}
                )

        def before_tool(c):
            log.debug("Tool call: %s", c["toolCall"].get("toolName"))

        def after_tool(c):
            log.debug("Tool done in %dms", c.get("durationMs", 0))

        return AgentRuntimePluginSetup(hooks={
            "before_run": before_run,
            "after_run": after_run,
            "before_tool": before_tool,
            "after_tool": after_tool,
        })
```

## Distributing a Plugin as a Python Package

Structure:

```
my_quiver_plugin/
  __init__.py       # from my_quiver_plugin import MyPlugin
  plugin.py         # class MyPlugin
  tools.py          # tool definitions
pyproject.toml
README.md
```

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "my-quiver-plugin"
version = "0.1.0"
dependencies = ["quiver-sdk"]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio"]
```

Users install and use it:

```bash
pip install my-quiver-plugin
```

```python
from my_quiver_plugin import MyPlugin
from src import Agent

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    plugins=[MyPlugin()],
)
```
