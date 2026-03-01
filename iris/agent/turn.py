"""Turn event types emitted by the agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..core.types import TokenUsage


class TurnEventType(str, Enum):
    TEXT_DELTA = "text_delta"
    TEXT_DONE = "text_done"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_ARGS_DELTA = "tool_call_args_delta"
    TOOL_CALL_DONE = "tool_call_done"
    TOOL_RESULT = "tool_result"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    ERROR = "error"
    CANCELLED = "cancelled"
    USAGE_UPDATE = "usage_update"
    USER_QUESTION = "user_question"
    PLAN_GENERATED = "plan_generated"
    PLAN_STEP_START = "plan_step_start"
    PLAN_STEP_DONE = "plan_step_done"


@dataclass
class TurnEvent:
    type: TurnEventType
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_args: str = ""
    tool_result: str = ""
    tool_is_error: bool = False
    error: Optional[str] = None
    usage: Optional[TokenUsage] = None
    turn_number: int = 0
    plan_steps: Optional[List[str]] = None
    plan_step_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def text_delta(text: str) -> "TurnEvent":
        return TurnEvent(type=TurnEventType.TEXT_DELTA, text=text)

    @staticmethod
    def text_done(full_text: str) -> "TurnEvent":
        return TurnEvent(type=TurnEventType.TEXT_DONE, text=full_text)

    @staticmethod
    def tool_call_start(tool_call_id: str, tool_name: str) -> "TurnEvent":
        return TurnEvent(
            type=TurnEventType.TOOL_CALL_START,
            tool_call_id=tool_call_id, tool_name=tool_name,
        )

    @staticmethod
    def tool_call_args_delta(tool_call_id: str, delta: str) -> "TurnEvent":
        return TurnEvent(
            type=TurnEventType.TOOL_CALL_ARGS_DELTA,
            tool_call_id=tool_call_id, tool_args=delta,
        )

    @staticmethod
    def tool_call_done(tool_call_id: str, tool_name: str, args: str) -> "TurnEvent":
        return TurnEvent(
            type=TurnEventType.TOOL_CALL_DONE,
            tool_call_id=tool_call_id, tool_name=tool_name, tool_args=args,
        )

    @staticmethod
    def tool_result_event(
        tool_call_id: str, tool_name: str, result: str, is_error: bool = False,
    ) -> "TurnEvent":
        return TurnEvent(
            type=TurnEventType.TOOL_RESULT,
            tool_call_id=tool_call_id, tool_name=tool_name,
            tool_result=result, tool_is_error=is_error,
        )

    @staticmethod
    def turn_start(turn_number: int) -> "TurnEvent":
        return TurnEvent(type=TurnEventType.TURN_START, turn_number=turn_number)

    @staticmethod
    def turn_end(turn_number: int) -> "TurnEvent":
        return TurnEvent(type=TurnEventType.TURN_END, turn_number=turn_number)

    @staticmethod
    def error_event(error: str) -> "TurnEvent":
        return TurnEvent(type=TurnEventType.ERROR, error=error)

    @staticmethod
    def cancelled_event() -> "TurnEvent":
        return TurnEvent(type=TurnEventType.CANCELLED)

    @staticmethod
    def usage_update(usage: TokenUsage) -> "TurnEvent":
        return TurnEvent(type=TurnEventType.USAGE_UPDATE, usage=usage)

    @staticmethod
    def user_question(question: str, options: Optional[List[str]], tool_call_id: str) -> "TurnEvent":
        return TurnEvent(
            type=TurnEventType.USER_QUESTION,
            text=question, tool_call_id=tool_call_id,
            metadata={"options": options or []},
        )

    @staticmethod
    def plan_generated(steps: List[str]) -> "TurnEvent":
        return TurnEvent(type=TurnEventType.PLAN_GENERATED, plan_steps=steps)

    @staticmethod
    def plan_step_start(index: int, description: str) -> "TurnEvent":
        return TurnEvent(
            type=TurnEventType.PLAN_STEP_START,
            plan_step_index=index, text=description,
        )

    @staticmethod
    def plan_step_done(index: int, result: str) -> "TurnEvent":
        return TurnEvent(
            type=TurnEventType.PLAN_STEP_DONE,
            plan_step_index=index, text=result,
        )
