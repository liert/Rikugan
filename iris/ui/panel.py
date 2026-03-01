"""Main IRIS panel: dockable PluginForm with chat, input, and context bar.

All iris.* imports are at module level.  This module is imported during the
Shiboken bypass window in iris_plugin._toggle_panel(), so every ``from``
statement executes through CPython's real __import__ — not the Shiboken hook
that causes SIGSEGV on Python 3.14.
"""

from __future__ import annotations

import threading
from typing import Optional

from .qt_compat import (
    QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QTimer,
)
from .styles import DARK_THEME
from .chat_view import ChatView
from .input_area import InputArea
from .context_bar import ContextBar
from .settings_dialog import SettingsDialog, _resolve_auth_cached
from .session_controller import SessionController
from ..core.config import IRISConfig
from ..core.logging import log_error, log_info, log_debug
from ..agent.turn import TurnEvent

try:
    import idaapi
    _HAS_IDA = True
except ImportError:
    _HAS_IDA = False


class IRISPanel(idaapi.PluginForm if _HAS_IDA else QWidget):
    """The main IRIS dockable panel."""

    def __init__(self):
        super().__init__()
        self._config = IRISConfig.load_or_create()
        log_debug(f"Config loaded: provider={self._config.provider.name} model={self._config.provider.model}")
        self._ctrl = SessionController(self._config)
        self._poll_timer: Optional[QTimer] = None
        self._root: Optional[QWidget] = None

        # Pre-warm OAuth cache in a background thread so the settings dialog
        # doesn't need to spawn subprocesses during widget construction.
        def _warm_oauth():
            try:
                _resolve_auth_cached()
            except Exception as e:
                log_debug(f"OAuth warm-up failed: {e}")
        threading.Thread(target=_warm_oauth, daemon=True).start()

    if _HAS_IDA:
        def OnCreate(self, form):  # noqa: N802
            try:
                self._form_widget = self.FormToPyQtWidget(form)
            except Exception:
                self._form_widget = self.FormToPySideWidget(form)

            # Intermediate root widget: sits between IDA's form and our UI.
            # In OnClose we detach _root from the form so IDA's cascade
            # deletion hits an empty form — not our Shiboken-wrapped widgets.
            self._root = QWidget()
            form_layout = QVBoxLayout(self._form_widget)
            form_layout.setContentsMargins(0, 0, 0, 0)
            form_layout.addWidget(self._root)
            self._build_ui(self._root)

        def OnClose(self, form):  # noqa: N802
            try:
                if self._poll_timer:
                    self._poll_timer.stop()
                    self._poll_timer = None
                if hasattr(self, '_context_bar') and self._context_bar:
                    self._context_bar.stop()
                self._ctrl.shutdown()
                # Detach widget tree to prevent Qt cascade deletion
                if self._root is not None:
                    self._root.setParent(None)
                    self._root = None
            except Exception as e:
                log_error(f"OnClose error: {e}")

        def show(self):
            return self.Show(
                "IRIS",
                options=(
                    idaapi.PluginForm.WOPN_TAB
                    | idaapi.PluginForm.WOPN_PERSIST
                ),
            )

        def close(self):
            self.Close(0)
    else:
        def show(self):
            self._root = self
            self._build_ui(self)
            super().show()

    def _build_ui(self, parent: QWidget) -> None:
        parent.setStyleSheet(DARK_THEME)
        parent.setObjectName("iris_panel")

        layout = QVBoxLayout(parent) if parent.layout() is None else parent.layout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._chat_view = ChatView()
        layout.addWidget(self._chat_view, 1)

        # Input area with send/cancel buttons
        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(8, 4, 8, 4)

        self._input_area = InputArea()
        self._input_area.submit_requested.connect(self._on_submit)
        self._input_area.cancel_requested.connect(self._on_cancel)
        self._input_area.set_skill_slugs(self._ctrl.skill_slugs)
        input_layout.addWidget(self._input_area, 1)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("send_button")
        self._send_btn.setFixedWidth(64)
        self._send_btn.clicked.connect(self._on_send_clicked)
        btn_layout.addWidget(self._send_btn)

        self._cancel_btn = QPushButton("Stop")
        self._cancel_btn.setObjectName("cancel_button")
        self._cancel_btn.setFixedWidth(64)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._cancel_btn)

        _small_btn_style = (
            "QPushButton { background: #2d2d2d; color: #d4d4d4; border: 1px solid #3c3c3c; "
            "border-radius: 6px; padding: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #3c3c3c; }"
        )

        self._new_btn = QPushButton("New")
        self._new_btn.setFixedWidth(64)
        self._new_btn.setStyleSheet(_small_btn_style)
        self._new_btn.clicked.connect(self._on_new_chat)
        btn_layout.addWidget(self._new_btn)

        self._settings_btn = QPushButton("Settings")
        self._settings_btn.setFixedWidth(64)
        self._settings_btn.setStyleSheet(_small_btn_style)
        self._settings_btn.clicked.connect(self._on_settings)
        btn_layout.addWidget(self._settings_btn)

        btn_layout.addStretch()
        input_layout.addLayout(btn_layout)
        layout.addWidget(input_container)

        self._context_bar = ContextBar()
        self._context_bar.set_model(self._config.provider.model)
        layout.addWidget(self._context_bar)

        self._try_restore_session()

    # -- Event handlers --

    def _on_submit(self, text: str) -> None:
        if not text:
            return
        if self._ctrl.is_agent_running:
            self._ctrl.queue_message(text)
            self._chat_view.add_user_message(f"[queued] {text}")
            return
        self._start_agent(text)

    def _on_send_clicked(self) -> None:
        text = self._input_area.toPlainText().strip()
        if text:
            self._input_area.clear()
            self._on_submit(text)

    def _on_cancel(self) -> None:
        self._ctrl.cancel()

    def _on_settings(self) -> None:
        try:
            dlg = SettingsDialog(self._config, registry=self._ctrl.provider_registry)
            result = dlg.exec_()
            if result:
                self._config.save()
                self._ctrl.update_settings()
                self._context_bar.set_model(self._config.provider.model)
                log_info(f"Settings updated: {self._config.provider.name}/{self._config.provider.model}")
            dlg.setParent(None)
        except Exception as e:
            log_error(f"Settings dialog error: {e}")

    def _on_new_chat(self) -> None:
        """Start a fresh chat session."""
        if self._ctrl.is_agent_running:
            return
        self._ctrl.new_chat()
        self._chat_view.clear_chat()
        self._context_bar.set_tokens(0)

    # -- Agent start / poll / finish --

    def _start_agent(self, user_message: str) -> None:
        self._chat_view.add_user_message(user_message)
        self._set_running(True)

        error = self._ctrl.start_agent(user_message)
        if error:
            self._chat_view.add_error_message(error)
            self._set_running(False)
            return

        # Poll the event queue from the Qt thread — no cross-thread signals
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_events)
        self._poll_timer.start(50)

    def _poll_events(self) -> None:
        for _ in range(20):  # Process up to 20 events per tick
            event = self._ctrl.get_event(timeout=0)
            if event is None:
                if not self._ctrl.is_agent_running:
                    self._on_agent_finished()
                return
            self._on_event(event)

    def _on_event(self, event: TurnEvent) -> None:
        if self._root is None:
            return
        self._chat_view.handle_event(event)
        if event.usage:
            self._context_bar.set_tokens(self._ctrl.session.total_usage.total_tokens)

    def _on_agent_finished(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None
        self._set_running(False)

        next_msg = self._ctrl.on_agent_finished()
        if next_msg:
            self._start_agent(next_msg)

    # -- Session restore --

    def _try_restore_session(self) -> None:
        """Restore the most recent session on startup."""
        session = self._ctrl.restore_session()
        if session:
            self._chat_view.restore_from_messages(session.messages)
            self._context_bar.set_tokens(session.total_usage.total_tokens)

    # -- UI state --

    def _set_running(self, running: bool) -> None:
        if self._root is None:
            return
        self._input_area.set_enabled(not running)
        self._send_btn.setVisible(not running)
        self._send_btn.setEnabled(not running)
        self._cancel_btn.setVisible(running)
