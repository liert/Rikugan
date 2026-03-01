"""Session state management."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..core.types import Message, TokenUsage


@dataclass
class SessionState:
    """Holds the state of one IRIS conversation session."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    messages: List[Message] = field(default_factory=list)
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    current_turn: int = 0
    is_running: bool = False
    provider_name: str = ""
    model_name: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)

    def add_message(self, msg: Message) -> None:
        self.messages.append(msg)
        if msg.token_usage:
            self.total_usage.prompt_tokens += msg.token_usage.prompt_tokens
            self.total_usage.completion_tokens += msg.token_usage.completion_tokens
            self.total_usage.total_tokens += msg.token_usage.total_tokens

    def clear(self) -> None:
        self.messages.clear()
        self.total_usage = TokenUsage()
        self.current_turn = 0
        self.is_running = False

    def get_messages_for_provider(self) -> List[Message]:
        """Return messages in the format expected by providers."""
        return list(self.messages)

    def message_count(self) -> int:
        return len(self.messages)
