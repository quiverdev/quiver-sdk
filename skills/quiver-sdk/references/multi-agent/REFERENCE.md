# Multi-Agent Coordination

The Quiver SDK supports building multi-agent systems in Python using asyncio concurrency. Common patterns include sub-agents (parent-child delegation) and fan-out (parallel execution).

## Sub-Agents (Parent-Child)

A parent agent can spawn sub-agents as tools. The sub-agent runs to completion and returns its result to the parent:

```python
import asyncio
from src import Agent, create_tool, AgentToolContext

def make_sub_agent_tool(sub_agent_config: dict):
    """Create a tool that runs a sub-agent."""

    async def execute(inp: dict, ctx: AgentToolContext) -> dict:
        sub = Agent(
            provider_id=sub_agent_config["provider_id"],
            model_id=sub_agent_config["model_id"],
            system_prompt=sub_agent_config.get("system_prompt", ""),
            tools=sub_agent_config.get("tools", []),
            max_iterations=sub_agent_config.get("max_iterations", 10),
            agent_role="sub-agent",
            parent_agent_id=ctx.agent_id,
        )

        task = inp.get("task", "")
        ctx.emit_update(f"Sub-agent starting: {task[:50]}...")

        result = await sub.run(task)
        return {
            "status": result.status,
            "output": result.output_text,
            "iterations": result.iterations,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        }

    return create_tool(
        name="delegate_task",
        description=(
            "Delegate a specific subtask to a specialized sub-agent. "
            "The sub-agent will independently work on the task and return its result. "
            "Use for tasks that require different expertise or can be parallelized."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Clear, self-contained task description for the sub-agent",
                },
            },
            "required": ["task"],
        },
        execute=execute,
        timeout_ms=300_000,  # 5 minutes
    )

# Orchestrator agent
orchestrator = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    system_prompt=(
        "You are an orchestrator. Break down complex tasks and delegate to sub-agents. "
        "Synthesize their results into a coherent final answer."
    ),
    tools=[
        make_sub_agent_tool({
            "provider_id": "anthropic",
            "model_id": "claude-haiku-4-5",
            "system_prompt": "You are a web researcher. Find and summarize information.",
            "max_iterations": 5,
        })
    ],
)

result = await orchestrator.run("Research and summarize the latest developments in quantum computing.")
print(result.output_text)
```

## Fan-Out (Parallel Execution)

Run multiple specialized agents in parallel and combine results:

```python
import asyncio
from src import Agent

async def parallel_agents(prompt: str) -> dict:
    # Create specialized agents
    researcher = Agent(
        provider_id="anthropic",
        model_id="claude-haiku-4-5",
        system_prompt="You are a research assistant. Find factual information.",
        agent_role="researcher",
    )
    analyst = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are an analyst. Provide deep analysis and insights.",
        agent_role="analyst",
    )
    writer = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt="You are a technical writer. Write clear, structured content.",
        agent_role="writer",
    )

    # Run all in parallel
    results = await asyncio.gather(
        researcher.run(f"Research: {prompt}"),
        analyst.run(f"Analyze the implications of: {prompt}"),
        writer.run(f"Write an introduction about: {prompt}"),
    )

    return {
        "research": results[0].output_text,
        "analysis": results[1].output_text,
        "introduction": results[2].output_text,
    }

outputs = await parallel_agents("artificial general intelligence")
print(outputs["research"])
print(outputs["analysis"])
```

## Supervisor Pattern

A supervisor agent reviews and refines the output of a worker agent:

```python
import asyncio
from src import Agent

async def supervised_run(task: str) -> str:
    # Worker produces initial output
    worker = Agent(
        provider_id="anthropic",
        model_id="claude-haiku-4-5",
        system_prompt="You are a code generator. Write clean, working Python code.",
        agent_role="worker",
    )
    worker_result = await worker.run(task)

    # Supervisor reviews and improves
    supervisor = Agent(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        system_prompt=(
            "You are a code reviewer. Review the provided code and either approve it "
            "or improve it. Return the final, production-ready version."
        ),
        agent_role="supervisor",
    )
    review_result = await supervisor.run(
        f"Review this code:\n\n{worker_result.output_text}"
    )

    return review_result.output_text

code = await supervised_run("Write a Python function that validates email addresses")
print(code)
```

## Pipeline (Sequential)

Chain agents where each output feeds the next:

```python
import asyncio
from src import Agent

async def pipeline(user_input: str) -> str:
    stages = [
        ("requirements_analyst", "Extract clear technical requirements from the user's request."),
        ("architect", "Design a system architecture for these requirements."),
        ("implementer", "Implement the solution based on this architecture."),
        ("reviewer", "Review this implementation and provide the final polished version."),
    ]

    current_input = user_input

    for role, system_prompt in stages:
        agent = Agent(
            provider_id="anthropic",
            model_id="claude-sonnet-4-6",
            system_prompt=system_prompt,
            agent_role=role,
        )
        result = await agent.run(current_input)
        print(f"[{role}] complete ({result.iterations} iterations)")
        current_input = result.output_text

    return current_input

final = await pipeline("Build me a REST API for a todo app")
print(final)
```

## Multi-Session QuiverCore Teams

Using QuiverCore with multiple sessions for persistent team memory:

```python
import asyncio
from src import QuiverCore

async def team_run(task: str):
    async with QuiverCore.create(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        enable_tools=True,
        db_path="/tmp/team.db",
    ) as core:
        # Create specialized sessions
        researcher_session = await core.start({
            "system_prompt": "You are a research specialist. Focus on gathering information."
        })
        coder_session = await core.start({
            "system_prompt": "You are a Python expert. Write clean, tested code."
        })
        reviewer_session = await core.start({
            "system_prompt": "You are a code reviewer. Ensure quality and correctness."
        })

        # Sequential handoffs
        r1 = await core.send(researcher_session.session_id, f"Research: {task}")
        r2 = await core.send(coder_session.session_id, f"Implement based on this research:\n{r1.output_text}")
        r3 = await core.send(reviewer_session.session_id, f"Review:\n{r2.output_text}")

        return r3.output_text

result = await team_run("Build a web scraper for news articles")
print(result)
```

## Tips for Multi-Agent Systems

1. **Set `agent_role`** — helps with logging, metrics, and event filtering
2. **Use `max_iterations`** — prevent runaway agents in sub-agent tools
3. **Handle failures** — check `result.status` before passing to the next stage
4. **Isolate state** — each `Agent` has its own message history; don't share agents across calls
5. **Cost awareness** — parallel agents multiply your token usage; monitor with event subscriptions
6. **Set tool timeouts** — sub-agent tools should have generous `timeout_ms` values
