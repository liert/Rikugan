"""Chat view: scrollable area containing message widgets."""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from .qt_compat import (
    QScrollArea, QVBoxLayout, QWidget, QSizePolicy, QTimer, Qt,
)
from .message_widgets import (
    AssistantMessageWidget, ErrorMessageWidget, QueuedMessageWidget,
    ThinkingWidget, ToolCallWidget, UserMessageWidget, UserQuestionWidget,
)
from ..agent.turn import TurnEvent, TurnEventType
from ..core.types import Message, Role
from .plan_view import PlanView


class ChatView(QScrollArea):
    """Scrollable chat area that renders TurnEvents into widgets."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("chat_scroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container.setObjectName("chat_container")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)
        self._layout.addStretch()
        self.setWidget(self._container)

        # Track current assistant widget for streaming
        self._current_assistant: Optional[AssistantMessageWidget] = None
        self._tool_widgets: Dict[str, ToolCallWidget] = {}
        self._thinking: Optional[ThinkingWidget] = None
        self._thinking_shown_at: float = 0.0
        self._plan_view: Optional[PlanView] = None

        # Member timer for scroll-to-bottom — child of self, auto-destroyed.
        # Replaces QTimer.singleShot(lambda) which captured `self` and could
        # fire on a dead wrapper if the widget was destroyed within 50ms.
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._do_scroll)

        # Timer for minimum thinking display duration (500ms)
        self._thinking_hide_timer = QTimer(self)
        self._thinking_hide_timer.setSingleShot(True)
        self._thinking_hide_timer.timeout.connect(self._force_hide_thinking)

    def add_user_message(self, text: str) -> None:
        widget = UserMessageWidget(text)
        self._insert_widget(widget)
        self._current_assistant = None

    def add_error_message(self, text: str) -> None:
        """Display an error message in the chat."""
        self._insert_widget(ErrorMessageWidget(text))
        self._scroll_to_bottom()

    def add_queued_message(self, text: str) -> None:
        """Display a queued message with dashed border."""
        self._insert_widget(QueuedMessageWidget(text))
        self._scroll_to_bottom()

    def _show_thinking(self) -> None:
        """Show the animated thinking indicator."""
        if self._thinking is not None:
            return  # already showing
        self._thinking = ThinkingWidget()
        self._thinking_shown_at = time.monotonic()
        self._insert_widget(self._thinking)
        self._scroll_to_bottom()

    def _hide_thinking(self) -> None:
        """Remove the thinking indicator, respecting minimum display time."""
        if self._thinking is None:
            return
        elapsed_ms = (time.monotonic() - self._thinking_shown_at) * 1000
        if elapsed_ms < 500:
            remaining = int(500 - elapsed_ms)
            self._thinking_hide_timer.start(remaining)
            return
        self._force_hide_thinking()

    def _force_hide_thinking(self) -> None:
        """Immediately remove the thinking indicator."""
        if self._thinking is None:
            return
        self._thinking.stop()
        self._layout.removeWidget(self._thinking)
        self._thinking.deleteLater()
        self._thinking = None

    def handle_event(self, event: TurnEvent) -> None:
        """Process a TurnEvent and update the UI accordingly."""
        etype = event.type

        if etype == TurnEventType.TEXT_DELTA:
            self._hide_thinking()  # First text → stop thinking animation
            if self._current_assistant is None:
                self._current_assistant = AssistantMessageWidget()
                self._insert_widget(self._current_assistant)
            self._current_assistant.append_text(event.text)
            self._scroll_to_bottom()

        elif etype == TurnEventType.TEXT_DONE:
            self._hide_thinking()
            if self._current_assistant is not None:
                self._current_assistant.set_text(event.text)
            self._current_assistant = None

        elif etype == TurnEventType.TOOL_CALL_START:
            self._hide_thinking()  # Tool call → stop thinking
            tw = ToolCallWidget(event.tool_name, event.tool_call_id)
            self._tool_widgets[event.tool_call_id] = tw
            self._insert_widget(tw)
            self._scroll_to_bottom()

        elif etype == TurnEventType.TOOL_CALL_ARGS_DELTA:
            tw = self._tool_widgets.get(event.tool_call_id)
            if tw:
                tw.append_args_delta(event.tool_args)

        elif etype == TurnEventType.TOOL_CALL_DONE:
            tw = self._tool_widgets.get(event.tool_call_id)
            if tw:
                tw.set_arguments(event.tool_args)

        elif etype == TurnEventType.TOOL_RESULT:
            tw = self._tool_widgets.get(event.tool_call_id)
            if tw:
                tw.set_result(event.tool_result, event.tool_is_error)
            self._scroll_to_bottom()

        elif etype == TurnEventType.TURN_START:
            self._current_assistant = None
            self._show_thinking()  # New turn → show thinking
            self._scroll_to_bottom()

        elif etype == TurnEventType.TURN_END:
            self._hide_thinking()
            self._current_assistant = None

        elif etype == TurnEventType.ERROR:
            self._hide_thinking()
            self._insert_widget(ErrorMessageWidget(event.error or "Unknown error"))
            self._scroll_to_bottom()

        elif etype == TurnEventType.USER_QUESTION:
            self._hide_thinking()
            options = event.metadata.get("options", [])
            self._insert_widget(UserQuestionWidget(event.text, options))
            self._scroll_to_bottom()

        elif etype == TurnEventType.PLAN_GENERATED:
            self._hide_thinking()
            self._plan_view = PlanView()
            if event.plan_steps:
                self._plan_view.set_plan(event.plan_steps)
            self._insert_widget(self._plan_view)
            self._scroll_to_bottom()

        elif etype == TurnEventType.PLAN_STEP_START:
            if self._plan_view:
                self._plan_view.set_step_status(event.plan_step_index, "active")
                self._plan_view.set_buttons_visible(False)
            self._scroll_to_bottom()

        elif etype == TurnEventType.PLAN_STEP_DONE:
            if self._plan_view:
                self._plan_view.set_step_status(event.plan_step_index, "done")
            self._scroll_to_bottom()

        elif etype == TurnEventType.CANCELLED:
            self._hide_thinking()
            self._insert_widget(ErrorMessageWidget("Cancelled by user"))
            self._scroll_to_bottom()

    def restore_from_messages(self, messages: List[Message]) -> None:
        """Replay saved Message objects into the chat view."""
        self.clear_chat()
        for msg in messages:
            if msg.role == Role.USER:
                self.add_user_message(msg.content)

            elif msg.role == Role.ASSISTANT:
                if msg.content:
                    w = AssistantMessageWidget()
                    w.set_text(msg.content)
                    self._insert_widget(w)
                # Show tool calls as completed widgets
                for tc in msg.tool_calls:
                    tw = ToolCallWidget(tc.name, tc.id)
                    try:
                        tw.set_arguments(json.dumps(tc.arguments, indent=2))
                    except Exception:
                        tw.set_arguments(str(tc.arguments))
                    tw.mark_done()
                    self._tool_widgets[tc.id] = tw
                    self._insert_widget(tw)

            elif msg.role == Role.TOOL:
                for tr in msg.tool_results:
                    tw = self._tool_widgets.get(tr.tool_call_id)
                    if tw:
                        tw.set_result(tr.content, tr.is_error)

        self._current_assistant = None
        self._scroll_to_bottom()

    def clear_chat(self) -> None:
        self._force_hide_thinking()
        self._thinking_hide_timer.stop()
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._current_assistant = None
        self._tool_widgets.clear()
        self._plan_view = None

    def _insert_widget(self, widget: QWidget) -> None:
        """Insert before the stretch at the end."""
        idx = self._layout.count() - 1
        self._layout.insertWidget(idx, widget)

    def _scroll_to_bottom(self) -> None:
        """Schedule a scroll-to-bottom. Restarting the timer debounces."""
        self._scroll_timer.start()

    def _do_scroll(self) -> None:
        self._container.adjustSize()
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    def shutdown(self) -> None:
        """Stop all timers. Call before widget destruction."""
        self._scroll_timer.stop()
        self._thinking_hide_timer.stop()
        self._force_hide_thinking()
