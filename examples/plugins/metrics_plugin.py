"""
Metrics plugin example for the Quiver SDK.

Tracks agent run statistics: total runs, tool usage, token consumption,
and per-run durations. Demonstrates the plugin system.

Usage:
    python examples/plugins/metrics_plugin.py

Install:
    pip install "quiver-sdk[anthropic]"
    export ANTHROPIC_API_KEY="sk-ant-..."
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Dict

from quiver_sdk import Agent, create_tool
from quiver_sdk.types import AgentRuntimePluginContext, AgentRuntimePluginSetup


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


@dataclass
class AgentStats:
    """Accumulated statistics across all agent runs."""

    runs_started: int = 0
    runs_completed: int = 0
    runs_aborted: int = 0
    runs_failed: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_iterations: int = 0
    tool_calls: Dict[str, int] = field(default_factory=dict)
    tool_duration_ms_total: int = 0

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def report(self) -> str:
        lines = [
            "=== Agent Metrics ===",
            f"Runs: {self.runs_started} started | {self.runs_completed} completed | "
            f"{self.runs_aborted} aborted | {self.runs_failed} failed",
            f"Iterations: {self.total_iterations} total",
            f"Tokens: {self.total_input_tokens:,} in / {self.total_output_tokens:,} out "
            f"({self.total_tokens:,} total)",
            f"Tool calls: {sum(self.tool_calls.values())} total | avg duration: "
            f"{self.tool_duration_ms_total // max(sum(self.tool_calls.values()), 1)}ms",
        ]
        if self.tool_calls:
            lines.append("Per-tool breakdown:")
            for tool_name, count in sorted(self.tool_calls.items(), key=lambda x: -x[1]):
                lines.append(f"  {tool_name}: {count}")
        return "\n".join(lines)


class MetricsPlugin:
    """
    Plugin that collects statistics across agent runs.

    Hooks into before_run, after_run, before_tool, and after_tool
    to track runs, tool usage, and token consumption.
    """

    name = "metrics"

    def __init__(self, stats: AgentStats = None):
        self.stats = stats or AgentStats()

    async def setup(self, ctx: AgentRuntimePluginContext):
        stats = self.stats

        def before_run(c):
            stats.runs_started += 1
            print(f"[metrics] Run #{stats.runs_started} started")

        def after_run(c):
            result = c.get("result")
            if result:
                if result.status == "completed":
                    stats.runs_completed += 1
                elif result.status == "aborted":
                    stats.runs_aborted += 1
                else:
                    stats.runs_failed += 1

                stats.total_iterations += result.iterations
                stats.total_input_tokens += result.usage.input_tokens
                stats.total_output_tokens += result.usage.output_tokens

                print(
                    f"[metrics] Run finished: {result.status} "
                    f"({result.iterations} iterations, "
                    f"{result.usage.input_tokens}→{result.usage.output_tokens} tokens)"
                )

        def before_tool(c):
            name = c["toolCall"].get("toolName", "unknown")
            stats.tool_calls[name] = stats.tool_calls.get(name, 0) + 1
            print(f"[metrics] Tool called: {name}")

        def after_tool(c):
            duration_ms = c.get("durationMs", 0)
            stats.tool_duration_ms_total += duration_ms
            name = c["toolCall"].get("toolName", "?")
            print(f"[metrics] Tool {name} done in {duration_ms}ms")

        return AgentRuntimePluginSetup(
            hooks={
                "before_run": before_run,
                "after_run": after_run,
                "before_tool": before_tool,
                "after_tool": after_tool,
            }
        )


# ---------------------------------------------------------------------------
# Demo tools
# ---------------------------------------------------------------------------


def make_demo_tools():
    def search_docs(inp, ctx):
        query = inp.get("query", "")
        time.sleep(0.05)  # simulate work
        return {"results": [f"Doc result for: {query}"], "count": 1}

    def calculate(inp, ctx):
        expr = inp.get("expression", "0")
        try:
            result = eval(expr, {"__builtins__": {}}, {})  # noqa: S307
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}

    return [
        create_tool(
            name="search_docs",
            description="Search documentation for the given query.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            execute=search_docs,
        ),
        create_tool(
            name="calculate",
            description="Evaluate a Python math expression.",
            input_schema={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
            execute=calculate,
        ),
        create_tool(
            name="finish",
            description="Submit the final answer.",
            input_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
            lifecycle={"completes_run": True},
            execute=lambda inp, ctx: {"answer": inp.get("answer", "")},
        ),
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    stats = AgentStats()
    plugin = MetricsPlugin(stats)

    agent = Agent(
        provider_id="anthropic",
        model_id="claude-haiku-4-5",
        system_prompt=(
            "You are a helpful assistant. "
            "Use tools to answer questions, then call finish with the final answer."
        ),
        tools=make_demo_tools(),
        plugins=[plugin],
        max_iterations=5,
    )

    print("=== Run 1 ===")
    r1 = await agent.run("What is 17 * 23 + 144?")
    print(f"Output: {r1.output_text}\n")

    # Reset for second run (new agent)
    agent2 = Agent(
        provider_id="anthropic",
        model_id="claude-haiku-4-5",
        system_prompt=(
            "You are a helpful assistant. "
            "Use tools to answer questions, then call finish with the final answer."
        ),
        tools=make_demo_tools(),
        plugins=[plugin],  # same stats object
        max_iterations=5,
    )

    print("=== Run 2 ===")
    r2 = await agent2.run("Search docs for 'async generators' and summarize.")
    print(f"Output: {r2.output_text}\n")

    print(stats.report())


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to run this example.")
        raise SystemExit(1)
    asyncio.run(main())
