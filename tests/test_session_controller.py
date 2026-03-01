"""Tests for iris.ui.session_controller."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests.mocks.ida_mock import install_ida_mocks
install_ida_mocks()

from iris.core.config import IRISConfig
from iris.core.types import Message, Role, TokenUsage, ToolCall, ToolResult
from iris.ui.session_controller import SessionController


class TestSessionController(unittest.TestCase):
    def setUp(self):
        self.cfg = IRISConfig()
        self.cfg._config_dir = tempfile.mkdtemp()
        self.ctrl = SessionController(self.cfg)

    def tearDown(self):
        self.ctrl.shutdown()

    def test_initial_session_state(self):
        self.assertIsNotNone(self.ctrl.session)
        self.assertEqual(self.ctrl.session.provider_name, self.cfg.provider.name)
        self.assertEqual(self.ctrl.session.model_name, self.cfg.provider.model)

    def test_is_agent_running_initially_false(self):
        self.assertFalse(self.ctrl.is_agent_running)

    def test_get_event_without_runner_returns_none(self):
        self.assertIsNone(self.ctrl.get_event())

    def test_queue_and_drain_messages(self):
        self.ctrl.queue_message("first")
        self.ctrl.queue_message("second")

        # on_agent_finished pops the first pending message
        next_msg = self.ctrl.on_agent_finished()
        self.assertEqual(next_msg, "first")

        next_msg = self.ctrl.on_agent_finished()
        self.assertEqual(next_msg, "second")

        next_msg = self.ctrl.on_agent_finished()
        self.assertIsNone(next_msg)

    def test_cancel_clears_pending_messages(self):
        self.ctrl.queue_message("will be cancelled")
        self.ctrl.cancel()
        next_msg = self.ctrl.on_agent_finished()
        self.assertIsNone(next_msg)

    def test_new_chat_creates_fresh_session(self):
        old_id = self.ctrl.session.id
        self.ctrl.session.add_message(Message(role=Role.USER, content="hello"))
        self.ctrl.new_chat()

        self.assertNotEqual(self.ctrl.session.id, old_id)
        self.assertEqual(len(self.ctrl.session.messages), 0)

    def test_new_chat_clears_pending_messages(self):
        self.ctrl.queue_message("pending")
        self.ctrl.new_chat()
        self.assertIsNone(self.ctrl.on_agent_finished())

    def test_update_settings_syncs_session(self):
        self.cfg.provider.name = "test_provider"
        self.cfg.provider.model = "test_model"
        self.ctrl.update_settings()

        self.assertEqual(self.ctrl.session.provider_name, "test_provider")
        self.assertEqual(self.ctrl.session.model_name, "test_model")

    def test_skill_slugs_returns_list(self):
        slugs = self.ctrl.skill_slugs
        self.assertIsInstance(slugs, list)

    def test_on_agent_finished_auto_saves(self):
        self.cfg.checkpoint_auto_save = True
        self.ctrl.session.add_message(Message(role=Role.USER, content="test"))
        self.ctrl.on_agent_finished()

        # Verify session was saved to disk
        from iris.state.history import SessionHistory
        history = SessionHistory(self.cfg)
        sessions = history.list_sessions()
        self.assertTrue(any(s["id"] == self.ctrl.session.id for s in sessions))

    def test_restore_session(self):
        # Save a session first
        self.ctrl.session.add_message(Message(role=Role.USER, content="persisted"))
        self.cfg.checkpoint_auto_save = True
        self.ctrl.on_agent_finished()
        saved_id = self.ctrl.session.id

        # New chat, then restore
        self.ctrl.new_chat()
        self.assertNotEqual(self.ctrl.session.id, saved_id)

        restored = self.ctrl.restore_session()
        self.assertIsNotNone(restored)
        self.assertEqual(self.ctrl.session.id, saved_id)
        self.assertEqual(len(self.ctrl.session.messages), 1)
        self.assertEqual(self.ctrl.session.messages[0].content, "persisted")

    def test_restore_preserves_token_usage(self):
        """Full round-trip: save with token usage -> restore -> verify preserved."""
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        self.ctrl.session.add_message(Message(role=Role.USER, content="question"))
        self.ctrl.session.add_message(
            Message(role=Role.ASSISTANT, content="answer", token_usage=usage),
        )
        self.cfg.checkpoint_auto_save = True
        self.ctrl.on_agent_finished()
        saved_id = self.ctrl.session.id

        # Create fresh controller to avoid in-memory state
        ctrl2 = SessionController(self.cfg)
        restored = ctrl2.restore_session()
        self.assertIsNotNone(restored)
        self.assertEqual(restored.id, saved_id)
        self.assertEqual(len(restored.messages), 2)
        self.assertEqual(restored.messages[1].content, "answer")
        ctrl2.shutdown()

    def test_restore_preserves_tool_calls(self):
        """Full round-trip: save with tool calls -> restore -> verify preserved."""
        tc = ToolCall(id="tc_1", name="get_info", arguments={"addr": "0x1000"})
        tr = ToolResult(tool_call_id="tc_1", name="get_info", content="data here")
        self.ctrl.session.add_message(Message(role=Role.USER, content="analyze"))
        self.ctrl.session.add_message(
            Message(role=Role.ASSISTANT, content="", tool_calls=[tc]),
        )
        self.ctrl.session.add_message(Message(role=Role.TOOL, tool_results=[tr]))
        self.cfg.checkpoint_auto_save = True
        self.ctrl.on_agent_finished()

        ctrl2 = SessionController(self.cfg)
        restored = ctrl2.restore_session()
        self.assertIsNotNone(restored)
        self.assertEqual(len(restored.messages), 3)
        self.assertEqual(len(restored.messages[1].tool_calls), 1)
        self.assertEqual(restored.messages[1].tool_calls[0].name, "get_info")
        self.assertEqual(restored.messages[2].tool_results[0].content, "data here")
        ctrl2.shutdown()

    def test_shutdown_is_idempotent(self):
        self.ctrl.shutdown()
        self.ctrl.shutdown()  # Should not raise


if __name__ == "__main__":
    unittest.main()
