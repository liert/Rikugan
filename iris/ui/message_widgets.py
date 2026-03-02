"""Message display widgets for the chat view."""

from __future__ import annotations

import json
import random
from typing import Dict, List, Optional

from .qt_compat import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QToolButton,
    QWidget, QSizePolicy, Qt, Signal, QTimer,
)
from .markdown import md_to_html

_MAX_ARGS_DISPLAY = 2000
_MAX_RESULT_DISPLAY = 3000
_TOOL_PREVIEW_LINES = 3

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

# ---------------------------------------------------------------------------
# MCP prefix stripping — works with any MCP server, not just a specific one
# ---------------------------------------------------------------------------

def _strip_mcp_prefix(name: str) -> str:
    """Strip MCP server prefix (``mcp__<server>__``) from tool names."""
    if name.startswith("mcp__"):
        rest = name[5:]  # after "mcp__"
        idx = rest.find("__")
        if idx >= 0:
            return rest[idx + 2:]
    return name


# ---------------------------------------------------------------------------
# Tool-specific colors (by base name — MCP prefix is stripped before lookup)
# ---------------------------------------------------------------------------
_TOOL_COLORS: Dict[str, str] = {}

# Analysis (read-only) -> teal/cyan
for _t in (
    "decompile_function", "read_disassembly", "read_function_disassembly",
    "get_binary_info", "list_imports", "list_exports", "list_functions",
    "search_functions", "list_strings", "search_strings", "get_string_at",
    "list_segments", "xrefs_to", "xrefs_from", "function_xrefs",
    "get_microcode", "get_cursor_position", "get_current_function",
    "fetch_disassembly", "list_methods", "list_strings_filter",
    "list_sections", "get_xrefs_to", "get_xrefs_to_field",
    "get_xrefs_to_struct", "get_xrefs_to_type", "get_xrefs_to_enum",
    "get_xrefs_to_union", "get_il", "get_binary_status",
    "hexdump_address", "hexdump_data", "get_data_decl",
    "search_functions_by_name", "function_at", "get_entry_points",
    "list_classes", "list_namespaces", "list_data_items",
    "list_all_strings", "list_local_types", "search_types",
    "get_type_info", "get_user_defined_type",
    "get_comment", "get_function_comment",
    "list_binaries", "select_binary", "list_platforms",
    "convert_number", "format_value",
):
    _TOOL_COLORS[_t] = "#4ec9b0"  # teal/cyan

# Modification -> magenta/purple
for _t in (
    "rename_function", "rename_variable", "rename_address",
    "set_type", "set_function_prototype", "set_comment",
    "set_function_comment", "create_struct", "create_enum",
    "nop_microcode", "install_microcode_optimizer",
    "redecompile_function", "apply_struct_to_address",
    "rename_single_variable", "rename_multi_variables",
    "retype_variable", "define_types", "declare_c_type",
    "rename_data", "set_local_variable_type", "make_function_at",
    "delete_comment", "delete_function_comment",
):
    _TOOL_COLORS[_t] = "#c586c0"  # magenta/purple

# Scripting -> green
for _t in ("execute_python",):
    _TOOL_COLORS[_t] = "#6a9955"

_DEFAULT_TOOL_COLOR = "#569cd6"  # blue


def _tool_color(name: str) -> str:
    """Look up tool color by base name (MCP prefix stripped)."""
    return _TOOL_COLORS.get(_strip_mcp_prefix(name), _DEFAULT_TOOL_COLOR)


# ---------------------------------------------------------------------------
# Smart tool parameter summaries
# ---------------------------------------------------------------------------

def _format_tool_summary(tool_name: str, args_text: str) -> str:
    """Extract the most relevant parameter for a compact one-line summary."""
    try:
        args = json.loads(args_text) if args_text else {}
    except (json.JSONDecodeError, TypeError):
        return ""

    if not isinstance(args, dict):
        return ""

    def _get(*keys: str) -> str:
        for k in keys:
            v = args.get(k)
            if v is not None:
                return str(v)
        return ""

    # Strip MCP prefix for matching (works with any MCP server)
    short_name = _strip_mcp_prefix(tool_name)

    summary = ""

    if short_name in ("decompile_function",):
        target = _get("address", "ea", "name", "target", "func_id")
        if target:
            summary = target

    elif short_name in ("rename_function",):
        old = _get("old_name", "current_name", "ea")
        new = _get("new_name")
        if old and new:
            summary = f"{old} → {new}"

    elif short_name in ("rename_single_variable", "rename_variable"):
        func = _get("function_name", "function", "ea")
        old = _get("variable_name", "var_name", "old_name")
        new = _get("new_name")
        if old and new:
            summary = f"{func}: {old} → {new}" if func else f"{old} → {new}"

    elif short_name in ("rename_multi_variables",):
        func = _get("function_identifier", "function_name", "ea")
        summary = func if func else ""

    elif short_name in ("set_comment", "set_function_comment"):
        addr = _get("address", "ea", "function_name")
        comment = _get("comment", "text")
        if comment and len(comment) > 50:
            comment = comment[:47] + "..."
        if addr and comment:
            summary = f"{addr}: {comment}"
        elif comment:
            summary = comment

    elif short_name in ("set_type", "set_function_prototype", "retype_variable",
                         "set_local_variable_type"):
        target = _get("ea", "address", "name", "name_or_address", "variable_name")
        type_str = _get("type_str", "prototype", "new_type", "type")
        if target and type_str:
            summary = f"{target}: {type_str}"

    elif short_name in ("xrefs_to", "xrefs_from", "function_xrefs",
                         "get_xrefs_to", "get_xrefs_to_field"):
        target = _get("address", "ea", "name", "struct_name")
        if target:
            summary = target

    elif short_name in ("search_strings", "search_functions", "search_functions_by_name",
                         "list_strings_filter"):
        query = _get("pattern", "query", "filter", "name")
        if query:
            summary = f'"{query}"'

    elif short_name in ("define_types", "declare_c_type"):
        code = _get("c_code", "c_declaration", "types")
        if code and len(code) > 60:
            code = code[:57] + "..."
        summary = code or ""

    elif short_name in ("create_struct",):
        name = _get("name", "struct_name")
        summary = name

    elif short_name in ("execute_python",):
        code = _get("code", "script")
        if code:
            first_line = code.strip().split("\n")[0]
            if len(first_line) > 60:
                first_line = first_line[:57] + "..."
            summary = first_line

    elif short_name in ("fetch_disassembly", "read_disassembly", "read_function_disassembly"):
        target = _get("name", "ea", "address", "start")
        if target:
            summary = target

    elif short_name in ("get_il",):
        target = _get("name_or_address")
        view = _get("view")
        if target:
            summary = f"{target}" + (f" ({view})" if view else "")

    elif short_name in ("hexdump_address", "hexdump_data", "get_data_decl"):
        target = _get("address", "name_or_address")
        if target:
            summary = target

    else:
        # Generic: try common parameter names
        for key in ("target", "address", "ea", "name", "path", "query",
                     "pattern", "command", "name_or_address"):
            val = _get(key)
            if val:
                summary = val
                break

    # Truncate
    if len(summary) > 80:
        summary = summary[:77] + "..."
    return summary


def _truncate_preview(text: str, max_lines: int = _TOOL_PREVIEW_LINES) -> str:
    """Return first N lines with a '… +M lines' indicator if truncated."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    preview = "\n".join(lines[:max_lines])
    remaining = len(lines) - max_lines
    return f"{preview}\n… +{remaining} lines"


# ---------------------------------------------------------------------------
# Collapsible section (unchanged, used internally)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# User message
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Assistant message (with streaming + Markdown)
# ---------------------------------------------------------------------------

class AssistantMessageWidget(QFrame):
    """Displays an assistant message with streaming support and Markdown rendering."""

    _RENDER_BATCH = 40

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_assistant")
        self._full_text = ""
        self._pending_delta = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        role_label = QLabel("IRIS")
        role_label.setStyleSheet("color: #569cd6; font-weight: bold; font-size: 11px;")
        layout.addWidget(role_label)

        self._content = QLabel()
        self._content.setWordWrap(True)
        self._content.setTextFormat(Qt.TextFormat.RichText)
        self._content.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._content.setOpenExternalLinks(True)
        self._content.setStyleSheet("color: #d4d4d4; font-size: 13px;")
        layout.addWidget(self._content)

    def _render(self) -> None:
        self._content.setText(md_to_html(self._full_text))
        self._pending_delta = 0

    def append_text(self, delta: str) -> None:
        self._full_text += delta
        self._pending_delta += len(delta)
        if self._pending_delta >= self._RENDER_BATCH:
            self._render()

    def set_text(self, text: str) -> None:
        self._full_text = text
        self._render()

    def full_text(self) -> str:
        return self._full_text


# ---------------------------------------------------------------------------
# Compact tool call widget
# ---------------------------------------------------------------------------

class ToolCallWidget(QFrame):
    """Compact tool call display.

    Shows:  ● tool_name  summary_text
    With a collapsible detail section for args and result.
    """

    def __init__(self, tool_name: str, tool_call_id: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_tool")
        self._tool_name = tool_name
        self._tool_call_id = tool_call_id
        self._args_text = ""
        self._result_text = ""
        self._is_error = False
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(2)

        display_name = _strip_mcp_prefix(tool_name)
        color = _tool_color(tool_name)

        # Compact header line: ● tool_name  summary
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        self._toggle_btn = QToolButton()
        self._toggle_btn.setObjectName("collapse_button")
        self._toggle_btn.setText("▶")
        self._toggle_btn.setFixedSize(14, 14)
        self._toggle_btn.clicked.connect(self._toggle)
        header_layout.addWidget(self._toggle_btn)

        self._bullet = QLabel("●")
        self._bullet.setStyleSheet(f"color: {color}; font-size: 10px;")
        self._bullet.setFixedWidth(14)
        header_layout.addWidget(self._bullet)

        self._name_label = QLabel(display_name)
        self._name_label.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 11px;"
        )
        header_layout.addWidget(self._name_label)

        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet("color: #808080; font-size: 11px; margin-left: 6px;")
        header_layout.addWidget(self._summary_label, 1)

        self._status_label = QLabel("…")
        self._status_label.setStyleSheet("color: #dcdcaa; font-size: 10px;")
        header_layout.addWidget(self._status_label)

        layout.addLayout(header_layout)

        # Preview: first few lines of args, shown by default
        self._preview_label = QLabel()
        self._preview_label.setObjectName("tool_content")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            "color: #6a6a7a; font-family: monospace; font-size: 10px; "
            "margin-left: 28px;"
        )
        self._preview_label.setVisible(False)
        layout.addWidget(self._preview_label)

        # Expandable detail area (args + result)
        self._detail_widget = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_widget)
        self._detail_layout.setContentsMargins(28, 2, 0, 2)
        self._detail_layout.setSpacing(2)

        self._args_label = QLabel()
        self._args_label.setObjectName("tool_content")
        self._args_label.setWordWrap(True)
        self._args_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._detail_layout.addWidget(self._args_label)

        self._result_header = QLabel("Result:")
        self._result_header.setStyleSheet("color: #808080; font-size: 10px; font-weight: bold;")
        self._result_header.setVisible(False)
        self._detail_layout.addWidget(self._result_header)

        self._result_label = QLabel()
        self._result_label.setObjectName("tool_content")
        self._result_label.setWordWrap(True)
        self._result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._result_label.setVisible(False)
        self._detail_layout.addWidget(self._result_label)

        self._detail_widget.setVisible(False)
        layout.addWidget(self._detail_widget)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._detail_widget.setVisible(self._expanded)
        self._preview_label.setVisible(not self._expanded and bool(self._args_text))
        self._toggle_btn.setText("▼" if self._expanded else "▶")

    def set_arguments(self, args_text: str) -> None:
        self._args_text = args_text
        # Update summary
        summary = _format_tool_summary(self._tool_name, args_text)
        if summary:
            self._summary_label.setText(summary)
        # Preview (truncated)
        if args_text.strip():
            self._preview_label.setText(_truncate_preview(args_text.strip()))
            self._preview_label.setVisible(not self._expanded)
        # Full args in detail area
        display = args_text[:_MAX_ARGS_DISPLAY] + "..." if len(args_text) > _MAX_ARGS_DISPLAY else args_text
        self._args_label.setText(display)

    def append_args_delta(self, delta: str) -> None:
        self._args_text += delta
        # Don't update preview during streaming — wait for set_arguments

    def set_result(self, result: str, is_error: bool = False) -> None:
        self._result_text = result
        self._is_error = is_error
        display = result[:_MAX_RESULT_DISPLAY] + "\n... (truncated)" if len(result) > _MAX_RESULT_DISPLAY else result
        self._result_label.setText(display)
        self._result_label.setVisible(True)
        self._result_header.setVisible(True)
        if is_error:
            self._result_label.setStyleSheet("color: #f44747; font-family: monospace; font-size: 11px;")
            self._status_label.setText("✗")
            self._status_label.setStyleSheet("color: #f44747; font-size: 10px;")
            self._bullet.setStyleSheet("color: #f44747; font-size: 10px;")
            # Auto-expand on error
            self._expanded = True
            self._detail_widget.setVisible(True)
            self._preview_label.setVisible(False)
            self._toggle_btn.setText("▼")
        else:
            self._status_label.setText("✓")
            self._status_label.setStyleSheet("color: #4ec9b0; font-size: 10px;")

    def mark_done(self) -> None:
        if self._status_label.text() == "…":
            self._status_label.setText("✓")
            self._status_label.setStyleSheet("color: #4ec9b0; font-size: 10px;")

    def hide_preview(self) -> None:
        """Hide the args preview (used when preview budget exhausted)."""
        self._preview_label.setVisible(False)


# ---------------------------------------------------------------------------
# Tool batch widget — groups N consecutive calls to the same tool
# ---------------------------------------------------------------------------

class ToolBatchWidget(QFrame):
    """Groups consecutive calls to the same tool.

    Shows:  ● tool_name  (N calls)
    With preview of the first call's args.
    """

    def __init__(self, tool_name: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_tool")
        self._tool_name = tool_name
        self._count = 0
        self._expanded = False
        self._first_args: str = ""
        self._tool_call_ids: List[str] = []
        self._results: Dict[str, str] = {}
        self._errors: Dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(2)

        display_name = _strip_mcp_prefix(tool_name)
        color = _tool_color(tool_name)

        # Header: ● tool_name  (N calls)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        self._toggle_btn = QToolButton()
        self._toggle_btn.setObjectName("collapse_button")
        self._toggle_btn.setText("▶")
        self._toggle_btn.setFixedSize(14, 14)
        self._toggle_btn.clicked.connect(self._toggle)
        header_layout.addWidget(self._toggle_btn)

        self._bullet = QLabel("●")
        self._bullet.setStyleSheet(f"color: {color}; font-size: 10px;")
        self._bullet.setFixedWidth(14)
        header_layout.addWidget(self._bullet)

        self._name_label = QLabel(display_name)
        self._name_label.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 11px;"
        )
        header_layout.addWidget(self._name_label)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #808080; font-size: 11px; margin-left: 6px;")
        header_layout.addWidget(self._count_label, 1)

        self._status_label = QLabel("…")
        self._status_label.setStyleSheet("color: #dcdcaa; font-size: 10px;")
        header_layout.addWidget(self._status_label)

        layout.addLayout(header_layout)

        # Preview of first call's args
        self._preview_label = QLabel()
        self._preview_label.setObjectName("tool_content")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            "color: #6a6a7a; font-family: monospace; font-size: 10px; "
            "margin-left: 28px;"
        )
        self._preview_label.setVisible(False)
        layout.addWidget(self._preview_label)

        # Detail area for all calls
        self._detail_widget = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_widget)
        self._detail_layout.setContentsMargins(28, 2, 0, 2)
        self._detail_layout.setSpacing(4)
        self._detail_widget.setVisible(False)
        layout.addWidget(self._detail_widget)

    def add_call(self, tool_call_id: str, args_text: str = "") -> None:
        """Add another call to this batch."""
        self._count += 1
        self._tool_call_ids.append(tool_call_id)
        self._count_label.setText(f"({self._count} calls)")

        if self._count == 1 and args_text.strip():
            self._first_args = args_text
            summary = _format_tool_summary(self._tool_name, args_text)
            # For first call, show summary alongside count
            preview = _truncate_preview(args_text.strip())
            self._preview_label.setText(preview)
            self._preview_label.setVisible(not self._expanded)

        # Add entry in detail area
        summary = _format_tool_summary(self._tool_name, args_text) if args_text else ""
        entry = QLabel(f"#{self._count}: {summary}" if summary else f"#{self._count}")
        entry.setStyleSheet("color: #808080; font-family: monospace; font-size: 10px;")
        entry.setWordWrap(True)
        self._detail_layout.addWidget(entry)

    def set_args_for_call(self, tool_call_id: str, args_text: str) -> None:
        """Update args for a specific call (used when streaming completes)."""
        idx = -1
        for i, tid in enumerate(self._tool_call_ids):
            if tid == tool_call_id:
                idx = i
                break
        if idx < 0:
            return

        if idx == 0 and not self._first_args:
            self._first_args = args_text
            preview = _truncate_preview(args_text.strip())
            self._preview_label.setText(preview)
            self._preview_label.setVisible(not self._expanded)

        # Update detail entry
        summary = _format_tool_summary(self._tool_name, args_text)
        item = self._detail_layout.itemAt(idx)
        if item and item.widget():
            label_text = f"#{idx + 1}: {summary}" if summary else f"#{idx + 1}"
            item.widget().setText(label_text)

    def set_result_for_call(self, tool_call_id: str, result: str, is_error: bool) -> None:
        """Record a result for one call in the batch."""
        if is_error:
            self._errors[tool_call_id] = result
        else:
            self._results[tool_call_id] = result
        self._update_status()

    def _update_status(self) -> None:
        done = len(self._results) + len(self._errors)
        if done >= self._count:
            if self._errors:
                self._status_label.setText(f"✓{len(self._results)} ✗{len(self._errors)}")
                self._status_label.setStyleSheet("color: #f44747; font-size: 10px;")
            else:
                self._status_label.setText("✓")
                self._status_label.setStyleSheet("color: #4ec9b0; font-size: 10px;")
        else:
            self._status_label.setText(f"{done}/{self._count}")

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._detail_widget.setVisible(self._expanded)
        self._preview_label.setVisible(not self._expanded and bool(self._first_args))
        self._toggle_btn.setText("▼" if self._expanded else "▶")

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def count(self) -> int:
        return self._count


# ---------------------------------------------------------------------------
# Thinking indicator
# ---------------------------------------------------------------------------

class ThinkingWidget(QFrame):
    """Animated thinking indicator shown while the LLM is processing."""

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

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(900)

    def _tick(self) -> None:
        if self._stopped:
            return
        self._star_idx = (self._star_idx + 1) % len(self._STAR_FRAMES)
        self._star_label.setText(self._STAR_FRAMES[self._star_idx])

        if self._star_idx == 0:
            self._phrase_idx = (self._phrase_idx + 1) % len(_THINKING_PHRASES)
            self._phrase_label.setText(_THINKING_PHRASES[self._phrase_idx])

    def stop(self) -> None:
        self._stopped = True
        try:
            self._timer.stop()
            self._timer.timeout.disconnect(self._tick)
        except (RuntimeError, TypeError):
            pass


# ---------------------------------------------------------------------------
# Other message widgets
# ---------------------------------------------------------------------------

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
