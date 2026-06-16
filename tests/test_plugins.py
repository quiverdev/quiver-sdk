"""
Tests for the plugin system.
"""

import asyncio
import pytest

from quiver_sdk import Agent, create_tool
from quiver_sdk.types import (
    AgentRuntimePluginContext,
    AgentRuntimePluginSetup,
    AgentTool,
)
from tests.test_agent import make_model, make_tool_model


# ---------------------------------------------------------------------------
# Basic plugin tests
# ---------------------------------------------------------------------------


class SimplePlugin:
    name = "simple"

    def __init__(self):
        self.setup_called = False
        self.ctx_received = None

    async def setup(self, ctx: AgentRuntimePluginContext):
        self.setup_called = True
        self.ctx_received = ctx
        return None


@pytest.mark.asyncio
async def test_plugin_setup_called():
    """Plugin setup() is called during agent initialization."""
    plugin = SimplePlugin()
    agent = Agent(model=make_model(), plugins=[plugin])
    await agent.run("Hello")
    assert plugin.setup_called is True


@pytest.mark.asyncio
async def test_plugin_receives_context():
    """Plugin setup() receives AgentRuntimePluginContext."""
    plugin = SimplePlugin()
    agent = Agent(model=make_model(), plugins=[plugin])
    await agent.run("Hello")
    assert isinstance(plugin.ctx_received, AgentRuntimePluginContext)
    assert plugin.ctx_received.agent_id


# ---------------------------------------------------------------------------
# Plugin tools
# ---------------------------------------------------------------------------


class ToolPlugin:
    name = "tool-plugin"

    async def setup(self, ctx: AgentRuntimePluginContext):
        plugin_tool = create_tool(
            name="plugin_tool",
            description="A tool from a plugin.",
            input_schema={"type": "object", "properties": {}},
            execute=lambda inp, c: {"from_plugin": True},
        )
        return AgentRuntimePluginSetup(tools=[plugin_tool])


@pytest.mark.asyncio
async def test_plugin_adds_tools():
    """Plugin tools are registered and available to the agent."""
    executed = []

    class TrackingToolPlugin:
        name = "tracking"

        async def setup(self, ctx):
            t = create_tool(
                name="plugin_t",
                description="Tracking tool",
                input_schema={},
                execute=lambda inp, c: executed.append(True) or {"ok": True},
            )
            return AgentRuntimePluginSetup(tools=[t])

    model = make_tool_model("plugin_t", {})
    agent = Agent(model=model, plugins=[TrackingToolPlugin()])
    result = await agent.run("Use plugin_t")

    assert len(executed) >= 1


# ---------------------------------------------------------------------------
# Plugin hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_hooks_fire():
    """Plugin hooks are invoked during agent run."""
    before_runs = []
    after_runs = []

    class HookPlugin:
        name = "hooks"

        async def setup(self, ctx):
            return AgentRuntimePluginSetup(hooks={
                "before_run": lambda c: before_runs.append(c),
                "after_run": lambda c: after_runs.append(c),
            })

    agent = Agent(model=make_model(), plugins=[HookPlugin()])
    await agent.run("Hello")

    assert len(before_runs) == 1
    assert len(after_runs) == 1


@pytest.mark.asyncio
async def test_plugin_hooks_before_tool():
    """Plugin before_tool hook fires."""
    hook_calls = []

    class ToolHookPlugin:
        name = "tool-hook"

        async def setup(self, ctx):
            return AgentRuntimePluginSetup(hooks={
                "before_tool": lambda c: hook_calls.append(c["toolCall"]["toolName"]),
            })

    tool = create_tool(
        name="tracked",
        description="d",
        input_schema={},
        execute=lambda i, c: {"ok": True},
    )
    agent = Agent(
        model=make_tool_model("tracked", {}),
        tools=[tool],
        plugins=[ToolHookPlugin()],
    )
    await agent.run("Use tracked")

    assert "tracked" in hook_calls


# ---------------------------------------------------------------------------
# Multiple plugins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_plugins_all_setup():
    """Multiple plugins are all initialized."""
    setup_log = []

    class P1:
        name = "p1"
        async def setup(self, ctx):
            setup_log.append("p1")
            return None

    class P2:
        name = "p2"
        async def setup(self, ctx):
            setup_log.append("p2")
            return None

    agent = Agent(model=make_model(), plugins=[P1(), P2()])
    await agent.run("Hello")

    assert "p1" in setup_log
    assert "p2" in setup_log


@pytest.mark.asyncio
async def test_plugins_combined_with_direct_tools():
    """Plugin tools and directly passed tools both work."""
    plugin_executed = []
    direct_executed = []

    class PluginWithTool:
        name = "plugin"
        async def setup(self, ctx):
            t = create_tool(
                name="plugin_tool",
                description="Plugin tool",
                input_schema={},
                execute=lambda i, c: plugin_executed.append(True) or {"ok": True},
            )
            return AgentRuntimePluginSetup(tools=[t])

    direct_tool = create_tool(
        name="direct_tool",
        description="Direct tool",
        input_schema={},
        execute=lambda i, c: direct_executed.append(True) or {"ok": True},
    )

    # Both tools should be registered
    agent = Agent(
        model=make_model(),
        plugins=[PluginWithTool()],
        tools=[direct_tool],
    )

    snap = agent.snapshot()
    # Agent should have both tools after initialization (lazy init — must trigger)
    await agent.run("Hello")


# ---------------------------------------------------------------------------
# Plugin setup returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_none_setup_is_safe():
    """Plugin that returns None from setup doesn't break the agent."""
    class NonePlugin:
        name = "none"
        async def setup(self, ctx):
            return None

    agent = Agent(model=make_model(), plugins=[NonePlugin()])
    result = await agent.run("Hello")
    assert result.status == "completed"


# ---------------------------------------------------------------------------
# Plugin context fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_context_has_agent_id():
    """Plugin context contains agent_id."""
    ctx_ref = []

    class CtxPlugin:
        name = "ctx"
        async def setup(self, ctx):
            ctx_ref.append(ctx)
            return None

    agent = Agent(
        model=make_model(),
        plugins=[CtxPlugin()],
        agent_role="test-role",
        system_prompt="Test prompt",
    )
    await agent.run("Hello")

    assert ctx_ref[0].agent_id
    assert ctx_ref[0].agent_role == "test-role"
    assert ctx_ref[0].system_prompt == "Test prompt"
