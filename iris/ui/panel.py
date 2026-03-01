"""Main IRIS panel: dockable PluginForm with chat, input, and context bar.

All iris.* imports are at module level.  All ida_* imports use
importlib.import_module() to bypass Shiboken's __import__ hook, avoiding
the UAF crash on Python 3.14 / PySide6.
"""

from __future__ import annotations

import importlib
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
from .actions import IRISUIHooks
from ..core.config import IRISConfig
from ..core.logging import log_error, log_info, log_debug
from ..agent.turn import TurnEvent, TurnEventType

try:
    idaapi = importlib.import_module("idaapi")
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
        self._polling = False  # re-entrancy guard for _poll_events
        self._root: Optional[QWidget] = None
        self._pending_answer = False

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
                self._stop_poll_timer()
                if hasattr(self, '_context_bar') and self._context_bar:
                    self._context_bar.stop()
                if hasattr(self, '_chat_view') and self._chat_view:
                    self._chat_view.shutdown()
                if hasattr(self, '_ui_hooks') and self._ui_hooks:
                    self._ui_hooks.unhook()
                    self._ui_hooks = None
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
        # Plain Python callbacks — no Shiboken signal dispatch (avoids SIGSEGV)
        self._input_area.set_submit_callback(self._on_submit)
        self._input_area.set_cancel_callback(self._on_cancel)
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

        # Hook IDA context menus (right-click "IRIS/" submenu)
        if _HAS_IDA:
            self._ui_hooks = IRISUIHooks(panel_getter=lambda: self)
            self._ui_hooks.hook()
        else:
            self._ui_hooks = None

        self._try_restore_session()

    # -- Event handlers --

    def _on_submit(self, text: str) -> None:
        if not text:
            return
        # Deliver answer to a pending ask_user question
        if self._pending_answer:
            self._pending_answer = False
            self._chat_view.add_user_message(text)
            self._set_running(True)
            runner = self._ctrl.get_runner()
            if runner:
                runner.agent_loop.submit_user_answer(text)
            return
        if self._ctrl.is_agent_running:
            self._ctrl.queue_message(text)
            self._chat_view.add_queued_message(text)
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

        # Poll the event queue from the Qt thread — no cross-thread signals.
        # Reuse a single parented timer to avoid:
        #  - Parentless QTimer UAF via Python 3.14 deferred refcounting
        #  - Timer destruction inside its own signal handler
        self._ensure_poll_timer()
        self._poll_timer.start(50)

    def _ensure_poll_timer(self) -> None:
        """Create the poll timer once, parented to _root for deterministic destruction."""
        if self._poll_timer is not None:
            return
        self._poll_timer = QTimer(self._root)
        self._poll_timer.timeout.connect(self._poll_events)

    def _stop_poll_timer(self) -> None:
        """Safely stop and discard the poll timer."""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            try:
                self._poll_timer.timeout.disconnect(self._poll_events)
            except (RuntimeError, TypeError):
                pass
            self._poll_timer.deleteLater()
            self._poll_timer = None

    def _poll_events(self) -> None:
        # Re-entrancy guard: IDA's execute_sync pumps the Qt event loop,
        # which can fire this timer again while we're already inside it.
        if self._polling or self._root is None:
            return
        self._polling = True
        try:
            for _ in range(20):  # Process up to 20 events per tick
                event = self._ctrl.get_event(timeout=0)
                if event is None:
                    if not self._ctrl.is_agent_running:
                        self._on_agent_finished()
                    return
                self._on_event(event)
        finally:
            self._polling = False

    def _on_event(self, event: TurnEvent) -> None:
        if self._root is None:
            return
        self._chat_view.handle_event(event)
        if event.usage:
            self._context_bar.set_tokens(self._ctrl.session.total_usage.total_tokens)
        # ask_user: enable input so user can type an answer
        if event.type == TurnEventType.USER_QUESTION:
            self._pending_answer = True
            self._set_running(False)  # Show send button, enable input

    def _on_agent_finished(self) -> None:
        if self._root is None:
            return
        # Stop the timer — don't destroy it; _start_agent() will reuse it.
        if self._poll_timer:
            self._poll_timer.stop()
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
