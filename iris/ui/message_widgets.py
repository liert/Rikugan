"""Message display widgets for the chat view."""

from __future__ import annotations

import random

from .qt_compat import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QToolButton,
    QWidget, QSizePolicy, Qt, Signal, QTimer,
)

_MAX_ARGS_DISPLAY = 2000
_MAX_RESULT_DISPLAY = 3000

_THINKING_PHRASES = [
    "analyzing binary structure...",
    "examining control flow...",
    "tracing cross-references...",
    "inspecting disassembly...",
    "reading function signatures...",
    "correlating data references...",
    "mapping call graph...",
    "evaluating type patterns...",
    "scanning string references...",
    "deobfuscating logic...",
    "checking import table...",
    "inferring variable types...",
    "analyzing stack layout...",
    "tracing data flow...",
    "examining vtable references...",
    "decoding encoded values...",
]


class CollapsibleSection(QFrame):
    """A widget with a clickable header that shows/hides content."""

    def __init__(self, title: str, parent: QWidget = None):
        super().__init__(parent)
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Header
        header = QHBoxLayout()
        self._toggle_btn = QToolButton()
        self._toggle_btn.setObjectName("collapse_button")
        self._toggle_btn.setText("▶")
        self._toggle_btn.setFixedSize(16, 16)
        self._toggle_btn.clicked.connect(self.toggle)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("tool_header")
        header.addWidget(self._toggle_btn)
        header.addWidget(self._title_label, 1)
        layout.addLayout(header)

        # Content area
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(20, 0, 0, 0)
        self._content.setVisible(False)
        layout.addWidget(self._content)

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._toggle_btn.setText("▼" if self._expanded else "▶")

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._toggle_btn.setText("▼" if expanded else "▶")

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout


class UserMessageWidget(QFrame):
    """Displays a user message."""

    def __init__(self, text: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_user")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        role_label = QLabel("You")
        role_label.setStyleSheet("color: #4ec9b0; font-weight: bold; font-size: 11px;")
        layout.addWidget(role_label)

        content = QLabel(text)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setStyleSheet("color: #d4d4d4; font-size: 13px;")
        layout.addWidget(content)


class AssistantMessageWidget(QFrame):
    """Displays an assistant message with streaming support."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_assistant")
        self._full_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        role_label = QLabel("IRIS")
        role_label.setStyleSheet("color: #569cd6; font-weight: bold; font-size: 11px;")
        layout.addWidget(role_label)

        self._content = QLabel()
        self._content.setWordWrap(True)
        self._content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._content.setStyleSheet("color: #d4d4d4; font-size: 13px;")
        layout.addWidget(self._content)

    def append_text(self, delta: str) -> None:
        self._full_text += delta
        self._content.setText(self._full_text)

    def set_text(self, text: str) -> None:
        self._full_text = text
        self._content.setText(text)

    def full_text(self) -> str:
        return self._full_text


class ToolCallWidget(QFrame):
    """Displays a tool call with collapsible arguments and result."""

    def __init__(self, tool_name: str, tool_call_id: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_tool")
        self._tool_name = tool_name
        self._tool_call_id = tool_call_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # Tool name header
        header = QLabel(f"Tool: {tool_name}")
        header.setObjectName("tool_header")
        layout.addWidget(header)

        # Arguments (collapsible)
        self._args_section = CollapsibleSection("Arguments")
        self._args_label = QLabel()
        self._args_label.setObjectName("tool_content")
        self._args_label.setWordWrap(True)
        self._args_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._args_section.content_layout().addWidget(self._args_label)
        layout.addWidget(self._args_section)

        # Result (collapsible)
        self._result_section = CollapsibleSection("Result")
        self._result_label = QLabel()
        self._result_label.setObjectName("tool_content")
        self._result_label.setWordWrap(True)
        self._result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._result_section.content_layout().addWidget(self._result_label)
        layout.addWidget(self._result_section)

        # Status indicator
        self._status = QLabel("Running...")
        self._status.setStyleSheet("color: #dcdcaa; font-size: 10px;")
        layout.addWidget(self._status)

    def set_arguments(self, args_text: str) -> None:
        display = args_text[:_MAX_ARGS_DISPLAY] + "..." if len(args_text) > _MAX_ARGS_DISPLAY else args_text
        self._args_label.setText(display)

    def append_args_delta(self, delta: str) -> None:
        current = self._args_label.text()
        self._args_label.setText(current + delta)

    def set_result(self, result: str, is_error: bool = False) -> None:
        display = result[:_MAX_RESULT_DISPLAY] + "\n... (truncated)" if len(result) > _MAX_RESULT_DISPLAY else result
        self._result_label.setText(display)
        if is_error:
            self._result_label.setStyleSheet("color: #f44747; font-family: monospace; font-size: 11px;")
            self._status.setText("Error")
            self._status.setStyleSheet("color: #f44747; font-size: 10px;")
        else:
            self._status.setText("Done")
            self._status.setStyleSheet("color: #4ec9b0; font-size: 10px;")
        self._result_section.set_expanded(is_error)

    def mark_done(self) -> None:
        if self._status.text() == "Running...":
            self._status.setText("Done")
            self._status.setStyleSheet("color: #4ec9b0; font-size: 10px;")


class ThinkingWidget(QFrame):
    """Animated thinking indicator shown while the LLM is processing.

    Displays a blinking star with rotating technical phrases.
    No Signal definitions — uses QTimer.timeout which is safe because
    QTimer is a pre-existing Qt class (not defined during Shiboken bypass).
    """

    _STAR_FRAMES = ["✳", "✴", "✵", "✶"]

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_thinking")
        self._phrase_idx = random.randint(0, len(_THINKING_PHRASES) - 1)
        self._star_idx = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self._star_label = QLabel(self._STAR_FRAMES[0])
        self._star_label.setStyleSheet("color: #dcdcaa; font-size: 14px;")
        self._star_label.setFixedWidth(18)
        layout.addWidget(self._star_label)

        self._phrase_label = QLabel(_THINKING_PHRASES[self._phrase_idx])
        self._phrase_label.setStyleSheet("color: #808080; font-style: italic; font-size: 12px;")
        layout.addWidget(self._phrase_label, 1)

        self._stopped = False

        # Animate via QTimer — safe, no custom Signals
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(900)

    def _tick(self) -> None:
        if self._stopped:
            return
        self._star_idx = (self._star_idx + 1) % len(self._STAR_FRAMES)
        self._star_label.setText(self._STAR_FRAMES[self._star_idx])

        # Rotate phrase every ~3 ticks
        if self._star_idx == 0:
            self._phrase_idx = (self._phrase_idx + 1) % len(_THINKING_PHRASES)
            self._phrase_label.setText(_THINKING_PHRASES[self._phrase_idx])

    def stop(self) -> None:
        """Stop animation. Call before removing from layout."""
        self._stopped = True
        try:
            self._timer.stop()
            self._timer.timeout.disconnect(self._tick)
        except (RuntimeError, TypeError):
            pass


class QueuedMessageWidget(QFrame):
    """Displays a queued user message with dashed border."""

    def __init__(self, text: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_queued")
        self.setStyleSheet(
            "QFrame#message_queued { border: 1px dashed #007acc; "
            "border-radius: 6px; background: #1e1e2e; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        content_layout = QVBoxLayout()

        role_label = QLabel("You")
        role_label.setStyleSheet("color: #4ec9b0; font-weight: bold; font-size: 11px;")
        content_layout.addWidget(role_label)

        content = QLabel(text)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setStyleSheet("color: #d4d4d4; font-size: 13px;")
        content_layout.addWidget(content)

        layout.addLayout(content_layout, 1)

        badge = QLabel("[queued]")
        badge.setStyleSheet("color: #808080; font-size: 10px; font-style: italic;")
        badge.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(badge)


class UserQuestionWidget(QFrame):
    """Displays a question from the agent to the user."""

    def __init__(self, question: str, options: list = None, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_question")
        self.setStyleSheet(
            "QFrame#message_question { border: 1px solid #dcdcaa; "
            "border-radius: 6px; background: #2d2d1e; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        header = QLabel("IRIS asks:")
        header.setStyleSheet("color: #dcdcaa; font-weight: bold; font-size: 11px;")
        layout.addWidget(header)

        q_label = QLabel(question)
        q_label.setWordWrap(True)
        q_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        q_label.setStyleSheet("color: #d4d4d4; font-size: 13px;")
        layout.addWidget(q_label)

        if options:
            for i, opt in enumerate(options, 1):
                opt_label = QLabel(f"  {i}. {opt}")
                opt_label.setStyleSheet("color: #9cdcfe; font-size: 12px;")
                layout.addWidget(opt_label)

            hint = QLabel("Type your answer or a number to choose an option.")
            hint.setStyleSheet("color: #808080; font-size: 10px; font-style: italic;")
            layout.addWidget(hint)


class ErrorMessageWidget(QFrame):
    """Displays an error message."""

    def __init__(self, error_text: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_tool")
        self.setStyleSheet("QFrame#message_tool { border-color: #f44747; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        header = QLabel("Error")
        header.setStyleSheet("color: #f44747; font-weight: bold; font-size: 11px;")
        layout.addWidget(header)

        content = QLabel(error_text)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setStyleSheet("color: #f44747; font-size: 12px;")
        layout.addWidget(content)
