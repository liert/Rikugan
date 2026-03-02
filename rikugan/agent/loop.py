"""Agent loop: generator-based turn cycle with tool orchestration."""

from __future__ import annotations

import json
import threading
import queue
import traceback
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from ..core.config import RikuganConfig
from ..core.errors import AgentError, CancellationError, ProviderError, ToolError
from ..core.logging import log_debug, log_error, log_info
from ..core.types import Message, Role, StreamChunk, TokenUsage, ToolCall, ToolResult
from ..providers.base import LLMProvider
from ..tools.registry import ToolRegistry
from ..skills.registry import SkillRegistry
from .system_prompt import build_system_prompt
from .turn import TurnEvent, TurnEventType
from ..state.session import SessionState

_PLAN_GENERATION_PROMPT = (
    "You are in PLAN MODE. Analyze the user's request and create a numbered "
    "step-by-step plan. Output ONLY the plan as a numbered list, one step per "
    "line. Do NOT execute any tools. Do NOT include commentary before or after "
    "the plan. Example format:\n"
    "1. Decompile function at 0x401000\n"
    "2. Identify string references\n"
    "3. Rename variables based on analysis\n"
)

_STEP_EXECUTION_PROMPT = (
    "You are executing step {index} of a plan.\n"
    "Step: {description}\n\n"
    "Execute this step using the available tools. When done, provide a brief "
    "summary of what you accomplished."
)


class AgentLoop:
    """The core agentic loop: stream LLM -> execute tools -> repeat.

    Uses a generator pattern to yield TurnEvents to the UI layer.
    Runs in a background thread; IDA API calls are marshalled via @idasync.
    """

    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        config: RikuganConfig,
        session: SessionState,
        skill_registry: Optional[SkillRegistry] = None,
        host_name: str = "IDA Pro",
    ):
        self.provider = provider
        self.tools = tool_registry
        self.config = config
        self.session = session
        self.skills = skill_registry
        self.host_name = host_name
        self._cancelled = threading.Event()
        self._running = False
        self._consecutive_errors = 0
        self._tools_disabled_for_turn = False
        self._event_queue: queue.Queue[TurnEvent] = queue.Queue()
        self._user_answer_event = threading.Event()
        self._user_answer: Optional[str] = None
        self.plan_mode = False

        # Tool approval state (for execute_python)
        self._tool_approval_event = threading.Event()
        self._tool_approved: Optional[str] = None  # "allow" or "deny"

    @property
    def is_running(self) -> bool:
        return self._running

    def cancel(self) -> None:
        """Cancel the current run."""
        self._cancelled.set()

    def submit_user_answer(self, answer: str) -> None:
        """Submit an answer to an ask_user question (called from UI thread)."""
        self._user_answer = answer
        self._user_answer_event.set()

    def submit_tool_approval(self, decision: str) -> None:
        """Submit tool approval decision: 'allow', 'allow_all', or 'deny'."""
        self._tool_approved = decision
        self._tool_approval_event.set()

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
            host_name=self.host_name,
            binary_info=binary_info,
            current_function=current_function,
            current_address=current_address,
            tool_names=self.tools.list_names(),
            skill_summary=skill_summary,
        )

    def _resolve_skill(self, user_message: str) -> tuple:
        """Rewrite user message if it starts with a /skill slug.

        Returns (rewritten_message, skill_or_None).
        """
        if not self.skills:
            return (user_message, None)
        skill, remaining = self.skills.resolve_skill_invocation(user_message)
        if skill is None:
            return (user_message, None)
        log_debug(f"AgentLoop: skill invocation /{skill.slug}")
        rewritten = (
            f"[Skill: {skill.name}]\n"
            f"{skill.body}\n\n"
            f"User request: {remaining}"
        )
        return (rewritten, skill)

    @staticmethod
    def _parse_plan(text: str) -> List[str]:
        """Parse a numbered plan from LLM text into step strings."""
        import re
        steps = []
        for line in text.strip().splitlines():
            line = line.strip()
            m = re.match(r"^\d+[.)]\s+(.+)", line)
            if m:
                steps.append(m.group(1).strip())
        return steps

    def _execute_step(
        self,
        step_index: int,
        step_desc: str,
        system_prompt: str,
        tools_schema: List,
    ) -> Generator[TurnEvent, None, None]:
        """Execute a single plan step using a mini agent loop."""
        yield TurnEvent.plan_step_start(step_index, step_desc)

        step_prompt = _STEP_EXECUTION_PROMPT.format(
            index=step_index + 1, description=step_desc,
        )
        step_msg = Message(role=Role.USER, content=step_prompt)
        self.session.add_message(step_msg)

        max_step_turns = 20
        for _st in range(max_step_turns):
            self._check_cancelled()
            yield TurnEvent.turn_start(_st + 1)

            try:
                assistant_text, tool_calls, last_usage = yield from self._stream_llm_turn(
                    system_prompt, tools_schema,
                )
            except CancellationError:
                yield TurnEvent.cancelled_event()
                return
            except ProviderError as e:
                yield TurnEvent.error_event(str(e))
                return

            if assistant_text:
                yield TurnEvent.text_done(assistant_text)

            assistant_msg = Message(
                role=Role.ASSISTANT, content=assistant_text,
                tool_calls=tool_calls, token_usage=last_usage,
            )
            self.session.add_message(assistant_msg)

            if not tool_calls:
                yield TurnEvent.turn_end(_st + 1)
                break

            tool_results: List[ToolResult] = yield from self._execute_tool_calls(tool_calls)
            tool_msg = Message(role=Role.TOOL, tool_results=tool_results)
            self.session.add_message(tool_msg)
            yield TurnEvent.turn_end(_st + 1)

        yield TurnEvent.plan_step_done(step_index, "completed")

    def _run_plan_mode(
        self,
        user_message: str,
        system_prompt: str,
        tools_schema: List,
    ) -> Generator[TurnEvent, None, None]:
        """Run the agent in plan mode: generate plan, get approval, execute steps."""
        # Phase 1: Generate plan (text-only)
        plan_prompt = _PLAN_GENERATION_PROMPT + f"\n\nUser request: {user_message}"
        plan_msg = Message(role=Role.USER, content=plan_prompt)
        self.session.add_message(plan_msg)

        yield TurnEvent.turn_start(1)
        try:
            plan_text, _, usage = yield from self._stream_llm_turn(system_prompt, None)
        except (CancellationError, ProviderError) as e:
            yield TurnEvent.error_event(str(e))
            return

        if plan_text:
            yield TurnEvent.text_done(plan_text)

        plan_msg_resp = Message(role=Role.ASSISTANT, content=plan_text, token_usage=usage)
        self.session.add_message(plan_msg_resp)
        yield TurnEvent.turn_end(1)

        steps = self._parse_plan(plan_text)
        if not steps:
            yield TurnEvent.error_event("Failed to generate a valid plan.")
            return

        yield TurnEvent.plan_generated(steps)

        # Phase 2: Get user approval via ask_user mechanism
        yield TurnEvent.user_question(
            "Do you want to execute this plan?",
            ["Approve", "Reject"],
            "__plan_approval__",
        )

        self._user_answer_event.clear()
        self._user_answer = None
        while not self._user_answer_event.wait(0.5):
            self._check_cancelled()

        answer = (self._user_answer or "").strip().lower()
        if answer not in ("approve", "1", "yes", "y"):
            yield TurnEvent.error_event("Plan rejected by user.")
            return

        # Phase 3: Execute each step
        for i, step_desc in enumerate(steps):
            self._check_cancelled()
            yield from self._execute_step(i, step_desc, system_prompt, tools_schema)

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

    @staticmethod
    def _describe_tool_call(name: str, args: Dict[str, Any]) -> str:
        """Generate a brief human-readable description of what a tool will do."""
        if name == "execute_python":
            code = args.get("code", args.get("script", ""))
            lines = code.strip().splitlines()
            if len(lines) <= 3:
                return f"Run Python code:\n{code.strip()}"
            preview = "\n".join(lines[:3])
            return f"Run Python code ({len(lines)} lines):\n{preview}\n..."
        if name in ("rename_function",):
            return f"Rename function {args.get('old_name', '?')} → {args.get('new_name', '?')}"
        if name in ("rename_variable", "rename_single_variable"):
            return f"Rename variable {args.get('variable_name', '?')} → {args.get('new_name', '?')}"
        if name in ("set_comment", "set_function_comment"):
            return f"Set comment at {args.get('address', args.get('function_name', '?'))}"
        if name in ("set_type", "set_function_prototype"):
            return f"Set type at {args.get('ea', args.get('name_or_address', '?'))}"
        if name in ("nop_microcode", "nop_instructions"):
            return f"NOP instructions at {args.get('address', args.get('ea', '?'))}"
        if name in ("create_struct", "create_enum"):
            return f"Create {name.split('_')[1]} '{args.get('name', '?')}'"
        if name in ("decompile_function", "fetch_disassembly"):
            return f"Decompile/disassemble {args.get('name', args.get('address', '?'))}"
        # Generic
        summary_parts = []
        for k in ("name", "address", "ea", "target", "query"):
            if k in args:
                summary_parts.append(f"{k}={args[k]}")
                break
        return f"Call {name}({', '.join(summary_parts)})" if summary_parts else f"Call {name}"

    def _wait_for_approval(
        self, tc: ToolCall,
    ) -> Generator[TurnEvent, None, bool]:
        """Yield an approval request and wait for the user decision.

        Returns True if approved, False if denied.
        """
        args_str = json.dumps(tc.arguments, indent=2)
        description = self._describe_tool_call(tc.name, tc.arguments)
        yield TurnEvent.tool_approval_request(tc.id, tc.name, args_str, description)

        self._tool_approval_event.clear()
        self._tool_approved = None
        while not self._tool_approval_event.wait(0.5):
            self._check_cancelled()

        decision = (self._tool_approved or "deny").lower()
        return decision == "allow"

    def _execute_tool_calls(
        self, tool_calls: List[ToolCall],
    ) -> Generator[TurnEvent, None, List[ToolResult]]:
        """Execute tool calls, yielding result events. Returns ToolResult list."""
        tool_results: List[ToolResult] = []
        for tc in tool_calls:
            self._check_cancelled()

            # ask_user: block until the UI delivers an answer
            if tc.name == "ask_user":
                question = tc.arguments.get("question", "")
                options = tc.arguments.get("options", [])
                yield TurnEvent.user_question(question, options, tc.id)

                self._user_answer_event.clear()
                self._user_answer = None
                while not self._user_answer_event.wait(0.5):
                    self._check_cancelled()

                answer = self._user_answer or ""
                tr = ToolResult(
                    tool_call_id=tc.id, name=tc.name,
                    content=f"User answered: {answer}", is_error=False,
                )
                tool_results.append(tr)
                yield TurnEvent.tool_result_event(tc.id, tc.name, tr.content, False)
                continue

            # Tool approval gate — execute_python always needs explicit approval
            if tc.name == "execute_python":
                approved = yield from self._wait_for_approval(tc)
                if not approved:
                    tr = ToolResult(
                        tool_call_id=tc.id, name=tc.name,
                        content="Tool execution denied by user.", is_error=True,
                    )
                    tool_results.append(tr)
                    yield TurnEvent.tool_result_event(tc.id, tc.name, tr.content, True)
                    continue

            log_debug(f"Executing tool {tc.name}")
            try:
                result = self.tools.execute(tc.name, tc.arguments)
                is_error = False
                self._consecutive_errors = 0
            except ToolError as e:
                result = f"Error: {e}"
                is_error = True
                self._consecutive_errors += 1
                log_error(f"Tool {tc.name} error: {e}")
            except Exception as e:
                result = f"Unexpected error: {e}"
                is_error = True
                self._consecutive_errors += 1
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
            # Detect /plan prefix before skill resolution
            use_plan_mode = False
            stripped = user_message.strip()
            if stripped.lower().startswith("/plan "):
                use_plan_mode = True
                user_message = stripped[6:].strip()

            user_message, active_skill = self._resolve_skill(user_message)

            user_msg = Message(role=Role.USER, content=user_message)
            self.session.add_message(user_msg)

            system_prompt = self._build_system_prompt()
            tools_schema = self.tools.to_provider_format()

            # If active skill has allowed_tools, filter to only those
            if active_skill and active_skill.allowed_tools:
                allowed = set(active_skill.allowed_tools)
                tools_schema = [
                    t for t in tools_schema
                    if t.get("function", {}).get("name") in allowed
                ]

            # Append the ask_user pseudo-tool so the LLM can ask the user
            _ASK_USER_SCHEMA = {
                "type": "function",
                "function": {
                    "name": "ask_user",
                    "description": (
                        "Ask the user a question and wait for their answer. "
                        "Use this when you need clarification, confirmation, "
                        "or a choice from the user before proceeding."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The question to ask the user.",
                            },
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of choices for the user.",
                            },
                        },
                        "required": ["question"],
                    },
                },
            }
            tools_schema.append(_ASK_USER_SCHEMA)

            log_debug(f"Agent run started: {len(tools_schema)} tools, msg={user_message[:80]!r}")

            # Plan mode: generate plan → approval → step-by-step execution
            if use_plan_mode or self.plan_mode:
                yield from self._run_plan_mode(user_message, system_prompt, tools_schema)
                return

            max_turns = 100
            turn = 0
            while True:
                self._check_cancelled()
                turn += 1
                if turn > max_turns:
                    yield TurnEvent.error_event(f"Reached max turns limit ({max_turns}).")
                    break
                self.session.current_turn = turn
                log_debug(f"Turn {turn} start")
                yield TurnEvent.turn_start(turn)

                # Stream LLM response
                assistant_text = ""
                tool_calls: List[ToolCall] = []
                last_usage: Optional[TokenUsage] = None

                # If tools were disabled due to consecutive errors, run
                # text-only so the agent is forced to explain the problem.
                turn_tools = None if self._tools_disabled_for_turn else tools_schema
                self._tools_disabled_for_turn = False

                try:
                    # yield from propagates streamed TurnEvents to the caller
                    # while the generator's return value (via StopIteration.value)
                    # provides the accumulated result tuple (PEP 380).
                    assistant_text, tool_calls, last_usage = yield from self._stream_llm_turn(
                        system_prompt, turn_tools,
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
                    self._consecutive_errors = 0
                    log_debug(f"Turn {turn} end (final)")
                    yield TurnEvent.turn_end(turn)
                    break

                # Execute tool calls
                tool_results: List[ToolResult] = yield from self._execute_tool_calls(tool_calls)

                # Record tool results as a message
                tool_msg = Message(role=Role.TOOL, tool_results=tool_results)
                self.session.add_message(tool_msg)

                # Consecutive error recovery: hint at 3, force text-only at 5
                if self._consecutive_errors >= 5:
                    self._tools_disabled_for_turn = True
                    self._consecutive_errors = 0
                    hint = Message(
                        role=Role.USER,
                        content=(
                            "[SYSTEM] You have failed 5 consecutive tool calls. "
                            "Tools are temporarily disabled. Explain what went wrong "
                            "and what you were trying to do. The user may help you. "
                            "Tools will be re-enabled on your next turn."
                        ),
                    )
                    self.session.add_message(hint)
                elif self._consecutive_errors >= 3:
                    hint = Message(
                        role=Role.USER,
                        content=(
                            "[SYSTEM] You have failed 3 consecutive tool calls. "
                            "Stop retrying the same approach. Try a different strategy "
                            "or explain what is failing."
                        ),
                    )
                    self.session.add_message(hint)

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
