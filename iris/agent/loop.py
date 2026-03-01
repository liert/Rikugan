"""Agent loop: generator-based turn cycle with tool orchestration."""

from __future__ import annotations

import json
import threading
import queue
import traceback
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from ..core.config import IRISConfig
from ..core.errors import AgentError, CancellationError, ProviderError, ToolError
from ..core.logging import log_debug, log_error, log_info
from ..core.types import Message, Role, StreamChunk, TokenUsage, ToolCall, ToolResult
from ..providers.base import LLMProvider
from ..tools.registry import ToolRegistry
from ..skills.registry import SkillRegistry
from .system_prompt import build_system_prompt
from .turn import TurnEvent, TurnEventType
from ..state.session import SessionState


class AgentLoop:
    """The core agentic loop: stream LLM -> execute tools -> repeat.

    Uses a generator pattern to yield TurnEvents to the UI layer.
    Runs in a background thread; IDA API calls are marshalled via @idasync.
    """

    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        config: IRISConfig,
        session: SessionState,
        skill_registry: Optional[SkillRegistry] = None,
    ):
        self.provider = provider
        self.tools = tool_registry
        self.config = config
        self.session = session
        self.skills = skill_registry
        self._cancelled = threading.Event()
        self._running = False
        self._event_queue: queue.Queue[TurnEvent] = queue.Queue()

    @property
    def is_running(self) -> bool:
        return self._running

    def cancel(self) -> None:
        """Cancel the current run."""
        self._cancelled.set()

    def _check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise CancellationError("Agent run cancelled")

    def _build_system_prompt(self) -> str:
        binary_info = None
        current_address = None
        current_function = None

        if self.config.auto_context:
            try:
                binary_info = self.tools.execute("get_binary_info", {})
            except Exception as e:
                log_debug(f"get_binary_info failed: {e}")
            try:
                current_address = self.tools.execute("get_cursor_position", {})
                current_function = self.tools.execute("get_current_function", {})
            except Exception as e:
                log_debug(f"cursor/function context failed: {e}")

        skill_summary = None
        if self.skills:
            skill_summary = self.skills.get_summary_for_prompt()

        return build_system_prompt(
            binary_info=binary_info,
            current_function=current_function,
            current_address=current_address,
            tool_names=self.tools.list_names(),
            skill_summary=skill_summary,
        )

    def _resolve_skill(self, user_message: str) -> str:
        """Rewrite user message if it starts with a /skill slug."""
        if not self.skills:
            return user_message
        skill, remaining = self.skills.resolve_skill_invocation(user_message)
        if skill is None:
            return user_message
        log_debug(f"AgentLoop: skill invocation /{skill.slug}")
        return (
            f"[Skill: {skill.name}]\n"
            f"{skill.body}\n\n"
            f"User request: {remaining}"
        )

    def _stream_llm_turn(
        self, system_prompt: str, tools_schema: Optional[List],
    ) -> Generator[TurnEvent, None, Tuple[str, List[ToolCall], Optional[TokenUsage]]]:
        """Stream one LLM call, yielding events. Returns (text, tool_calls, usage)."""
        assistant_text = ""
        tool_calls: List[ToolCall] = []
        current_tool_args: Dict[str, str] = {}
        current_tool_names: Dict[str, str] = {}
        last_usage: Optional[TokenUsage] = None

        stream = self.provider.chat_stream(
            messages=self.session.get_messages_for_provider(),
            tools=tools_schema if tools_schema else None,
            temperature=self.config.provider.temperature,
            max_tokens=self.config.provider.max_tokens,
            system=system_prompt,
        )

        chunk_count = 0
        for chunk in stream:
            self._check_cancelled()
            chunk_count += 1

            if chunk.text:
                assistant_text += chunk.text
                yield TurnEvent.text_delta(chunk.text)

            if chunk.is_tool_call_start and chunk.tool_call_id:
                current_tool_args[chunk.tool_call_id] = ""
                current_tool_names[chunk.tool_call_id] = chunk.tool_name or ""
                yield TurnEvent.tool_call_start(chunk.tool_call_id, chunk.tool_name or "")

            if chunk.tool_args_delta and chunk.tool_call_id:
                if not chunk.is_tool_call_end:
                    current_tool_args[chunk.tool_call_id] = current_tool_args.get(chunk.tool_call_id, "") + chunk.tool_args_delta
                    yield TurnEvent.tool_call_args_delta(chunk.tool_call_id, chunk.tool_args_delta)

            if chunk.is_tool_call_end and chunk.tool_call_id:
                tc_id = chunk.tool_call_id
                tc_name = current_tool_names.get(tc_id, chunk.tool_name or "")
                raw_args = current_tool_args.get(tc_id, "")
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}

                tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=args))
                yield TurnEvent.tool_call_done(tc_id, tc_name, raw_args)

            if chunk.usage:
                last_usage = chunk.usage
                yield TurnEvent.usage_update(chunk.usage)

        log_debug(f"Stream done: {chunk_count} chunks, {len(assistant_text)} chars, {len(tool_calls)} tool calls")
        return (assistant_text, tool_calls, last_usage)

    def _execute_tool_calls(
        self, tool_calls: List[ToolCall],
    ) -> Generator[TurnEvent, None, List[ToolResult]]:
        """Execute tool calls, yielding result events. Returns ToolResult list."""
        tool_results: List[ToolResult] = []
        for tc in tool_calls:
            self._check_cancelled()

            log_debug(f"Executing tool {tc.name}")
            try:
                result = self.tools.execute(tc.name, tc.arguments)
                is_error = False
            except ToolError as e:
                result = f"Error: {e}"
                is_error = True
                log_error(f"Tool {tc.name} error: {e}")
            except Exception as e:
                result = f"Unexpected error: {e}"
                is_error = True
                log_error(f"Tool {tc.name} unexpected error: {e}\n{traceback.format_exc()}")

            tr = ToolResult(
                tool_call_id=tc.id, name=tc.name,
                content=result, is_error=is_error,
            )
            tool_results.append(tr)
            yield TurnEvent.tool_result_event(tc.id, tc.name, result, is_error)

        return tool_results

    def run(self, user_message: str) -> Generator[TurnEvent, None, None]:
        """Run the agent loop for a user message. Yields TurnEvents.

        This generator should be consumed from a background thread,
        while the UI reads events via the event_queue or directly iterates.
        """
        self._cancelled.clear()
        self._running = True
        self.session.is_running = True

        try:
            user_message = self._resolve_skill(user_message)

            user_msg = Message(role=Role.USER, content=user_message)
            self.session.add_message(user_msg)

            system_prompt = self._build_system_prompt()
            tools_schema = self.tools.to_provider_format()
            log_debug(f"Agent run started: {len(tools_schema)} tools, msg={user_message[:80]!r}")

            turn = 0
            while True:
                self._check_cancelled()
                turn += 1
                self.session.current_turn = turn
                log_debug(f"Turn {turn} start")
                yield TurnEvent.turn_start(turn)

                # Stream LLM response
                assistant_text = ""
                tool_calls: List[ToolCall] = []
                last_usage: Optional[TokenUsage] = None

                try:
                    # yield from propagates streamed TurnEvents to the caller
                    # while the generator's return value (via StopIteration.value)
                    # provides the accumulated result tuple (PEP 380).
                    assistant_text, tool_calls, last_usage = yield from self._stream_llm_turn(
                        system_prompt, tools_schema,
                    )
                except CancellationError:
                    yield TurnEvent.cancelled_event()
                    return
                except ProviderError as e:
                    log_error(f"Provider error: {e}")
                    yield TurnEvent.error_event(str(e))
                    return

                if assistant_text:
                    yield TurnEvent.text_done(assistant_text)

                # Record assistant message
                assistant_msg = Message(
                    role=Role.ASSISTANT,
                    content=assistant_text,
                    tool_calls=tool_calls,
                    token_usage=last_usage,
                )
                self.session.add_message(assistant_msg)

                # If no tool calls, we're done
                if not tool_calls:
                    log_debug(f"Turn {turn} end (final)")
                    yield TurnEvent.turn_end(turn)
                    break

                # Execute tool calls
                tool_results: List[ToolResult] = yield from self._execute_tool_calls(tool_calls)

                # Record tool results as a message
                tool_msg = Message(role=Role.TOOL, tool_results=tool_results)
                self.session.add_message(tool_msg)

                log_debug(f"Turn {turn} end ({len(tool_calls)} tool calls)")
                yield TurnEvent.turn_end(turn)

        except CancellationError:
            yield TurnEvent.cancelled_event()
        except Exception as e:
            log_error(f"Agent loop error: {e}\n{traceback.format_exc()}")
            yield TurnEvent.error_event(str(e))
        finally:
            self._running = False
            self.session.is_running = False


class BackgroundAgentRunner:
    """Runs the AgentLoop in a background thread, bridging to a queue."""

    def __init__(self, agent_loop: AgentLoop):
        self.agent_loop = agent_loop
        self.event_queue: queue.Queue[Optional[TurnEvent]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    def start(self, user_message: str) -> None:
        """Start the agent in a background thread."""
        self._thread = threading.Thread(
            target=self._run, args=(user_message,), daemon=True,
        )
        self._thread.start()

    def _run(self, user_message: str) -> None:
        try:
            for event in self.agent_loop.run(user_message):
                self.event_queue.put(event)
        except Exception as e:
            log_error(f"BackgroundAgentRunner error: {e}\n{traceback.format_exc()}")
            self.event_queue.put(TurnEvent.error_event(str(e)))
        finally:
            self.event_queue.put(None)  # Sentinel

    def cancel(self) -> None:
        self.agent_loop.cancel()

    def get_event(self, timeout: float = 0.1) -> Optional[TurnEvent]:
        """Get the next event, or None if queue is empty."""
        try:
            return self.event_queue.get(timeout=timeout)
        except queue.Empty:
            return None
