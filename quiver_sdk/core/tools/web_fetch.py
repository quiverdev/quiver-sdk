"""
Web fetch executor for QuiverCore built-in tools.
Mirrors the web-fetch executor from @quiver/core.
"""

from __future__ import annotations

import asyncio
import json as json_module
from dataclasses import dataclass
from typing import Any, Dict, Optional

from quiver_sdk.types import AgentToolContext
from quiver_sdk.utils import html_to_text


@dataclass
class WebFetchExecutorOptions:
    """Options for the web fetch executor."""

    timeout_ms: int = 30_000
    max_response_bytes: int = 5_000_000
    user_agent: str = "Mozilla/5.0 (compatible; AgentBot/1.0)"
    headers: Optional[Dict[str, str]] = None
    follow_redirects: bool = True
    max_redirects: int = 5


def create_web_fetch_executor(options: Optional[WebFetchExecutorOptions] = None):
    """
    Create a web fetch executor.

    Returns an async callable: (url, prompt, context) -> str
    """
    opts = options or WebFetchExecutorOptions()
    timeout_ms = opts.timeout_ms
    max_response_bytes = opts.max_response_bytes
    user_agent = opts.user_agent
    extra_headers = opts.headers or {}
    follow_redirects = opts.follow_redirects

    async def execute(url: str, prompt: str, context: AgentToolContext) -> str:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
        except Exception:
            return f"Error: Invalid URL: {url}"

        if parsed.scheme not in ("http", "https"):
            return f"Error: Invalid protocol '{parsed.scheme}'. Only http and https are supported."

        try:
            import aiohttp
        except ImportError:
            # Fallback to urllib
            return await _fetch_with_urllib(
                url=url,
                prompt=prompt,
                timeout_ms=timeout_ms,
                max_response_bytes=max_response_bytes,
                user_agent=user_agent,
                extra_headers=extra_headers,
            )

        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            **extra_headers,
        }

        timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000)
        connector = aiohttp.TCPConnector(limit=10)

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers=headers,
            ) as session:
                async with session.get(
                    url,
                    allow_redirects=follow_redirects,
                ) as response:
                    if response.status >= 400:
                        return f"Error: HTTP {response.status}: {response.reason}"

                    content_type = response.headers.get("Content-Type", "")
                    content_length = int(response.headers.get("Content-Length", 0) or 0)

                    chunks = []
                    total_size = 0
                    async for chunk in response.content.iter_chunked(8192):
                        total_size += len(chunk)
                        if total_size > max_response_bytes:
                            return f"Error: Response too large (exceeded {max_response_bytes} bytes)"
                        chunks.append(chunk)

                    raw_bytes = b"".join(chunks)
                    raw_text = raw_bytes.decode("utf-8", errors="replace")

                    if "text/html" in content_type or "application/xhtml" in content_type:
                        content = html_to_text(raw_text)
                    elif "application/json" in content_type:
                        try:
                            parsed_json = json_module.loads(raw_text)
                            content = json_module.dumps(parsed_json, indent=2)
                        except Exception:
                            content = raw_text
                    else:
                        content = raw_text

                    MAX_CONTENT = 50_000
                    truncated_note = ""
                    if len(content) > MAX_CONTENT:
                        truncated_note = f"\n[Content truncated: showing first {MAX_CONTENT} of {len(content)} characters]"
                        content = content[:MAX_CONTENT]

                    return "\n".join([
                        f"URL: {url}",
                        f"Content-Type: {content_type}",
                        f"Size: {total_size} bytes",
                        "",
                        "--- Content ---",
                        content,
                        truncated_note,
                        "",
                        "--- Analysis Request ---",
                        f"Prompt: {prompt}",
                    ])

        except asyncio.TimeoutError:
            return f"Error: Request timed out after {timeout_ms}ms"
        except Exception as e:
            return f"Error fetching URL: {e}"

    return execute


async def _fetch_with_urllib(
    url: str,
    prompt: str,
    timeout_ms: int,
    max_response_bytes: int,
    user_agent: str,
    extra_headers: Dict[str, str],
) -> str:
    """Fallback HTTP fetch using urllib."""
    import urllib.request
    import asyncio

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,*/*",
        **extra_headers,
    }

    req = urllib.request.Request(url, headers=headers)

    def _blocking_fetch():
        try:
            with urllib.request.urlopen(req, timeout=timeout_ms / 1000) as resp:
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read(max_response_bytes)
                return content_type, raw
        except Exception as e:
            raise RuntimeError(str(e))

    loop = asyncio.get_event_loop()
    try:
        content_type, raw_bytes = await loop.run_in_executor(None, _blocking_fetch)
        raw_text = raw_bytes.decode("utf-8", errors="replace")

        if "text/html" in content_type:
            content = html_to_text(raw_text)
        else:
            content = raw_text

        MAX_CONTENT = 50_000
        if len(content) > MAX_CONTENT:
            content = content[:MAX_CONTENT] + f"\n[truncated at {MAX_CONTENT} chars]"

        return "\n".join([
            f"URL: {url}",
            f"Content-Type: {content_type}",
            "",
            "--- Content ---",
            content,
            "",
            "--- Analysis Request ---",
            f"Prompt: {prompt}",
        ])
    except Exception as e:
        return f"Error fetching URL: {e}"
