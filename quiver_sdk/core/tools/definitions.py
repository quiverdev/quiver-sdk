"""
Default tool definitions for QuiverCore.
Creates the full set of built-in tools using executor functions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from quiver_sdk.tools import create_tool
from quiver_sdk.types import AgentTool, AgentToolContext
from quiver_sdk.exceptions import CommandExitError, TimeoutError as QuiverTimeoutError
from quiver_sdk.core.tools.bash import create_bash_executor, BashExecutorOptions, MAX_COMMAND_OUTPUT_CHARS
from quiver_sdk.core.tools.editor import create_editor_executor, EditorExecutorOptions
from quiver_sdk.core.tools.file_read import create_file_read_executor, FileReadExecutorOptions, MAX_READ_LINES, MAX_READ_OUTPUT_CHARS
from quiver_sdk.core.tools.search import create_search_executor, SearchExecutorOptions
from quiver_sdk.core.tools.web_fetch import create_web_fetch_executor, WebFetchExecutorOptions
from quiver_sdk.core.tools.apply_patch import create_apply_patch_executor


@dataclass
class DefaultToolsConfig:
    """Configuration for the built-in tool suite."""

    cwd: str = field(default_factory=os.getcwd)
    bash_timeout_ms: int = 30_000
    file_read_timeout_ms: int = 10_000
    search_timeout_ms: int = 30_000
    web_fetch_timeout_ms: int = 30_000
    max_output_chars: int = MAX_COMMAND_OUTPUT_CHARS
    shell: Optional[str] = None
    enable_bash: bool = True
    enable_editor: bool = True
    enable_read_files: bool = True
    enable_search: bool = True
    enable_web_fetch: bool = True
    enable_apply_patch: bool = True
    extra_env: Optional[Dict[str, str]] = None


def _format_error(error: Any) -> str:
    return str(error) if error else "Unknown error"


def create_read_files_tool(executor, config: Optional[Dict[str, Any]] = None) -> AgentTool:
    """Create the read_files tool."""
    cfg = config or {}
    timeout_ms = cfg.get("file_read_timeout_ms", 10_000)

    async def execute(input_data: Any, context: AgentToolContext) -> List[Dict[str, Any]]:
        requests = []
        if isinstance(input_data, str):
            requests = [{"path": input_data}]
        elif isinstance(input_data, list):
            requests = [
                {"path": r} if isinstance(r, str) else r
                for r in input_data
            ]
        elif isinstance(input_data, dict):
            if "files" in input_data:
                files = input_data["files"]
                if not isinstance(files, list):
                    files = [files]
                requests = [{"path": f} if isinstance(f, str) else f for f in files]
            elif "paths" in input_data:
                paths = input_data["paths"]
                if not isinstance(paths, list):
                    paths = [paths]
                requests = [{"path": p} if isinstance(p, str) else p for p in paths]
            elif "file_paths" in input_data:
                fps = input_data["file_paths"]
                if not isinstance(fps, list):
                    fps = [fps]
                requests = [{"path": p} for p in fps]
            elif "path" in input_data:
                requests = [input_data]
            else:
                requests = [input_data]
        else:
            requests = [{"path": str(input_data)}]

        results = []
        for req in requests:
            path = req.get("path", "") if isinstance(req, dict) else str(req)
            query = f"read_file({path})"
            try:
                import asyncio
                content = await asyncio.wait_for(
                    executor(req if isinstance(req, dict) else {"path": str(req)}, context),
                    timeout=timeout_ms / 1000,
                )
                results.append({"query": query, "result": content, "success": True})
            except Exception as e:
                results.append({
                    "query": query,
                    "result": "",
                    "error": f"Error reading file: {_format_error(e)}",
                    "success": False,
                })
        return results

    return create_tool(
        name="read_files",
        description=(
            f"Read the content of text or image files at the provided absolute paths, "
            "or return only an inclusive one-based line range when start_line/end_line are provided. "
            "When you already know multiple files you need, read them together in one call. "
            f"Each read returns at most {MAX_READ_LINES} lines / ~{MAX_READ_OUTPUT_CHARS // 1024}k characters; "
            "longer files report their total line count — page through them with start_line/end_line. "
            "Binary files that are not images and large files are not supported. "
            "Returns file contents or error messages for each path."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "files": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "array",
                            "items": {
                                "oneOf": [
                                    {"type": "string"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "path": {"type": "string"},
                                            "start_line": {"type": "integer"},
                                            "end_line": {"type": "integer"},
                                        },
                                        "required": ["path"],
                                    },
                                ]
                            },
                        },
                    ],
                    "description": "File path(s) to read",
                }
            },
        },
        execute=execute,
        timeout_ms=timeout_ms * 2,
        retryable=True,
        max_retries=1,
    )


def create_search_codebase_tool(executor, config: Optional[Dict[str, Any]] = None) -> AgentTool:
    """Create the search_codebase tool."""
    cfg = config or {}
    timeout_ms = cfg.get("search_timeout_ms", 30_000)
    cwd = cfg.get("cwd", os.getcwd())

    async def execute(input_data: Any, context: AgentToolContext) -> List[Dict[str, Any]]:
        queries = []
        if isinstance(input_data, str):
            queries = [{"pattern": input_data}]
        elif isinstance(input_data, list):
            queries = [{"pattern": q} if isinstance(q, str) else q for q in input_data]
        elif isinstance(input_data, dict):
            if "queries" in input_data:
                qs = input_data["queries"]
                if not isinstance(qs, list):
                    qs = [qs]
                queries = [{"pattern": q} if isinstance(q, str) else q for q in qs]
            elif "pattern" in input_data:
                queries = [input_data]
            else:
                queries = [input_data]

        results = []
        for query in queries:
            q_str = str(query)
            try:
                import asyncio
                result = await asyncio.wait_for(
                    executor(query, cwd, context),
                    timeout=timeout_ms / 1000,
                )
                results.append({"query": q_str, "result": result, "success": True})
            except Exception as e:
                results.append({
                    "query": q_str,
                    "result": "",
                    "error": f"Search failed: {_format_error(e)}",
                    "success": False,
                })
        return results

    return create_tool(
        name="search_codebase",
        description=(
            "Perform regex pattern searches across the codebase. "
            "Supports multiple parallel searches. When several patterns are needed and do not depend on each other, run them together in one call. "
            "Use for finding code patterns, function definitions, class names, imports, etc."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "queries": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                                "include": {"type": "string", "description": "Glob pattern to include files"},
                                "exclude": {"type": "string", "description": "Glob pattern to exclude files"},
                                "context_lines": {"type": "integer", "description": "Lines of context around matches"},
                            },
                            "required": ["pattern"],
                        },
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "pattern": {"type": "string"},
                                    "include": {"type": "string"},
                                    "exclude": {"type": "string"},
                                },
                                "required": ["pattern"],
                            },
                        },
                    ],
                    "description": "Search query or queries",
                }
            },
        },
        execute=execute,
        timeout_ms=timeout_ms * 2,
        retryable=True,
        max_retries=1,
    )


def create_run_commands_tool(executor, config: Optional[Dict[str, Any]] = None) -> AgentTool:
    """Create the run_commands tool."""
    cfg = config or {}
    timeout_ms = cfg.get("bash_timeout_ms", 30_000)
    cwd = cfg.get("cwd", os.getcwd())

    async def execute(input_data: Any, context: AgentToolContext) -> List[Dict[str, Any]]:
        commands = []
        if isinstance(input_data, str):
            commands = [input_data]
        elif isinstance(input_data, list):
            commands = [c if isinstance(c, str) else json.dumps(c) for c in input_data]
        elif isinstance(input_data, dict):
            if "commands" in input_data:
                cmds = input_data["commands"]
                if not isinstance(cmds, list):
                    cmds = [cmds]
                commands = [c if isinstance(c, str) else json.dumps(c) for c in cmds]
            elif "command" in input_data:
                commands = [input_data["command"]]
            elif "cmd" in input_data:
                commands = [input_data["cmd"]]
            else:
                commands = [json.dumps(input_data)]

        results = []
        for command in commands:
            query = str(command)[:80] + "..." if len(str(command)) > 80 else str(command)
            try:
                import asyncio
                output = await asyncio.wait_for(
                    executor(command, cwd, context),
                    timeout=timeout_ms / 1000,
                )
                results.append({"query": query, "result": output, "success": True})
            except asyncio.TimeoutError:
                results.append({
                    "query": query,
                    "result": "",
                    "error": f"Command timed out after {timeout_ms}ms",
                    "success": False,
                })
            except QuiverTimeoutError as e:
                results.append({
                    "query": query,
                    "result": "",
                    "error": str(e),
                    "success": False,
                })
            except CommandExitError as e:
                results.append({
                    "query": query,
                    "result": e.output,
                    "error": str(e),
                    "success": False,
                })
            except Exception as e:
                results.append({
                    "query": query,
                    "result": "",
                    "error": f"Command failed: {_format_error(e)}",
                    "success": False,
                })
        return results

    return create_tool(
        name="run_commands",
        description=(
            "Run shell commands from the root of the workspace. "
            "Use for listing files, checking git status, running builds, executing tests, etc. "
            "Commands should be properly shell-escaped. Include multiple commands when they are independent and safe to run concurrently. "
            f"Output beyond ~{MAX_COMMAND_OUTPUT_CHARS // 1000}k characters is middle-truncated; "
            "pipe through grep/head/tail when you need specific sections of large output."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "commands": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Shell command(s) to run",
                }
            },
        },
        execute=execute,
        timeout_ms=timeout_ms * 2,
        retryable=False,
        max_retries=0,
    )


def create_edit_file_tool(executor, config: Optional[Dict[str, Any]] = None) -> AgentTool:
    """Create the edit_file tool."""
    cfg = config or {}

    async def execute(input_data: Dict[str, Any], context: AgentToolContext) -> str:
        return await executor(input_data, context)

    return create_tool(
        name="edit_file",
        description=(
            "Edit files using view, create, str_replace, or insert_line commands. "
            "Use 'view' to see file content with line numbers. "
            "Use 'create' to create a new file or overwrite an existing one. "
            "Use 'str_replace' to replace an exact string (must appear exactly once). "
            "Use 'insert_line' to insert a new line at a specific position."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["view", "create", "str_replace", "insert_line"],
                    "description": "The editor command to run",
                },
                "path": {"type": "string", "description": "File path"},
                "file_text": {"type": "string", "description": "File content for create command"},
                "old_str": {"type": "string", "description": "Text to replace for str_replace command"},
                "new_str": {"type": "string", "description": "Replacement text for str_replace command"},
                "insert_line": {"type": "integer", "description": "Line number to insert at"},
                "new_str_insert": {"type": "string", "description": "Text to insert"},
            },
            "required": ["command", "path"],
        },
        execute=execute,
        timeout_ms=30_000,
        retryable=True,
        max_retries=1,
    )


def create_fetch_web_content_tool(executor, config: Optional[Dict[str, Any]] = None) -> AgentTool:
    """Create the fetch_web_content tool."""
    cfg = config or {}
    timeout_ms = cfg.get("web_fetch_timeout_ms", 30_000)

    async def execute(input_data: Any, context: AgentToolContext) -> List[Dict[str, Any]]:
        requests = []
        if isinstance(input_data, dict):
            if "requests" in input_data:
                reqs = input_data["requests"]
                if not isinstance(reqs, list):
                    reqs = [reqs]
                requests = reqs
            elif "url" in input_data:
                requests = [input_data]
            else:
                requests = [input_data]
        elif isinstance(input_data, list):
            requests = input_data
        else:
            requests = [{"url": str(input_data), "prompt": ""}]

        results = []
        for req in requests:
            url = req.get("url", "") if isinstance(req, dict) else str(req)
            prompt = req.get("prompt", "") if isinstance(req, dict) else ""
            try:
                import asyncio
                result = await asyncio.wait_for(
                    executor(url, prompt, context),
                    timeout=timeout_ms / 1000,
                )
                results.append({"query": url, "result": result, "success": True})
            except Exception as e:
                results.append({
                    "query": url,
                    "result": "",
                    "error": f"Fetch failed: {_format_error(e)}",
                    "success": False,
                })
        return results

    return create_tool(
        name="fetch_web_content",
        description=(
            "Fetch content from URLs and analyze them using the provided prompts. "
            "Use for retrieving documentation, API references, or any web content. "
            "Each request includes a URL and a prompt describing what information to extract. "
            "Fetch independent URLs together in one call."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "requests": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string"},
                                "prompt": {"type": "string"},
                            },
                            "required": ["url"],
                        },
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string"},
                                    "prompt": {"type": "string"},
                                },
                                "required": ["url"],
                            },
                        },
                    ],
                    "description": "URL fetch request(s)",
                }
            },
        },
        execute=execute,
        timeout_ms=timeout_ms * 2,
        retryable=True,
        max_retries=1,
    )


def create_apply_patch_tool(executor) -> AgentTool:
    """Create the apply_patch tool."""

    async def execute(input_data: Any, context: AgentToolContext) -> str:
        return await executor(input_data, context)

    return create_tool(
        name="apply_patch",
        description=(
            "Apply a patch to files in the workspace. "
            "Supports ADD, UPDATE (with hunk-based edits), DELETE, and MOVE operations. "
            "Use for applying structured file changes when str_replace would be too verbose."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "The patch text in the custom patch grammar",
                }
            },
            "required": ["patch"],
        },
        execute=execute,
        timeout_ms=30_000,
        retryable=True,
        max_retries=1,
    )


def create_default_tools(config: Optional[DefaultToolsConfig] = None) -> List[AgentTool]:
    """
    Create the full set of default built-in tools.

    Args:
        config: Configuration for the tool suite

    Returns:
        List of AgentTool instances
    """
    cfg = config or DefaultToolsConfig()
    cwd = cfg.cwd
    tool_cfg = {
        "cwd": cwd,
        "bash_timeout_ms": cfg.bash_timeout_ms,
        "file_read_timeout_ms": cfg.file_read_timeout_ms,
        "search_timeout_ms": cfg.search_timeout_ms,
        "web_fetch_timeout_ms": cfg.web_fetch_timeout_ms,
    }

    tools = []

    if cfg.enable_read_files:
        file_read_executor = create_file_read_executor(
            FileReadExecutorOptions(encoding="utf-8")
        )
        tools.append(create_read_files_tool(file_read_executor, tool_cfg))

    if cfg.enable_search:
        search_executor = create_search_executor(SearchExecutorOptions())
        tools.append(create_search_codebase_tool(search_executor, tool_cfg))

    if cfg.enable_bash:
        bash_executor = create_bash_executor(
            BashExecutorOptions(
                timeout_ms=cfg.bash_timeout_ms,
                max_output_bytes=cfg.max_output_chars,
                shell=cfg.shell,
                env=cfg.extra_env or {},
            )
        )
        tools.append(create_run_commands_tool(bash_executor, tool_cfg))

    if cfg.enable_editor:
        editor_executor = create_editor_executor(cwd, EditorExecutorOptions())
        tools.append(create_edit_file_tool(editor_executor, tool_cfg))

    if cfg.enable_web_fetch:
        web_fetch_executor = create_web_fetch_executor(
            WebFetchExecutorOptions(timeout_ms=cfg.web_fetch_timeout_ms)
        )
        tools.append(create_fetch_web_content_tool(web_fetch_executor, tool_cfg))

    if cfg.enable_apply_patch:
        apply_patch_executor = create_apply_patch_executor(cwd)
        tools.append(create_apply_patch_tool(apply_patch_executor))

    return tools
