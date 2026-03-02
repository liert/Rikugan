"""System prompt builder with binary context awareness."""

from __future__ import annotations

from typing import List, Optional

from ..constants import SYSTEM_PROMPT_VERSION
from .prompts.binja import BINJA_BASE_PROMPT
from .prompts.ida import IDA_BASE_PROMPT

_HOST_PROMPTS = {"IDA Pro": IDA_BASE_PROMPT, "Binary Ninja": BINJA_BASE_PROMPT}
_BASE_PROMPT = IDA_BASE_PROMPT  # backward compat alias


def build_system_prompt(
    host_name: str = "IDA Pro",
    binary_info: Optional[str] = None,
    current_function: Optional[str] = None,
    current_address: Optional[str] = None,
    extra_context: Optional[str] = None,
    tool_names: Optional[List[str]] = None,
    skill_summary: Optional[str] = None,
) -> str:
    """Build the full system prompt with optional binary context."""
    base_prompt = _HOST_PROMPTS.get(host_name, IDA_BASE_PROMPT)
    parts = [base_prompt]

    if binary_info:
        parts.append(f"\n## Current Binary\n{binary_info}")

    if current_address:
        parts.append(f"\n## Current Position\nAddress: {current_address}")
        if current_function:
            parts.append(f"Function: {current_function}")

    if tool_names:
        parts.append(f"\n## Available Tools\n{', '.join(tool_names)}")

    if skill_summary:
        parts.append(f"\n## Skills\n{skill_summary}")

    if extra_context:
        parts.append(f"\n## Additional Context\n{extra_context}")

    return "\n".join(parts)
