"""Tests for the agent loop."""

from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any, Dict, Generator, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests.mocks.ida_mock import install_ida_mocks
install_ida_mocks()

from iris.core.types import (
    Message, ModelInfo, ProviderCapabilities, Role,
    StreamChunk, TokenUsage,
)
from iris.core.config import IRISConfig
from iris.agent.loop import AgentLoop, BackgroundAgentRunner
from iris.agent.turn import TurnEvent, TurnEventType
from iris.tools.base import tool, ParameterSchema, ToolDefinition
from iris.tools.registry import ToolRegistry
from iris.state.session import SessionState
from iris.providers.base import LLMProvider


class MockProvider(LLMProvider):
    """Mock LLM provider that returns scripted responses."""

    def __init__(self, responses: Optional[List[List[StreamChunk]]] = None):
        super().__init__(api_key="test", model="mock-model")
        self._responses = responses or []
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def _get_client(self):
        return None

    def _fetch_models_live(self) -> List[ModelInfo]:
        return [ModelInfo(id="mock-model", name="Mock", provider="mock")]

    @staticmethod
    def _builtin_models() -> List[ModelInfo]:
        return [ModelInfo(id="mock-model", name="Mock", provider="mock")]

    def chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, system=""):
        return Message(role=Role.ASSISTANT, content="mock response")

    def chat_stream(self, messages, tools=None, temperature=0.3, max_tokens=4096, system=""):
        if self._call_count < len(self._responses):
            chunks = self._responses[self._call_count]
            self._call_count += 1
            for chunk in chunks:
                yield chunk
        else:
            yield StreamChunk(text="No more scripted responses.")


def _text_response(text: str) -> List[StreamChunk]:
    """Create a simple text-only response."""
    return [
        StreamChunk(text=text),
        StreamChunk(usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)),
    ]


def _tool_call_response(tool_name: str, args: Dict[str, Any], call_id: str = "call_1") -> List[StreamChunk]:
    """Create a response with a tool call."""
    return [
        StreamChunk(is_tool_call_start=True, tool_call_id=call_id, tool_name=tool_name),
        StreamChunk(tool_args_delta=json.dumps(args), tool_call_id=call_id),
        StreamChunk(is_tool_call_end=True, tool_call_id=call_id, tool_name=tool_name),
        StreamChunk(usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)),
    ]


class TestAgentLoop(unittest.TestCase):
    def _make_loop(self, provider: MockProvider, tools: Optional[ToolRegistry] = None) -> AgentLoop:
        config = IRISConfig()
        config.auto_context = False  # Skip IDA API calls
        session = SessionState(provider_name="mock", model_name="mock-model")
        return AgentLoop(
            provider=provider,
            tool_registry=tools or ToolRegistry(),
            config=config,
            session=session,
        )

    def test_simple_text_response(self):
        provider = MockProvider(responses=[_text_response("Hello!")])
        loop = self._make_loop(provider)

        events = list(loop.run("Hi"))
        types = [e.type for e in events]
        self.assertIn(TurnEventType.TURN_START, types)
        self.assertIn(TurnEventType.TEXT_DELTA, types)
        self.assertIn(TurnEventType.TEXT_DONE, types)
        self.assertIn(TurnEventType.TURN_END, types)

        text_done = next(e for e in events if e.type == TurnEventType.TEXT_DONE)
        self.assertEqual(text_done.text, "Hello!")

    def test_session_records_messages(self):
        provider = MockProvider(responses=[_text_response("Hi there")])
        config = IRISConfig()
        config.auto_context = False
        session = SessionState()
        loop = AgentLoop(provider, ToolRegistry(), config, session)

        list(loop.run("Hello"))
        self.assertEqual(len(session.messages), 2)
        self.assertEqual(session.messages[0].role, Role.USER)
        self.assertEqual(session.messages[0].content, "Hello")
        self.assertEqual(session.messages[1].role, Role.ASSISTANT)
        self.assertEqual(session.messages[1].content, "Hi there")

    def test_tool_call_and_result(self):
        # Set up a tool
        registry = ToolRegistry()
        registry.register(ToolDefinition(
            name="echo_tool",
            description="Echo the input",
            parameters=[ParameterSchema(name="text", type="string", description="Text to echo", required=True)],
            handler=lambda text: f"Echo: {text}",
            category="test",
        ))

        # Turn 1: tool call, Turn 2: text response
        provider = MockProvider(responses=[
            _tool_call_response("echo_tool", {"text": "hello"}, call_id="call_1"),
            _text_response("The echo returned hello"),
        ])
        loop = self._make_loop(provider, tools=registry)

        events = list(loop.run("Echo hello"))
        types = [e.type for e in events]
        self.assertIn(TurnEventType.TOOL_CALL_START, types)
        self.assertIn(TurnEventType.TOOL_CALL_DONE, types)
        self.assertIn(TurnEventType.TOOL_RESULT, types)

        tool_result = next(e for e in events if e.type == TurnEventType.TOOL_RESULT)
        self.assertEqual(tool_result.tool_result, "Echo: hello")
        self.assertFalse(tool_result.tool_is_error)

    def test_tool_error(self):
        registry = ToolRegistry()
        registry.register(ToolDefinition(
            name="failing_tool",
            description="Always fails",
            parameters=[],
            handler=lambda: (_ for _ in ()).throw(ValueError("bad input")),
            category="test",
        ))

        provider = MockProvider(responses=[
            _tool_call_response("failing_tool", {}, call_id="call_1"),
            _text_response("Tool failed"),
        ])
        loop = self._make_loop(provider, tools=registry)

        events = list(loop.run("Run failing tool"))
        tool_result = next(e for e in events if e.type == TurnEventType.TOOL_RESULT)
        self.assertTrue(tool_result.tool_is_error)

    def test_cancellation_mid_tool_loop(self):
        """Cancel during a multi-turn tool loop."""
        registry = ToolRegistry()

        def cancel_handler():
            # Cancel during tool execution
            loop.cancel()
            return "done"

        registry.register(ToolDefinition(
            name="cancel_trigger",
            description="Triggers cancel",
            parameters=[],
            handler=cancel_handler,
            category="test",
        ))

        provider = MockProvider(responses=[
            _tool_call_response("cancel_trigger", {}, call_id="call_1"),
            _text_response("Should not reach"),
        ])
        loop = self._make_loop(provider, tools=registry)

        events = list(loop.run("Trigger cancel"))
        types = [e.type for e in events]
        self.assertIn(TurnEventType.CANCELLED, types)
        # Should not reach the second response
        self.assertNotIn(TurnEventType.TEXT_DONE, types)

    def test_is_running_flag(self):
        provider = MockProvider(responses=[_text_response("Done")])
        loop = self._make_loop(provider)
        self.assertFalse(loop.is_running)

        events = list(loop.run("Hi"))
        self.assertFalse(loop.is_running)

    def test_usage_tracked(self):
        provider = MockProvider(responses=[_text_response("Hi")])
        config = IRISConfig()
        config.auto_context = False
        session = SessionState()
        loop = AgentLoop(provider, ToolRegistry(), config, session)

        events = list(loop.run("Hello"))
        usage_events = [e for e in events if e.type == TurnEventType.USAGE_UPDATE]
        self.assertTrue(len(usage_events) > 0)
        self.assertEqual(session.total_usage.total_tokens, 15)


class TestBackgroundAgentRunner(unittest.TestCase):
    def test_run_in_background(self):
        provider = MockProvider(responses=[_text_response("Background response")])
        config = IRISConfig()
        config.auto_context = False
        session = SessionState()
        loop = AgentLoop(provider, ToolRegistry(), config, session)
        runner = BackgroundAgentRunner(loop)

        runner.start("Hello from background")

        events = []
        while True:
            event = runner.get_event(timeout=2.0)
            if event is None:
                break
            events.append(event)

        types = [e.type for e in events]
        self.assertIn(TurnEventType.TEXT_DONE, types)
        text_done = next(e for e in events if e.type == TurnEventType.TEXT_DONE)
        self.assertEqual(text_done.text, "Background response")


class TestSkillInvocation(unittest.TestCase):
    def test_skill_rewrite(self):
        """Test that /slug messages get rewritten with skill body."""
        import tempfile
        from iris.skills.registry import SkillRegistry

        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "test-skill")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: Test Skill\ndescription: A test\n---\nYou are a test skill.\n")

            registry = SkillRegistry(tmpdir)
            registry.discover()

            provider = MockProvider(responses=[_text_response("Skill response")])
            config = IRISConfig()
            config.auto_context = False
            session = SessionState()
            loop = AgentLoop(provider, ToolRegistry(), config, session, skill_registry=registry)

            list(loop.run("/test-skill do something"))

            # The user message in session should contain the skill body
            user_msg = session.messages[0]
            self.assertIn("[Skill: Test Skill]", user_msg.content)
            self.assertIn("You are a test skill.", user_msg.content)
            self.assertIn("do something", user_msg.content)


if __name__ == "__main__":
    unittest.main()
