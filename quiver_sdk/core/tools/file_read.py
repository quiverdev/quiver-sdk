"""
File read executor for QuiverCore built-in tools.
Mirrors the file-read executor from @quiver/core.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from quiver_sdk.types import AgentToolContext

MAX_READ_LINES = 500
MAX_READ_OUTPUT_CHARS = 204_800  # ~200KB

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".bmp", ".ico", ".tiff", ".tif",
}


@dataclass
class FileReadExecutorOptions:
    """Options for the file read executor."""

    encoding: str = "utf-8"
    max_lines: int = MAX_READ_LINES
    max_output_chars: int = MAX_READ_OUTPUT_CHARS


def create_file_read_executor(options: Optional[FileReadExecutorOptions] = None):
    """
    Create a file read executor.

    Returns an async callable: (request, context) -> str
    where request is {path, start_line?, end_line?}
    """
    opts = options or FileReadExecutorOptions()
    encoding = opts.encoding
    max_lines = opts.max_lines
    max_output_chars = opts.max_output_chars

    async def execute(request: Dict[str, Any], context: AgentToolContext) -> str:
        path = request.get("path", "")
        start_line = request.get("start_line")
        end_line = request.get("end_line")

        if not os.path.exists(path):
            return f"Error: File not found: {path}"

        if not os.path.isfile(path):
            return f"Error: Not a file: {path}"

        # Check if image
        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                b64 = base64.b64encode(data).decode("ascii")
                mime_map = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                    ".svg": "image/svg+xml",
                    ".bmp": "image/bmp",
                    ".ico": "image/x-icon",
                    ".tiff": "image/tiff",
                    ".tif": "image/tiff",
                }
                mime = mime_map.get(ext, "image/png")
                return f"data:{mime};base64,{b64}"
            except Exception as e:
                return f"Error reading image: {e}"

        # Read text file
        try:
            with open(path, "r", encoding=encoding, errors="replace") as f:
                all_lines = f.readlines()
        except Exception as e:
            return f"Error reading file: {e}"

        total_lines = len(all_lines)

        # Apply line range
        if start_line is not None or end_line is not None:
            s = max(0, int(start_line or 1) - 1)
            e = min(total_lines, int(end_line or total_lines))
            lines = all_lines[s:e]
            start_offset = s
        else:
            lines = all_lines[:max_lines]
            start_offset = 0

        # Truncate by chars
        output_parts = []
        chars = 0
        truncated_at = None
        for i, line in enumerate(lines):
            if chars + len(line) > max_output_chars:
                truncated_at = start_offset + i + 1
                break
            output_parts.append((start_offset + i + 1, line.rstrip("\n")))
            chars += len(line)

        # Format with line numbers
        numbered = "\n".join(f"{lineno}: {text}" for lineno, text in output_parts)

        meta_parts = [f"File: {path}", f"Total lines: {total_lines}"]
        if start_line or end_line:
            shown_start = (start_line or 1)
            shown_end = output_parts[-1][0] if output_parts else (end_line or total_lines)
            meta_parts.append(f"Showing lines {shown_start}-{shown_end}")

        if total_lines > max_lines and not (start_line or end_line):
            meta_parts.append(
                f"Note: File has {total_lines} lines; showing first {max_lines}. "
                "Use start_line/end_line to page through."
            )

        if truncated_at:
            meta_parts.append(
                f"Note: Output truncated at line {truncated_at} (~{max_output_chars} chars limit)."
            )

        header = "\n".join(meta_parts)
        return f"{header}\n\n{numbered}"

    return execute
