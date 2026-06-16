"""
Search executor for QuiverCore built-in tools.
Mirrors the search executor from @quiver/core (uses ripgrep with fallback).
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from quiver_sdk.types import AgentToolContext

MAX_SEARCH_RESULTS = 300
MAX_SEARCH_OUTPUT_CHARS = 51_200


@dataclass
class SearchExecutorOptions:
    """Options for the search executor."""

    max_results: int = MAX_SEARCH_RESULTS
    max_output_chars: int = MAX_SEARCH_OUTPUT_CHARS
    use_ripgrep: bool = True


async def _search_with_ripgrep(
    pattern: str,
    cwd: str,
    include: Optional[str],
    exclude: Optional[str],
    context_lines: int,
    max_results: int,
    max_output_chars: int,
) -> str:
    """Run a ripgrep search."""
    args = [
        "rg",
        "--line-number",
        "--with-filename",
        "--color=never",
        "--smart-case",
        f"--max-count={max_results}",
    ]
    if include:
        args += ["--glob", include]
    if exclude:
        args += ["--glob", f"!{exclude}"]
    if context_lines > 0:
        args += ["-C", str(context_lines)]

    args.append(pattern)

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode("utf-8", errors="replace")
        if len(output) > max_output_chars:
            output = output[:max_output_chars] + f"\n[... output truncated at {max_output_chars} chars ...]"
        return output or "(no matches)"
    except asyncio.TimeoutError:
        raise TimeoutError("Search timed out after 30 seconds")
    except Exception as e:
        raise RuntimeError(f"ripgrep failed: {e}")


async def _search_fallback(
    pattern: str,
    cwd: str,
    include: Optional[str],
    exclude: Optional[str],
    max_results: int,
    max_output_chars: int,
) -> str:
    """Pure-Python regex search fallback."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    results: List[str] = []
    result_count = 0
    total_chars = 0

    # Build include pattern
    include_re = None
    if include:
        # Convert glob to regex
        glob_to_re = include.replace(".", r"\.").replace("*", ".*").replace("?", ".")
        include_re = re.compile(glob_to_re, re.IGNORECASE)

    exclude_re = None
    if exclude:
        glob_to_re = exclude.replace(".", r"\.").replace("*", ".*").replace("?", ".")
        exclude_re = re.compile(glob_to_re, re.IGNORECASE)

    for root, dirs, files in os.walk(cwd):
        # Skip hidden dirs and common large dirs
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "dist", "build")
        ]

        for filename in files:
            if result_count >= max_results:
                break
            if total_chars >= max_output_chars:
                break

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, cwd)

            if include_re and not include_re.match(filename):
                continue
            if exclude_re and exclude_re.match(filename):
                continue

            # Skip binary/large files
            try:
                size = os.path.getsize(filepath)
                if size > 1_000_000:  # skip >1MB
                    continue
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                continue

            for line_no, line in enumerate(lines, 1):
                if regex.search(line):
                    match_line = f"{rel_path}:{line_no}:{line.rstrip()}"
                    results.append(match_line)
                    total_chars += len(match_line)
                    result_count += 1
                    if result_count >= max_results or total_chars >= max_output_chars:
                        break

    if not results:
        return "(no matches)"

    output = "\n".join(results)
    if total_chars >= max_output_chars:
        output += f"\n[... truncated: showing first {max_results} matches ...]"
    return output


def create_search_executor(options: Optional[SearchExecutorOptions] = None):
    """
    Create a search executor.

    Returns an async callable: (query, cwd, context) -> str
    where query is {pattern, include?, exclude?, context_lines?}
    """
    opts = options or SearchExecutorOptions()
    use_ripgrep = opts.use_ripgrep and shutil.which("rg") is not None
    max_results = opts.max_results
    max_output_chars = opts.max_output_chars

    async def execute(query: Any, cwd: str, context: AgentToolContext) -> str:
        if isinstance(query, dict):
            pattern = query.get("pattern", "")
            include = query.get("include")
            exclude = query.get("exclude")
            context_lines = int(query.get("context_lines", 0))
        elif isinstance(query, str):
            pattern = query
            include = None
            exclude = None
            context_lines = 0
        else:
            return "Error: Invalid search query format"

        if not pattern:
            return "Error: Search pattern is required"

        if use_ripgrep:
            try:
                return await _search_with_ripgrep(
                    pattern=pattern,
                    cwd=cwd,
                    include=include,
                    exclude=exclude,
                    context_lines=context_lines,
                    max_results=max_results,
                    max_output_chars=max_output_chars,
                )
            except Exception:
                pass

        # Fallback to Python search
        return await _search_fallback(
            pattern=pattern,
            cwd=cwd,
            include=include,
            exclude=exclude,
            max_results=max_results,
            max_output_chars=max_output_chars,
        )

    return execute
