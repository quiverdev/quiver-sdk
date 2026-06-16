"""
Web search plugin example for the Quiver SDK.

Adds a web_search tool to the agent via a plugin.
Also demonstrates async plugin setup and configurable tool options.

Usage:
    python examples/plugins/web_search_plugin.py

Install:
    pip install "quiver-sdk[anthropic,http]"
    pip install httpx
    export ANTHROPIC_API_KEY="sk-ant-..."
    export BRAVE_SEARCH_API_KEY="BSA..."  # optional, uses mock if not set
"""

import asyncio
import os
from typing import Optional

from quiver_sdk import Agent, create_tool
from quiver_sdk.types import AgentRuntimePluginContext, AgentRuntimePluginSetup


# ---------------------------------------------------------------------------
# Web search tool implementation
# ---------------------------------------------------------------------------


async def brave_search(query: str, api_key: str, num_results: int = 5) -> list:
    """Search using the Brave Search API."""
    try:
        import httpx
    except ImportError:
        raise ImportError("pip install httpx")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": num_results},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
            }
            for r in results[:num_results]
        ]


async def mock_search(query: str, num_results: int = 5) -> list:
    """Mock search that returns fake results (for testing without an API key)."""
    await asyncio.sleep(0.1)  # simulate latency
    return [
        {
            "title": f"Result {i+1} for: {query}",
            "url": f"https://example.com/result-{i+1}",
            "description": f"This is a mock search result {i+1} for the query '{query}'.",
        }
        for i in range(min(num_results, 3))
    ]


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class WebSearchPlugin:
    """
    Plugin that adds a web_search tool to the agent.

    If BRAVE_SEARCH_API_KEY is set, uses the real Brave Search API.
    Otherwise, falls back to a mock implementation for testing.
    """

    name = "web-search"

    def __init__(
        self,
        api_key: Optional[str] = None,
        num_results: int = 5,
        verbose: bool = True,
    ):
        self._api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        self._num_results = num_results
        self._verbose = verbose
        self._search_count = 0

    async def setup(self, ctx: AgentRuntimePluginContext):
        plugin = self

        async def execute(inp: dict, ctx) -> dict:
            query = inp.get("query", "").strip()
            if not query:
                return {"error": "No search query provided"}

            num = inp.get("num_results", plugin._num_results)
            plugin._search_count += 1

            if plugin._verbose:
                ctx.emit_update(f"Searching for: {query}...")

            try:
                if plugin._api_key:
                    results = await brave_search(query, plugin._api_key, num)
                    source = "Brave Search"
                else:
                    results = await mock_search(query, num)
                    source = "Mock Search (set BRAVE_SEARCH_API_KEY for real results)"

                return {
                    "query": query,
                    "source": source,
                    "results": results,
                    "count": len(results),
                }
            except Exception as e:
                return {"error": str(e), "query": query}

        web_search_tool = create_tool(
            name="web_search",
            description=(
                "Search the web for information on any topic. "
                "Returns titles, URLs, and descriptions of top results. "
                "Use for finding current information, facts, documentation, and news."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": f"Number of results to return (default: {self._num_results})",
                    },
                },
                "required": ["query"],
            },
            execute=execute,
            timeout_ms=15_000,
            retryable=True,
            max_retries=2,
        )

        # Logging hook
        def after_run(c):
            result = c.get("result")
            if result:
                print(
                    f"[web-search] Run complete: {plugin._search_count} searches performed, "
                    f"{result.iterations} iterations"
                )

        return AgentRuntimePluginSetup(
            tools=[web_search_tool],
            hooks={"after_run": after_run},
        )

    @property
    def search_count(self) -> int:
        return self._search_count


# ---------------------------------------------------------------------------
# Completion tool
# ---------------------------------------------------------------------------


finish_tool = create_tool(
    name="submit_answer",
    description="Submit the final researched answer. Call this when you have gathered enough information.",
    input_schema={
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "The complete researched answer"},
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of source URLs used",
            },
        },
        "required": ["answer"],
    },
    lifecycle={"completes_run": True},
    execute=lambda inp, ctx: {
        "submitted": True,
        "answer": inp.get("answer", ""),
        "sources": inp.get("sources", []),
    },
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    search_plugin = WebSearchPlugin(verbose=True)

    agent = Agent(
        provider_id="anthropic",
        model_id="claude-haiku-4-5",
        system_prompt=(
            "You are a research assistant. Use web_search to find accurate, "
            "up-to-date information. Always cite your sources. "
            "When you have a complete answer, call submit_answer."
        ),
        plugins=[search_plugin],
        tools=[finish_tool],
        max_iterations=8,
    )

    question = "What are the top 3 Python async frameworks in 2024?"
    print(f"Question: {question}\n")

    # Stream text output
    agent.subscribe(
        lambda e: print(e["text"], end="", flush=True)
        if e["type"] == "assistant-text-delta" else None
    )

    result = await agent.run(question)

    print(f"\n\nStatus: {result.status}")
    print(f"Iterations: {result.iterations}")
    print(f"Searches performed: {search_plugin.search_count}")
    print(f"Tokens: {result.usage.input_tokens} in / {result.usage.output_tokens} out")
    print(f"\nFinal answer:\n{result.output_text}")


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to run this example.")
        raise SystemExit(1)
    asyncio.run(main())
