"""
Bash executor for QuiverCore built-in tools.
Mirrors the bash executor from @quiver/core.
"""

from __future__ import annotations

import asyncio
import math
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from quiver_sdk.exceptions import CommandExitError, TimeoutError as QuiverTimeoutError
from quiver_sdk.types import AgentToolContext
from quiver_sdk.utils import get_default_shell, get_shell_args, truncate_middle

MAX_COMMAND_OUTPUT_CHARS = 51_200  # ~50KB


@dataclass
class BashExecutorOptions:
    """Options for the bash executor."""

    shell: Optional[str] = None
    timeout_ms: int = 30_000
    max_output_bytes: int = MAX_COMMAND_OUTPUT_CHARS
    env: Optional[Dict[str, str]] = None
    combine_output: bool = True


class _RollingCollector:
    """Collects output with a bounded memory budget."""

    def __init__(self, max_chars: int) -> None:
        self._head_limit = math.ceil(max_chars / 2)
        self._tail_limit = max(1, max_chars - self._head_limit)
        self._head = ""
        self._tail = ""
        self._total_chars = 0

    def append(self, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        self._total_chars += len(text)
        head_room = self._head_limit - len(self._head)
        if head_room > 0:
            self._head += text[:head_room]
            self._tail = (self._tail + text[head_room:])[-self._tail_limit:]
        else:
            self._tail = (self._tail + text)[-self._tail_limit:]

    def snapshot(self) -> Dict[str, Any]:
        text = self._head + self._tail
        return {
            "text": text,
            "total_chars": self._total_chars,
            "dropped": self._total_chars > len(text),
        }


async def _spawn_and_collect(
    executable: str,
    args: list,
    cwd: str,
    env: Dict[str, str],
    context: AgentToolContext,
    timeout_ms: int,
    max_output_bytes: int,
    combine_output: bool,
) -> str:
    """Run a subprocess and collect output asynchronously."""
    merged_env = {**os.environ, **env}

    try:
        proc = await asyncio.create_subprocess_exec(
            executable,
            *args,
            cwd=cwd,
            env=merged_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to execute command: {e}")

    stdout_collector = _RollingCollector(max_output_bytes)
    stderr_collector = _RollingCollector(max_output_bytes)

    async def _read_stream(stream: asyncio.StreamReader, collector: _RollingCollector) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            collector.append(chunk)

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(proc.stdout, stdout_collector),
                _read_stream(proc.stderr, stderr_collector),
                proc.wait(),
            ),
            timeout=timeout_ms / 1000,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise QuiverTimeoutError(
            f"Command timed out after {timeout_ms}ms", timeout_ms
        )

    out = stdout_collector.snapshot()
    err = stderr_collector.snapshot()

    if proc.returncode != 0:
        exit_code = proc.returncode or 1
        failure_output = out["text"]
        if combine_output and err["text"]:
            failure_output += f"\n[stderr]\n{err['text']}"
        total = out["total_chars"] + (err["total_chars"] if combine_output else 0)
        if out["dropped"] or (combine_output and err["dropped"]) or len(failure_output) > max_output_bytes:
            failure_output = truncate_middle(failure_output, max_output_bytes, total)
        result = (
            f"[Command exited with code {exit_code}]\n{failure_output}"
            if failure_output
            else f"[Command exited with code {exit_code}]"
        )
        raise CommandExitError(exit_code, result)

    output = out["text"]
    if combine_output and err["text"]:
        output += f"\n[stderr]\n{err['text']}"
    total = out["total_chars"] + (err["total_chars"] if combine_output else 0)
    if out["dropped"] or (combine_output and err["dropped"]) or len(output) > max_output_bytes:
        output = truncate_middle(output, max_output_bytes, total)
    return output


def create_bash_executor(options: Optional[BashExecutorOptions] = None):
    """
    Create a bash executor.

    Returns an async callable: (command, cwd, context) -> str
    """
    opts = options or BashExecutorOptions()
    shell = opts.shell or get_default_shell()
    timeout_ms = opts.timeout_ms
    max_output_bytes = opts.max_output_bytes
    env = opts.env or {}
    combine_output = opts.combine_output

    async def execute(
        command: Any,
        cwd: str,
        context: AgentToolContext,
    ) -> str:
        if isinstance(command, dict):
            executable = command["command"]
            args = command.get("args", [])
        else:
            executable = shell
            args = get_shell_args(shell, str(command))

        return await _spawn_and_collect(
            executable=executable,
            args=args,
            cwd=cwd,
            env=env,
            context=context,
            timeout_ms=timeout_ms,
            max_output_bytes=max_output_bytes,
            combine_output=combine_output,
        )

    return execute
