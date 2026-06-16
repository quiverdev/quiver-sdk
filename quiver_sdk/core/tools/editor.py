"""
Editor executor for QuiverCore built-in tools.
Mirrors the editor executor from @quiver/core.
"""

from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

from quiver_sdk.types import AgentToolContext


@dataclass
class EditorExecutorOptions:
    """Options for the editor executor."""

    encoding: str = "utf-8"
    restrict_to_cwd: bool = True
    max_diff_lines: int = 200


def _resolve_file_path(cwd: str, input_path: str, restrict_to_cwd: bool) -> str:
    is_absolute = os.path.isabs(input_path)
    resolved = os.path.normpath(input_path if is_absolute else os.path.join(cwd, input_path))

    if not restrict_to_cwd:
        return resolved
    if is_absolute:
        return resolved

    rel = os.path.relpath(resolved, cwd)
    if rel.startswith("..") or os.path.isabs(rel):
        raise ValueError(f"Path must stay within cwd: {input_path}")
    return resolved


def _count_occurrences(content: str, needle: str) -> int:
    if not needle:
        return 0
    return content.count(needle)


def _create_line_diff(old_content: str, new_content: str, max_lines: int) -> str:
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")
    max_len = max(len(old_lines), len(new_lines))
    out = ["```diff"]
    emitted = 0

    for i in range(max_len):
        if emitted >= max_lines:
            out.append("... diff truncated ...")
            break

        old_line = old_lines[i] if i < len(old_lines) else None
        new_line = new_lines[i] if i < len(new_lines) else None

        if old_line == new_line:
            continue

        line_no = i + 1
        if old_line is not None:
            out.append(f"-{line_no}: {old_line}")
            emitted += 1
        if new_line is not None and emitted < max_lines:
            out.append(f"+{line_no}: {new_line}")
            emitted += 1

    out.append("```")
    return "\n".join(out)


def create_editor_executor(cwd: str, options: Optional[EditorExecutorOptions] = None):
    """
    Create a file editor executor.

    Supports operations: view, create, str_replace, insert_line, undo_edit

    Returns an async callable: (input, context) -> str
    """
    opts = options or EditorExecutorOptions()
    encoding = opts.encoding
    restrict_to_cwd = opts.restrict_to_cwd
    max_diff_lines = opts.max_diff_lines

    async def execute(input_data: Dict[str, Any], context: AgentToolContext) -> str:
        command = input_data.get("command", "view")
        path = input_data.get("path", "")
        file_text = input_data.get("file_text")
        old_str = input_data.get("old_str")
        new_str = input_data.get("new_str", "")
        insert_line = input_data.get("insert_line")
        new_str_insert = input_data.get("new_str_insert", "")

        resolved = _resolve_file_path(cwd, path, restrict_to_cwd)

        if command == "view":
            try:
                with open(resolved, "r", encoding=encoding, errors="replace") as f:
                    content = f.read()
                lines = content.split("\n")
                numbered = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines))
                return f"File: {path}\nLines: {len(lines)}\n\n{numbered}"
            except FileNotFoundError:
                return f"Error: File not found: {path}"
            except Exception as e:
                return f"Error reading file: {e}"

        elif command == "create":
            if file_text is None:
                return "Error: file_text is required for create command"
            try:
                os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
                with open(resolved, "w", encoding=encoding) as f:
                    f.write(file_text)
                line_count = file_text.count("\n") + 1
                return f"File created successfully: {path} ({line_count} lines)"
            except Exception as e:
                return f"Error creating file: {e}"

        elif command == "str_replace":
            if old_str is None:
                return "Error: old_str is required for str_replace command"
            try:
                with open(resolved, "r", encoding=encoding, errors="replace") as f:
                    old_content = f.read()

                count = _count_occurrences(old_content, old_str)
                if count == 0:
                    return f"Error: old_str not found in {path}. Make sure it matches exactly."
                if count > 1:
                    return (
                        f"Error: old_str appears {count} times in {path}. "
                        "Provide a more specific string that appears exactly once."
                    )

                new_content = old_content.replace(old_str, new_str, 1)
                with open(resolved, "w", encoding=encoding) as f:
                    f.write(new_content)

                diff = _create_line_diff(old_content, new_content, max_diff_lines)
                return f"Successfully replaced in {path}:\n{diff}"
            except FileNotFoundError:
                return f"Error: File not found: {path}"
            except Exception as e:
                return f"Error editing file: {e}"

        elif command == "insert_line":
            if insert_line is None:
                return "Error: insert_line is required for insert_line command"
            try:
                with open(resolved, "r", encoding=encoding, errors="replace") as f:
                    old_content = f.read()

                lines = old_content.split("\n")
                line_num = int(insert_line)

                if line_num < 0 or line_num > len(lines):
                    return f"Error: Line number {line_num} out of range (0-{len(lines)})"

                lines.insert(line_num, new_str_insert)
                new_content = "\n".join(lines)

                with open(resolved, "w", encoding=encoding) as f:
                    f.write(new_content)

                return f"Successfully inserted line at position {line_num} in {path}"
            except FileNotFoundError:
                return f"Error: File not found: {path}"
            except Exception as e:
                return f"Error inserting line: {e}"

        elif command == "undo_edit":
            return "Error: undo_edit is not supported in the Python SDK (no undo history kept)"

        else:
            return f"Error: Unknown command '{command}'. Supported: view, create, str_replace, insert_line"

    return execute
