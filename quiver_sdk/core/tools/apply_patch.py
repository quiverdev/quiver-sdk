"""
Apply patch executor for QuiverCore built-in tools.
Mirrors the apply-patch executor from @quiver/core.

Supports a custom patch grammar with ADD, UPDATE, DELETE, MOVE operations.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from quiver_sdk.types import AgentToolContext


def _parse_patch(patch_text: str) -> List[Dict[str, Any]]:
    """
    Parse a custom patch format.

    Grammar:
      *** Begin Patch
      *** Add File: path/to/file
      [file content]
      *** End of file
      *** Update File: path/to/file
      *** Delete File: path/to/file
      ...
      *** End Patch
    """
    operations = []
    lines = patch_text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("*** Add File:"):
            path = line[len("*** Add File:"):].strip()
            content_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("***"):
                content_lines.append(lines[i])
                i += 1
            # Strip trailing "*** End of file" if present
            operations.append({
                "op": "add",
                "path": path,
                "content": "\n".join(content_lines),
            })

        elif line.startswith("*** Update File:"):
            path = line[len("*** Update File:"):].strip()
            hunks = []
            i += 1
            current_hunk: Optional[Dict] = None

            while i < len(lines) and not lines[i].strip().startswith("*** ") or \
                  (i < len(lines) and lines[i].strip().startswith("***") and
                   not any(lines[i].strip().startswith(f"*** {k}") for k in
                           ["Add File", "Update File", "Delete File", "Move File", "End Patch"])):
                l = lines[i]

                if l.startswith("@@") or l.strip().startswith("---") or l.strip().startswith("+++"):
                    if current_hunk:
                        hunks.append(current_hunk)
                    current_hunk = {"context": [], "removals": [], "additions": []}
                    i += 1
                    continue

                if current_hunk is not None:
                    if l.startswith("-"):
                        current_hunk["removals"].append(l[1:])
                    elif l.startswith("+"):
                        current_hunk["additions"].append(l[1:])
                    else:
                        current_hunk["context"].append(l.lstrip(" "))
                i += 1

            if current_hunk:
                hunks.append(current_hunk)

            operations.append({
                "op": "update",
                "path": path,
                "hunks": hunks,
            })
            continue

        elif line.startswith("*** Delete File:"):
            path = line[len("*** Delete File:"):].strip()
            operations.append({"op": "delete", "path": path})
            i += 1

        elif line.startswith("*** Move File:"):
            # Format: *** Move File: old_path -> new_path
            rest = line[len("*** Move File:"):].strip()
            parts = rest.split("->")
            if len(parts) == 2:
                operations.append({
                    "op": "move",
                    "from": parts[0].strip(),
                    "to": parts[1].strip(),
                })
            i += 1

        else:
            i += 1

    return operations


def _apply_hunk(content: str, hunk: Dict[str, Any]) -> Tuple[str, bool]:
    """Apply a single hunk to file content."""
    removals = hunk.get("removals", [])
    additions = hunk.get("additions", [])
    context = hunk.get("context", [])

    if not removals and not additions:
        return content, True

    if removals:
        # Find the removal block in the content
        search_block = "\n".join(removals)
        if search_block in content:
            replacement = "\n".join(additions)
            new_content = content.replace(search_block, replacement, 1)
            return new_content, True
        else:
            # Fuzzy matching: try stripping leading/trailing whitespace from each line
            stripped_removals = [l.strip() for l in removals]
            lines = content.splitlines()
            for i in range(len(lines) - len(stripped_removals) + 1):
                window = [l.strip() for l in lines[i:i + len(stripped_removals)]]
                if window == stripped_removals:
                    new_lines = lines[:i] + additions + lines[i + len(stripped_removals):]
                    return "\n".join(new_lines), True
            return content, False
    elif additions:
        # Pure addition: append to file
        return content + "\n" + "\n".join(additions), True

    return content, False


def create_apply_patch_executor(cwd: str):
    """
    Create an apply-patch executor.

    Returns an async callable: (patch_text, context) -> str
    """
    async def execute(patch_input: Any, context: AgentToolContext) -> str:
        if isinstance(patch_input, dict):
            patch_text = patch_input.get("patch", "") or patch_input.get("diff", "")
        elif isinstance(patch_input, str):
            patch_text = patch_input
        else:
            return "Error: Invalid patch input"

        if not patch_text:
            return "Error: Empty patch"

        operations = _parse_patch(patch_text)
        if not operations:
            return "Error: No valid patch operations found"

        results = []
        for op in operations:
            operation = op.get("op", "")
            path = op.get("path", op.get("from", ""))
            abs_path = path if os.path.isabs(path) else os.path.join(cwd, path)

            if operation == "add":
                try:
                    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
                    with open(abs_path, "w", encoding="utf-8") as f:
                        f.write(op.get("content", ""))
                    results.append(f"✓ Added: {path}")
                except Exception as e:
                    results.append(f"✗ Failed to add {path}: {e}")

            elif operation == "delete":
                try:
                    if os.path.exists(abs_path):
                        os.remove(abs_path)
                        results.append(f"✓ Deleted: {path}")
                    else:
                        results.append(f"⚠ File not found (already deleted?): {path}")
                except Exception as e:
                    results.append(f"✗ Failed to delete {path}: {e}")

            elif operation == "move":
                from_path = op.get("from", "")
                to_path = op.get("to", "")
                abs_from = from_path if os.path.isabs(from_path) else os.path.join(cwd, from_path)
                abs_to = to_path if os.path.isabs(to_path) else os.path.join(cwd, to_path)
                try:
                    os.makedirs(os.path.dirname(abs_to) or ".", exist_ok=True)
                    os.rename(abs_from, abs_to)
                    results.append(f"✓ Moved: {from_path} → {to_path}")
                except Exception as e:
                    results.append(f"✗ Failed to move {from_path}: {e}")

            elif operation == "update":
                try:
                    if not os.path.exists(abs_path):
                        results.append(f"✗ File not found: {path}")
                        continue

                    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()

                    failed_hunks = 0
                    for hunk in op.get("hunks", []):
                        content, success = _apply_hunk(content, hunk)
                        if not success:
                            failed_hunks += 1

                    with open(abs_path, "w", encoding="utf-8") as f:
                        f.write(content)

                    if failed_hunks:
                        results.append(f"⚠ Updated {path} ({failed_hunks} hunk(s) failed to apply)")
                    else:
                        results.append(f"✓ Updated: {path}")
                except Exception as e:
                    results.append(f"✗ Failed to update {path}: {e}")

        return "\n".join(results) if results else "No operations performed"

    return execute
