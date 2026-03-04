"""Core data types for Rikugan."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]

    @staticmethod
    def make_id() -> str:
        return f"call_{uuid.uuid4().hex[:24]}"


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    token_usage: Optional[TokenUsage] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # Provider-specific raw response data (e.g. Gemini parts with thought_signatures).
    # Not serialized to JSON — only kept in-memory for the current session.
    _raw_parts: Any = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role.value, "id": self.id, "timestamp": self.timestamp}
        if self.content:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        if self.tool_results:
            d["tool_results"] = [
                {"tool_call_id": tr.tool_call_id, "name": tr.name,
                 "content": tr.content, "is_error": tr.is_error}
                for tr in self.tool_results
            ]
        if self.token_usage:
            d["token_usage"] = {
                "prompt_tokens": self.token_usage.prompt_tokens,
                "completion_tokens": self.token_usage.completion_tokens,
                "total_tokens": self.token_usage.total_tokens,
                "cache_read_tokens": self.token_usage.cache_read_tokens,
                "cache_creation_tokens": self.token_usage.cache_creation_tokens,
            }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Message":
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
            for tc in d.get("tool_calls", [])
        ]
        tool_results = [
            ToolResult(
                tool_call_id=tr["tool_call_id"], name=tr["name"],
                content=tr["content"], is_error=tr.get("is_error", False),
            )
            for tr in d.get("tool_results", [])
        ]
        usage = None
        if "token_usage" in d:
            u = d["token_usage"]
            usage = TokenUsage(
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
                cache_read_tokens=u.get("cache_read_tokens", 0),
                cache_creation_tokens=u.get("cache_creation_tokens", 0),
            )
        return cls(
            role=Role(d["role"]),
            content=d.get("content", ""),
            tool_calls=tool_calls,
            tool_results=tool_results,
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
            timestamp=d.get("timestamp", time.time()),
            token_usage=usage,
            id=d.get("id", uuid.uuid4().hex[:12]),
        )


@dataclass
class ProviderCapabilities:
    streaming: bool = True
    tool_use: bool = True
    vision: bool = False
    max_context_window: int = 128000
    max_output_tokens: int = 4096
    supports_system_prompt: bool = True
    supports_cache_control: bool = False


@dataclass
class ModelInfo:
    id: str
    name: str
    provider: str
    context_window: int = 128000
    max_output_tokens: int = 4096
    supports_tools: bool = True
    supports_vision: bool = False


@dataclass
class StreamChunk:
    """A single chunk from a streaming response."""
    text: str = ""
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args_delta: str = ""
    finish_reason: Optional[str] = None
    usage: Optional[TokenUsage] = None
    is_tool_call_start: bool = False
    is_tool_call_end: bool = False
    # Provider-specific raw response parts (e.g. Gemini parts with thought_signatures).
    raw_parts: Any = None
