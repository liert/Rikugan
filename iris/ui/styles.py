"""Dark-theme stylesheet for IRIS UI."""

from __future__ import annotations

DARK_THEME = """
QWidget#iris_panel {
    background-color: #1e1e1e;
    color: #d4d4d4;
}

QScrollArea#chat_scroll {
    background-color: #1e1e1e;
    border: none;
}

QWidget#chat_container {
    background-color: #1e1e1e;
}

QFrame#message_user {
    background-color: #2d2d2d;
    border-radius: 8px;
    padding: 8px;
    margin: 4px 40px 4px 8px;
}

QFrame#message_assistant {
    background-color: #1e1e1e;
    border-radius: 8px;
    padding: 8px;
    margin: 4px 8px 4px 8px;
}

QFrame#message_tool {
    background-color: #252526;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 3px 6px;
    margin: 1px 12px 1px 12px;
}

QFrame#message_thinking {
    background-color: #1e1e1e;
    border-radius: 6px;
    padding: 4px 8px;
    margin: 2px 8px;
}

QLabel#tool_header {
    color: #569cd6;
    font-weight: bold;
    font-size: 11px;
}

QLabel#tool_content {
    color: #9cdcfe;
    font-family: monospace;
    font-size: 11px;
}

QPlainTextEdit#input_area {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 8px;
    padding: 8px;
    font-size: 13px;
    selection-background-color: #264f78;
}

QPlainTextEdit#input_area:focus {
    border-color: #007acc;
}

QPushButton#send_button {
    background-color: #007acc;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: bold;
}

QPushButton#send_button:hover {
    background-color: #1a8ad4;
}

QPushButton#send_button:pressed {
    background-color: #005a9e;
}

QPushButton#send_button:disabled {
    background-color: #3c3c3c;
    color: #6c6c6c;
}

QPushButton#cancel_button {
    background-color: #c72e2e;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: bold;
}

QFrame#context_bar {
    background-color: #252526;
    border-top: 1px solid #3c3c3c;
    padding: 4px 8px;
}

QLabel#context_label {
    color: #808080;
    font-size: 11px;
}

QLabel#context_value {
    color: #cccccc;
    font-size: 11px;
}

QFrame#plan_step {
    background-color: #252526;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 4px 8px;
    margin: 2px;
}

QFrame#plan_step_active {
    background-color: #252526;
    border: 1px solid #007acc;
    border-radius: 4px;
    padding: 4px 8px;
    margin: 2px;
}

QFrame#plan_step_done {
    background-color: #252526;
    border: 1px solid #4ec9b0;
    border-radius: 4px;
    padding: 4px 8px;
    margin: 2px;
}

QToolButton#collapse_button {
    border: none;
    color: #808080;
    font-size: 10px;
}

QToolButton#collapse_button:hover {
    color: #d4d4d4;
}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 4px;
}

QGroupBox {
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 16px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
"""
