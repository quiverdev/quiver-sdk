"""
Utility functions for the Quiver SDK.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from typing import Any, Optional

from nanoid import generate as _nanoid


def create_uid(prefix: str, length: int = 8) -> str:
    """Create a unique ID with a prefix."""
    return f"{prefix}_{_nanoid(size=length)}"


def estimate_tokens(char_count: int) -> int:
    """Rough estimate of token count from character count (1 token ≈ 4 chars)."""
    return math.ceil(char_count / 4)


def safe_json_stringify(value: Any) -> str:
    """JSON-serialize a value, handling non-serializable objects."""
    try:
        return json.dumps(value)
    except Exception:
        return str(value)


def get_output_size(output: Any) -> int:
    """Get the character size of a tool output."""
    if isinstance(output, str):
        return len(output)
    return len(safe_json_stringify(output))


def clone_messages(messages: list) -> list:
    """Deep clone a list of agent messages."""
    import copy
    return copy.deepcopy(messages)


def clone_usage(usage: Any) -> Any:
    """Clone a usage object."""
    import copy
    return copy.copy(usage)


def get_default_shell() -> str:
    """Get the default shell for the current platform."""
    if os.name == "nt":
        return "powershell"
    shell = os.environ.get("SHELL", "/bin/bash")
    return shell


def get_shell_args(shell: str, command: str) -> list[str]:
    """Get shell arguments for running a command."""
    if "powershell" in shell.lower():
        return ["-Command", command]
    return ["-c", command]


def truncate_middle(text: str, max_chars: int, total_chars: int) -> str:
    """Middle-truncate text, preserving head and tail."""
    head_limit = math.ceil(max_chars / 2)
    tail_limit = max(1, max_chars - head_limit)
    return (
        f"{text[:head_limit]}\n"
        f"[... output truncated: {total_chars} chars total. "
        "Refine the command (grep, head, tail) to view the elided middle ...]\n"
        f"{text[-tail_limit:]}"
    )


def html_to_text(html: str) -> str:
    """Simple HTML to plain text converter."""
    text = html
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    text = re.sub(r"<(p|div|br|hr|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def with_timeout(coro: Any, timeout_ms: int, message: str) -> Any:
    """Run a coroutine with a timeout."""
    from quiver_sdk.exceptions import TimeoutError as QuiverTimeoutError
    try:
        return await asyncio.wait_for(coro, timeout=timeout_ms / 1000)
    except asyncio.TimeoutError:
        raise QuiverTimeoutError(message, timeout_ms)


def text_from_message(message: Any) -> str:
    """Extract text content from an AgentMessage."""
    if message is None:
        return ""
    parts = message.content if hasattr(message, "content") else message.get("content", [])
    texts = []
    for part in parts:
        t = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
        if t == "text":
            texts.append(part.get("text", "") if isinstance(part, dict) else part.text)
    return "".join(texts)


def mask_secret(secret: str, visible: int = 4) -> str:
    """Mask a secret, showing only the last `visible` characters."""
    if len(secret) <= visible:
        return "*" * len(secret)
    return "*" * (len(secret) - visible) + secret[-visible:]
