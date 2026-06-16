"""
Safety plugin example for the Quiver SDK.

Demonstrates how to use the before_tool hook to intercept and block
dangerous tool calls before they execute. Shows both the dict and
dataclass return forms.

Usage:
    python examples/plugins/safety_plugin.py

Install:
    pip install "quiver-sdk[anthropic]"
    export ANTHROPIC_API_KEY="sk-ant-..."
"""

import asyncio
import os
import re
from typing import List, Optional

from quiver_sdk import Agent, create_tool
from quiver_sdk.types import (
    AgentBeforeToolResult,
    AgentRuntimePluginContext,
    AgentRuntimePluginSetup,
)


# ---------------------------------------------------------------------------
# Safety plugin
# ---------------------------------------------------------------------------


class SafetyPlugin:
    """
    Plugin that intercepts tool calls and blocks dangerous operations.

    Blocks:
    - Dangerous shell commands (rm -rf, sudo, curl | sh, etc.)
    - Path traversal in file operations
    - URLs from blocked domains
    """

    name = "safety"

    BLOCKED_COMMANDS = [
        r"rm\s+-rf",
        r"sudo\s+",
        r"curl\s+.*\|\s*(ba)?sh",
        r"wget\s+.*\|\s*(ba)?sh",
        r">\s*/dev/",
        r"mkfs\.",
        r"dd\s+if=",
        r"format\s+[a-zA-Z]:?\\?",
        r"shutdown\s+-",
        r"reboot\s*$",
    ]

    BLOCKED_DOMAINS = [
        "evil.example.com",
        "malware.test",
    ]

    PATH_TRAVERSAL = re.compile(r"\.\./")

    def __init__(self, blocked_commands: List[str] = None, verbose: bool = True):
        self._blocked = [re.compile(p, re.IGNORECASE) for p in (blocked_commands or self.BLOCKED_COMMANDS)]
        self._verbose = verbose
        self._blocks = []

    async def setup(self, ctx: AgentRuntimePluginContext):
        plugin = self

        def before_tool(c):
            tool_name = c["toolCall"].get("toolName", "")
            inp = c.get("input", {})

            # Check shell commands
            if tool_name in ("run_commands", "bash"):
                cmds = inp.get("commands", inp.get("command", ""))
                if isinstance(cmds, list):
                    cmds = " ".join(str(c) for c in cmds)
                for pattern in plugin._blocked:
                    if pattern.search(str(cmds)):
                        block_msg = f"Blocked dangerous command matching: {pattern.pattern!r}"
                        plugin._blocks.append({"tool": tool_name, "reason": block_msg})
                        if plugin._verbose:
                            print(f"[safety] BLOCKED: {block_msg}")
                        return AgentBeforeToolResult(skip=True)

            # Check file paths for traversal
            if tool_name in ("read_files", "edit_file", "apply_patch"):
                paths = _extract_paths(inp)
                for path in paths:
                    if plugin.PATH_TRAVERSAL.search(str(path)):
                        block_msg = f"Path traversal blocked in: {path!r}"
                        plugin._blocks.append({"tool": tool_name, "reason": block_msg})
                        if plugin._verbose:
                            print(f"[safety] BLOCKED: {block_msg}")
                        return AgentBeforeToolResult(skip=True)

            # Check URLs
            if tool_name in ("fetch_web_content", "web_search"):
                urls = _extract_urls(inp)
                for url in urls:
                    for domain in plugin.BLOCKED_DOMAINS:
                        if domain in str(url):
                            block_msg = f"Blocked domain in URL: {url!r}"
                            plugin._blocks.append({"tool": tool_name, "reason": block_msg})
                            if plugin._verbose:
                                print(f"[safety] BLOCKED: {block_msg}")
                            return AgentBeforeToolResult(skip=True)

            if plugin._verbose:
                print(f"[safety] Allowed: {tool_name}")
            return None  # allow

        def after_run(c):
            if plugin._blocks:
                print(f"[safety] {len(plugin._blocks)} block(s) during this run:")
                for b in plugin._blocks:
                    print(f"  - {b['tool']}: {b['reason']}")
                plugin._blocks.clear()

        return AgentRuntimePluginSetup(
            hooks={
                "before_tool": before_tool,
                "after_run": after_run,
            }
        )


def _extract_paths(inp: dict) -> List[str]:
    paths = []
    for key in ("path", "file_path", "target"):
        if key in inp:
            paths.append(inp[key])
    if "files" in inp:
        files = inp["files"]
        if isinstance(files, list):
            for f in files:
                if isinstance(f, str):
                    paths.append(f)
                elif isinstance(f, dict):
                    paths.append(f.get("path", ""))
        elif isinstance(files, str):
            paths.append(files)
    return paths


def _extract_urls(inp: dict) -> List[str]:
    urls = []
    for key in ("url", "query"):
        if key in inp:
            urls.append(inp[key])
    if "requests" in inp:
        reqs = inp["requests"]
        if isinstance(reqs, list):
            for r in reqs:
                if isinstance(r, dict):
                    urls.append(r.get("url", ""))
                elif isinstance(r, str):
                    urls.append(r)
    return urls


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def make_demo_tools():
    def run_cmd(inp, ctx):
        cmd = inp.get("commands", inp.get("command", ""))
        # In production this would actually run — here it just echoes
        return {"output": f"[would run: {cmd}]", "exit_code": 0}

    def read_file(inp, ctx):
        path = inp.get("path", inp.get("files", ""))
        if isinstance(path, list):
            path = path[0] if path else ""
        return {"content": f"[content of {path}]"}

    finish = create_tool(
        name="finish",
        description="Submit the final answer.",
        input_schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
        lifecycle={"completes_run": True},
        execute=lambda inp, ctx: {"answer": inp["answer"]},
    )

    return [
        create_tool(
            name="run_commands",
            description="Run shell commands.",
            input_schema={"type": "object", "properties": {"commands": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}}, "required": ["commands"]},
            execute=run_cmd,
        ),
        create_tool(
            name="read_files",
            description="Read file contents.",
            input_schema={"type": "object", "properties": {"files": {"type": "string"}}, "required": ["files"]},
            execute=read_file,
        ),
        finish,
    ]


async def main():
    safety = SafetyPlugin(verbose=True)

    agent = Agent(
        provider_id="anthropic",
        model_id="claude-haiku-4-5",
        system_prompt=(
            "You are a system administrator. "
            "Try to: list files, read /etc/passwd, then run 'rm -rf /tmp/*', "
            "then read '../../../etc/shadow', then finish with what you found."
        ),
        tools=make_demo_tools(),
        plugins=[safety],
        max_iterations=8,
    )

    print("Running agent with safety plugin...\n")
    result = await agent.run("Start the sysadmin tasks.")
    print(f"\nStatus: {result.status}")
    print(f"Output: {result.output_text}")


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to run this example.")
        raise SystemExit(1)
    asyncio.run(main())
