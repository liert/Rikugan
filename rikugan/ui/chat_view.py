"""Chat view: scrollable area containing message widgets."""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from .qt_compat import (
    QScrollArea, QVBoxLayout, QWidget, QSizePolicy, QTimer, Qt, Signal,
)
from .message_widgets import (
    AssistantMessageWidget, ErrorMessageWidget, ExplorationFindingWidget,
    ExplorationPhaseWidget, QueuedMessageWidget,
    ThinkingWidget, ToolApprovalWidget, ToolCallWidget,
    ToolGroupWidget, UserMessageWidget, UserQuestionWidget,
)
from ..agent.turn import TurnEvent, TurnEventType
from ..core.types import Message, Role
from .plan_view import PlanView

# Collapse consecutive tool runs once they reach this many calls.
_TOOL_GROUP_MIN_CALLS = 1


class ChatView(QScrollArea):
    """Scrollable chat area that renders TurnEvents into widgets."""

    tool_approval_submitted = Signal(str, str)  # (tool_call_id, "allow"/"deny")

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

        # Consecutive tool run state (collapsed when threshold is reached)
        self._tool_run_ids: List[str] = []
        self._tool_run_names: List[str] = []
        self._tool_run_widgets: List[ToolCallWidget] = []
        # Active collapsible group for the current run
        self._tool_group: Optional[ToolGroupWidget] = None
        # Map tool_call_id -> group it belongs to (for result routing/status)
        self._group_map: Dict[str, ToolGroupWidget] = {}

        # Member timer for scroll-to-bottom
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
        self._insert_widget(ErrorMessageWidget(text))
        self._scroll_to_bottom()

    def add_queued_message(self, text: str) -> None:
        self._insert_widget(QueuedMessageWidget(text))
        self._scroll_to_bottom()

    def remove_queued_messages(self) -> None:
        """Remove all [queued] message widgets (e.g. on cancel)."""
        for i in reversed(range(self._layout.count())):
            item = self._layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, QueuedMessageWidget):
                self._layout.removeWidget(widget)
                widget.deleteLater()

    def pop_first_queued_message(self) -> None:
        """Remove the first [queued] widget (when it gets submitted)."""
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, QueuedMessageWidget):
                self._layout.removeWidget(widget)
                widget.deleteLater()
                return

    def _show_thinking(self) -> None:
        if self._thinking is not None:
            return
        self._thinking = ThinkingWidget()
        self._thinking_shown_at = time.monotonic()
        self._insert_widget(self._thinking)
        self._scroll_to_bottom()

    def _hide_thinking(self) -> None:
        if self._thinking is None:
            return
        elapsed_ms = (time.monotonic() - self._thinking_shown_at) * 1000
        if elapsed_ms < 500:
            remaining = int(500 - elapsed_ms)
            self._thinking_hide_timer.start(remaining)
            return
        self._force_hide_thinking()

    def _force_hide_thinking(self) -> None:
        if self._thinking is None:
            return
        self._thinking.stop()
        self._layout.removeWidget(self._thinking)
        self._thinking.deleteLater()
        self._thinking = None

    def _reset_tool_run(self) -> None:
        """End the current consecutive tool run (state only)."""
        self._tool_group = None
        self._tool_run_ids.clear()
        self._tool_run_names.clear()
        self._tool_run_widgets.clear()

    def _register_tool_widget(
        self, tool_name: str, tool_id: str, widget: ToolCallWidget
    ) -> None:
        """Attach a new tool widget to the current run, collapsing at threshold."""
        self._tool_run_ids.append(tool_id)
        self._tool_run_names.append(tool_name)
        self._tool_run_widgets.append(widget)

        run_len = len(self._tool_run_widgets)

        # Below threshold: show tool calls directly.
        if self._tool_group is None and run_len < _TOOL_GROUP_MIN_CALLS:
            self._insert_widget(widget)
            return

        # Threshold reached: move entire run into a new collapsible group.
        if self._tool_group is None and run_len == _TOOL_GROUP_MIN_CALLS:
            self._tool_group = ToolGroupWidget()
            self._insert_widget(self._tool_group)

            for idx, run_widget in enumerate(self._tool_run_widgets):
                self._layout.removeWidget(run_widget)
                run_widget.hide_preview()

                run_tool_id = self._tool_run_ids[idx]
                run_tool_name = self._tool_run_names[idx]
                self._tool_group.add_widget(run_widget, run_tool_name)
                self._group_map[run_tool_id] = self._tool_group
            return

        # Already collapsed: add new call directly to existing group.
        widget.hide_preview()
        self._tool_group.add_widget(widget, tool_name)
        self._group_map[tool_id] = self._tool_group

    def handle_event(self, event: TurnEvent) -> None:
        """Process a TurnEvent and update the UI accordingly."""
        etype = event.type

        if etype == TurnEventType.TEXT_DELTA:
            self._hide_thinking()
            self._reset_tool_run()
            if self._current_assistant is None:
                self._current_assistant = AssistantMessageWidget()
                self._insert_widget(self._current_assistant)
            self._current_assistant.append_text(event.text)
            self._scroll_to_bottom()

        elif etype == TurnEventType.TEXT_DONE:
            self._hide_thinking()
            self._reset_tool_run()
            if self._current_assistant is not None:
                self._current_assistant.set_text(event.text)
            self._current_assistant = None

        elif etype == TurnEventType.TOOL_CALL_START:
            self._hide_thinking()
            tool_name = event.tool_name
            tool_id = event.tool_call_id

            tw = ToolCallWidget(tool_name, tool_id)
            self._tool_widgets[tool_id] = tw
            self._register_tool_widget(tool_name, tool_id, tw)

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
            # A result marks the end of a consecutive tool-call run.
            self._reset_tool_run()
            tw = self._tool_widgets.get(event.tool_call_id)
            if tw:
                tw.set_result(event.tool_result, event.tool_is_error)
            # Notify group if this tool belongs to one
            group = self._group_map.get(event.tool_call_id)
            if group:
                group.notify_result(event.tool_is_error)
            self._scroll_to_bottom()

        elif etype == TurnEventType.TURN_START:
            self._current_assistant = None
            self._reset_tool_run()
            self._group_map.clear()
            self._show_thinking()
            self._scroll_to_bottom()

        elif etype == TurnEventType.TURN_END:
            self._hide_thinking()
            self._reset_tool_run()
            self._current_assistant = None

        elif etype == TurnEventType.ERROR:
            self._hide_thinking()
            self._reset_tool_run()
            self._insert_widget(ErrorMessageWidget(event.error or "Unknown error"))
            self._scroll_to_bottom()

        elif etype == TurnEventType.USER_QUESTION:
            self._hide_thinking()
            self._reset_tool_run()
            options = event.metadata.get("options", [])
            self._insert_widget(UserQuestionWidget(event.text, options))
            self._scroll_to_bottom()

        elif etype == TurnEventType.PLAN_GENERATED:
            self._hide_thinking()
            self._reset_tool_run()
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

        elif etype == TurnEventType.TOOL_APPROVAL_REQUEST:
            self._hide_thinking()
            self._reset_tool_run()
            widget = ToolApprovalWidget(
                event.tool_call_id, event.tool_name,
                event.tool_args, event.text,
            )
            widget.approved.connect(self._on_tool_approval)
            self._insert_widget(widget)
            self._scroll_to_bottom()

        elif etype == TurnEventType.EXPLORATION_PHASE_CHANGE:
            self._hide_thinking()
            self._reset_tool_run()
            meta = event.metadata
            self._insert_widget(ExplorationPhaseWidget(
                meta.get("from_phase", ""),
                meta.get("to_phase", ""),
                event.text,
            ))
            self._scroll_to_bottom()

        elif etype == TurnEventType.EXPLORATION_FINDING:
            meta = event.metadata
            self._insert_widget(ExplorationFindingWidget(
                meta.get("category", "general"),
                event.text,
                meta.get("address"),
                meta.get("relevance", "medium"),
            ))
            self._scroll_to_bottom()

        elif etype == TurnEventType.SAVE_APPROVAL_REQUEST:
            self._hide_thinking()
            self._reset_tool_run()
            # Rendered as a user question with save options
            options = ["Save All", "Discard All"]
            self._insert_widget(UserQuestionWidget(event.text, options))
            self._scroll_to_bottom()

        elif etype == TurnEventType.CANCELLED:
            self._hide_thinking()
            self._reset_tool_run()
            self._insert_widget(ErrorMessageWidget("Cancelled by user"))
            self._scroll_to_bottom()

    def _on_tool_approval(self, tool_call_id: str, decision: str) -> None:
        """Forward tool approval decision to the panel/controller."""
        self.tool_approval_submitted.emit(tool_call_id, decision)

    def restore_from_messages(self, messages: List[Message]) -> None:
        """Replay saved Message objects into the chat view."""
        self.clear_chat()

        for msg in messages:
            if msg.role == Role.USER:
                self._reset_tool_run()
                self.add_user_message(msg.content)

            elif msg.role == Role.ASSISTANT:
                self._reset_tool_run()
                if msg.content:
                    w = AssistantMessageWidget()
                    w.set_text(msg.content)
                    self._insert_widget(w)

                for tc in msg.tool_calls:
                    tw = ToolCallWidget(tc.name, tc.id)
                    try:
                        args_str = json.dumps(tc.arguments, indent=2)
                    except Exception:
                        args_str = str(tc.arguments)
                    tw.set_arguments(args_str)
                    tw.mark_done()
                    self._tool_widgets[tc.id] = tw
                    self._register_tool_widget(tc.name, tc.id, tw)

            elif msg.role == Role.TOOL:
                self._reset_tool_run()
                for tr in msg.tool_results:
                    tw = self._tool_widgets.get(tr.tool_call_id)
                    if tw:
                        tw.set_result(tr.content, tr.is_error)
                    group = self._group_map.get(tr.tool_call_id)
                    if group:
                        group.notify_result(tr.is_error)

        self._current_assistant = None
        self._reset_tool_run()
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
        self._reset_tool_run()
        self._group_map.clear()

    def _insert_widget(self, widget: QWidget) -> None:
        """Insert before the stretch at the end."""
        idx = self._layout.count() - 1
        self._layout.insertWidget(idx, widget)

    def _scroll_to_bottom(self) -> None:
        self._scroll_timer.start()

    def _do_scroll(self) -> None:
        self._container.adjustSize()
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    def shutdown(self) -> None:
        self._scroll_timer.stop()
        self._thinking_hide_timer.stop()
        self._force_hide_thinking()
