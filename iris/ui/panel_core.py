"""Shared IRIS panel widget used by host-specific wrappers."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from .qt_compat import (
    QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QTimer,
    QTabWidget, QTabBar, QToolButton, Signal,
)
from .styles import DARK_THEME
from .chat_view import ChatView
from .input_area import InputArea
from .context_bar import ContextBar
from .settings_dialog import SettingsDialog, _resolve_auth_cached
from ..core.config import IRISConfig
from ..core.logging import log_error, log_info, log_debug
from ..agent.turn import TurnEvent, TurnEventType


class _AddButtonTabBar(QTabBar):
    """Tab bar with an integrated '+' button positioned after the last tab."""

    add_tab_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._add_btn = QToolButton(self)
        self._add_btn.setText("+")
        self._add_btn.setAutoRaise(True)
        self._add_btn.setFixedSize(20, 20)
        self._add_btn.setStyleSheet(
            "QToolButton { color: #d4d4d4; font-size: 14px; font-weight: bold; "
            "border: none; background: transparent; }"
            "QToolButton:hover { background: #3c3c3c; border-radius: 3px; }"
        )
        self._add_btn.clicked.connect(self.add_tab_requested)

    def tabInserted(self, index):
        super().tabInserted(index)
        self._reposition()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self._reposition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()

    def _reposition(self):
        count = self.count()
        if count > 0:
            rect = self.tabRect(count - 1)
            y = (self.height() - self._add_btn.height()) // 2
            self._add_btn.move(rect.right() + 2, max(0, y))
        else:
            self._add_btn.move(0, 0)


class IRISPanelCore(QWidget):
    """Host-agnostic chat panel widget."""

    def __init__(
        self,
        controller_factory: Callable[[IRISConfig], Any],
        ui_hooks_factory: Optional[Callable[[Callable[[], Any]], Any]] = None,
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self._config = IRISConfig.load_or_create()
        log_debug(
            f"Config loaded: provider={self._config.provider.name} "
            f"model={self._config.provider.model}",
        )
        self._ctrl = controller_factory(self._config)
        self._poll_timer: Optional[QTimer] = None
        self._polling = False
        self._pending_answer = False
        self._is_shutdown = False
        self._ui_hooks_factory = ui_hooks_factory
        self._ui_hooks = None

        # Tab-to-ChatView mapping
        self._chat_views: Dict[str, ChatView] = {}
        # Tab-id stored as widget property for lookup
        self._tab_id_for_index: Dict[int, str] = {}

        def _warm_oauth() -> None:
            try:
                _resolve_auth_cached()
            except Exception as e:
                log_debug(f"OAuth warm-up failed: {e}")

        threading.Thread(target=_warm_oauth, daemon=True).start()
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(DARK_THEME)
        self.setObjectName("iris_panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Tab widget with custom tab bar ---
        self._tab_widget = QTabWidget()
        self._tab_bar = _AddButtonTabBar()
        self._tab_widget.setTabBar(self._tab_bar)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.tabCloseRequested.connect(self._on_close_tab)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.add_tab_requested.connect(self._on_new_tab)

        # Style the tab bar
        self._tab_widget.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar { background: #1e1e1e; border: none; }"
            "QTabBar::tab { background: #252526; color: #cccccc; padding: 2px 8px; "
            "border: none; border-right: 1px solid #3c3c3c; "
            "font-size: 11px; max-width: 140px; }"
            "QTabBar::tab:selected { background: #1e1e1e; color: #ffffff; }"
            "QTabBar::tab:hover { background: #2d2d2d; }"
            "QTabBar::close-button { image: none; border: none; padding: 1px; }"
            "QTabBar::close-button:hover { background: #c42b1c; border-radius: 2px; }"
        )

        self._tab_bar.setExpanding(False)

        # Hide tab bar when there's only one tab
        self._tab_bar.setVisible(False)

        layout.addWidget(self._tab_widget, 1)

        # Create the initial tab
        self._create_tab(self._ctrl.active_tab_id, "New Chat")

        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(8, 4, 8, 4)

        self._input_area = InputArea()
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

        small_btn_style = (
            "QPushButton { background: #2d2d2d; color: #d4d4d4; border: 1px solid #3c3c3c; "
            "border-radius: 6px; padding: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #3c3c3c; }"
        )

        self._new_btn = QPushButton("New")
        self._new_btn.setFixedWidth(64)
        self._new_btn.setStyleSheet(small_btn_style)
        self._new_btn.clicked.connect(self._on_new_tab)
        btn_layout.addWidget(self._new_btn)

        self._settings_btn = QPushButton("Settings")
        self._settings_btn.setFixedWidth(64)
        self._settings_btn.setStyleSheet(small_btn_style)
        self._settings_btn.clicked.connect(self._on_settings)
        btn_layout.addWidget(self._settings_btn)

        btn_layout.addStretch()
        input_layout.addLayout(btn_layout)
        layout.addWidget(input_container)

        self._context_bar = ContextBar()
        self._context_bar.set_model(self._config.provider.model)
        layout.addWidget(self._context_bar)

        if self._ui_hooks_factory is not None:
            try:
                self._ui_hooks = self._ui_hooks_factory(lambda: self)
                self._ui_hooks.hook()
            except Exception as e:
                log_debug(f"UI hook setup failed: {e}")
                self._ui_hooks = None

        self._try_restore_session()

    # --- Tab management ---

    def _update_tab_bar_visibility(self) -> None:
        """Show the tab bar only when there are 2+ tabs."""
        self._tab_bar.setVisible(self._tab_widget.count() > 1)

    def _create_tab(self, tab_id: str, label: str) -> ChatView:
        """Create a new ChatView and add it as a tab."""
        chat_view = ChatView()
        self._chat_views[tab_id] = chat_view
        index = self._tab_widget.addTab(chat_view, label)
        self._tab_widget.setCurrentIndex(index)
        self._update_tab_bar_visibility()
        return chat_view

    def _on_new_tab(self) -> None:
        """Create a new chat tab."""
        if self._is_shutdown:
            return
        tab_id = self._ctrl.create_tab()
        self._create_tab(tab_id, "New Chat")
        self._ctrl.switch_tab(tab_id)

    def _on_close_tab(self, index: int) -> None:
        """Close a tab. Prevents closing the last tab."""
        if self._tab_widget.count() <= 1:
            return  # Don't close the last tab
        tab_id = self._tab_id_at_index(index)
        if tab_id is None:
            return
        self._ctrl.close_tab(tab_id)
        chat_view = self._chat_views.pop(tab_id, None)
        self._tab_widget.removeTab(index)
        if chat_view:
            chat_view.shutdown()
            chat_view.deleteLater()
        self._update_tab_bar_visibility()

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab switch."""
        if index < 0 or self._is_shutdown:
            return
        tab_id = self._tab_id_at_index(index)
        if tab_id is None:
            return
        self._ctrl.switch_tab(tab_id)
        session = self._ctrl.session
        self._context_bar.set_tokens(session.total_usage.total_tokens)

    def _tab_id_at_index(self, index: int) -> Optional[str]:
        """Find the tab_id for a given tab index by matching the widget."""
        widget = self._tab_widget.widget(index)
        if widget is None:
            return None
        for tid, cv in self._chat_views.items():
            if cv is widget:
                return tid
        return None

    def _active_chat_view(self) -> Optional[ChatView]:
        """Return the ChatView for the currently active tab."""
        return self._chat_views.get(self._ctrl.active_tab_id)

    def _update_tab_label(self, tab_id: str) -> None:
        """Update tab label from the first user message."""
        label = self._ctrl.tab_label(tab_id)
        cv = self._chat_views.get(tab_id)
        if cv is None:
            return
        for i in range(self._tab_widget.count()):
            if self._tab_widget.widget(i) is cv:
                self._tab_widget.setTabText(i, label)
                break

    # --- Public API ---

    def prefill_input(self, text: str, auto_submit: bool = False) -> None:
        self._input_area.setPlainText(text)
        if auto_submit:
            self._input_area.clear()
            self._on_submit(text)
        else:
            self._input_area.setFocus()

    def shutdown(self) -> None:
        if self._is_shutdown:
            return
        self._is_shutdown = True
        try:
            self._stop_poll_timer()
            if self._context_bar:
                self._context_bar.stop()
            for cv in self._chat_views.values():
                cv.shutdown()
            if self._ui_hooks:
                self._ui_hooks.unhook()
                self._ui_hooks = None
            self._ctrl.shutdown()
        except Exception as e:
            log_error(f"Panel teardown error: {e}")

    def on_database_changed(self, new_path: str) -> None:
        """Called when the user opens a different file."""
        if new_path == self._ctrl._idb_path:
            return
        self._ctrl.reset_for_new_file(new_path)
        # Remove all existing tabs
        for cv in self._chat_views.values():
            cv.shutdown()
        while self._tab_widget.count():
            w = self._tab_widget.widget(0)
            self._tab_widget.removeTab(0)
            if w:
                w.deleteLater()
        self._chat_views.clear()
        # Create default tab and try to restore saved sessions
        self._create_tab(self._ctrl.active_tab_id, "New Chat")
        self._try_restore_session()

    def _on_submit(self, text: str) -> None:
        if not text or self._is_shutdown:
            return
        chat_view = self._active_chat_view()
        if chat_view is None:
            return
        if self._pending_answer:
            self._pending_answer = False
            chat_view.add_user_message(text)
            self._set_running(True)
            runner = self._ctrl.get_runner()
            if runner:
                runner.agent_loop.submit_user_answer(text)
            return
        if self._ctrl.is_agent_running:
            self._ctrl.queue_message(text)
            chat_view.add_queued_message(text)
            return
        self._start_agent(text)

    def _on_send_clicked(self) -> None:
        text = self._input_area.toPlainText().strip()
        if text:
            self._input_area.clear()
            self._on_submit(text)

    def _on_cancel(self) -> None:
        if self._is_shutdown:
            return
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
        """Reset the current tab to a new chat."""
        if self._ctrl.is_agent_running or self._is_shutdown:
            return
        self._ctrl.new_chat()
        chat_view = self._active_chat_view()
        if chat_view:
            chat_view.clear_chat()
        self._context_bar.set_tokens(0)
        self._update_tab_label(self._ctrl.active_tab_id)

    def _start_agent(self, user_message: str) -> None:
        chat_view = self._active_chat_view()
        if chat_view is None:
            return
        chat_view.add_user_message(user_message)
        self._set_running(True)

        # Update tab label after first user message
        self._update_tab_label(self._ctrl.active_tab_id)

        error = self._ctrl.start_agent(user_message)
        if error:
            chat_view.add_error_message(error)
            self._set_running(False)
            return

        self._ensure_poll_timer()
        self._poll_timer.start(50)

    def _ensure_poll_timer(self) -> None:
        if self._poll_timer is not None:
            return
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_events)

    def _stop_poll_timer(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            try:
                self._poll_timer.timeout.disconnect(self._poll_events)
            except (RuntimeError, TypeError):
                pass
            self._poll_timer.deleteLater()
            self._poll_timer = None

    def _poll_events(self) -> None:
        if self._polling or self._is_shutdown:
            return
        self._polling = True
        try:
            for _ in range(20):
                event = self._ctrl.get_event(timeout=0)
                if event is None:
                    if not self._ctrl.is_agent_running:
                        self._on_agent_finished()
                    return
                self._on_event(event)
        finally:
            self._polling = False

    def _on_event(self, event: TurnEvent) -> None:
        if self._is_shutdown:
            return
        chat_view = self._active_chat_view()
        if chat_view is None:
            return
        chat_view.handle_event(event)
        if event.usage:
            self._context_bar.set_tokens(self._ctrl.session.total_usage.total_tokens)
        if event.type == TurnEventType.USER_QUESTION:
            self._pending_answer = True
            self._set_running(False)

    def _on_agent_finished(self) -> None:
        if self._is_shutdown:
            return
        if self._poll_timer:
            self._poll_timer.stop()
        self._set_running(False)

        next_msg = self._ctrl.on_agent_finished()
        if next_msg:
            self._start_agent(next_msg)

    def _try_restore_session(self) -> None:
        restored = self._ctrl.restore_sessions()
        if restored:
            # Remove the default empty tab if it was replaced
            default_cv = None
            for tid, cv in list(self._chat_views.items()):
                if tid not in self._ctrl.tab_ids:
                    # This tab was removed during restore
                    for i in range(self._tab_widget.count()):
                        if self._tab_widget.widget(i) is cv:
                            self._tab_widget.removeTab(i)
                            break
                    cv.shutdown()
                    cv.deleteLater()
                    del self._chat_views[tid]

            for tab_id, session in restored:
                label = self._ctrl.tab_label(tab_id)
                chat_view = self._create_tab(tab_id, label)
                chat_view.restore_from_messages(session.messages)

            # Activate the last (most recent) tab
            if restored:
                last_tab_id = restored[-1][0]
                cv = self._chat_views.get(last_tab_id)
                if cv:
                    for i in range(self._tab_widget.count()):
                        if self._tab_widget.widget(i) is cv:
                            self._tab_widget.setCurrentIndex(i)
                            break
                session = self._ctrl.session
                self._context_bar.set_tokens(session.total_usage.total_tokens)
        else:
            # No saved sessions — try legacy single-session restore
            session = self._ctrl.restore_session()
            if session:
                chat_view = self._active_chat_view()
                if chat_view:
                    chat_view.restore_from_messages(session.messages)
                self._context_bar.set_tokens(session.total_usage.total_tokens)

    def _set_running(self, running: bool) -> None:
        self._input_area.set_enabled(not running)
        self._send_btn.setVisible(not running)
        self._send_btn.setEnabled(not running)
        self._cancel_btn.setVisible(running)
