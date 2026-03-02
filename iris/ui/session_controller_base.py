"""Host-agnostic session controller orchestration."""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from ..core.config import IRISConfig
from ..core.logging import log_debug, log_error, log_info
from ..agent.loop import AgentLoop, BackgroundAgentRunner
from ..agent.turn import TurnEvent
from ..providers.registry import ProviderRegistry
from ..skills.registry import SkillRegistry
from ..mcp.manager import MCPManager
from ..state.session import SessionState
from ..state.history import SessionHistory
if TYPE_CHECKING:
    from ..tools.registry import ToolRegistry
else:
    ToolRegistry = Any


class SessionControllerBase:
    """Non-Qt orchestrator for IRIS sessions."""

    def __init__(
        self,
        config: IRISConfig,
        tool_registry_factory: Callable[[], ToolRegistry],
        database_path_getter: Callable[[], str],
        host_name: str,
    ):
        self.config = config
        self.host_name = host_name
        self._provider_registry = ProviderRegistry()
        self._tool_registry = tool_registry_factory()
        self._skill_registry = SkillRegistry()
        self._skill_registry.discover()
        self._mcp_manager = MCPManager()
        self._mcp_manager.load_config()
        self._idb_path = database_path_getter()

        # Multi-tab session management
        self._sessions: Dict[str, SessionState] = {}
        self._active_tab_id: str = ""
        tab_id = self._create_session()
        self._active_tab_id = tab_id

        self._runner: Optional[BackgroundAgentRunner] = None
        self._pending_messages: List[str] = []

        self._mcp_manager.start_servers(self._tool_registry)

    # --- Tab / multi-session management ---

    def _create_session(self) -> str:
        """Create a new SessionState and return its tab_id."""
        tab_id = uuid.uuid4().hex[:8]
        session = SessionState(
            provider_name=self.config.provider.name,
            model_name=self.config.provider.model,
            idb_path=self._idb_path,
        )
        self._sessions[tab_id] = session
        return tab_id

    def create_tab(self) -> str:
        """Create a new tab with a fresh session. Returns tab_id."""
        tab_id = self._create_session()
        log_info(f"Created new tab {tab_id}")
        return tab_id

    def close_tab(self, tab_id: str) -> None:
        """Save and remove a tab's session."""
        session = self._sessions.get(tab_id)
        if session is None:
            return
        if self.config.checkpoint_auto_save and session.messages:
            try:
                history = SessionHistory(self.config)
                history.save_session(session)
            except Exception as e:
                log_error(f"Failed to save session on tab close: {e}")
        del self._sessions[tab_id]
        log_debug(f"Closed tab {tab_id}")

    def switch_tab(self, tab_id: str) -> None:
        """Switch active tab. Cancels running agent if switching away."""
        if tab_id == self._active_tab_id:
            return
        if tab_id not in self._sessions:
            return
        if self.is_agent_running:
            self.cancel()
        self._active_tab_id = tab_id
        log_debug(f"Switched to tab {tab_id}")

    def tab_label(self, tab_id: str) -> str:
        """Return a display label for a tab."""
        session = self._sessions.get(tab_id)
        if session is None:
            return "New Chat"
        for msg in session.messages:
            if msg.role.value == "user" and msg.content:
                text = msg.content.strip()
                return text[:20] + ("..." if len(text) > 20 else "")
        return "New Chat"

    @property
    def active_tab_id(self) -> str:
        return self._active_tab_id

    @property
    def tab_ids(self) -> List[str]:
        return list(self._sessions.keys())

    @property
    def session(self) -> SessionState:
        return self._sessions[self._active_tab_id]

    @property
    def provider_registry(self) -> ProviderRegistry:
        return self._provider_registry

    @property
    def skill_slugs(self) -> List[str]:
        return self._skill_registry.list_slugs()

    @property
    def is_agent_running(self) -> bool:
        return self._runner is not None and self._runner.agent_loop.is_running

    def get_runner(self) -> Optional[BackgroundAgentRunner]:
        return self._runner

    def start_agent(self, user_message: str) -> Optional[str]:
        """Create provider + agent loop and start the background runner."""
        try:
            provider = self._provider_registry.get_or_create(
                self.config.provider.name,
                api_key=self.config.provider.api_key,
                api_base=self.config.provider.api_base,
                model=self.config.provider.model,
            )
            provider.ensure_ready()
        except Exception as e:
            log_error(f"Provider creation failed: {e}")
            return f"Provider error: {e}"

        loop = AgentLoop(
            provider,
            self._tool_registry,
            self.config,
            self._sessions[self._active_tab_id],
            skill_registry=self._skill_registry,
            host_name=self.host_name,
        )
        self._runner = BackgroundAgentRunner(loop)
        self._runner.start(user_message)
        return None

    def get_event(self, timeout: float = 0) -> Optional[TurnEvent]:
        if self._runner is None:
            return None
        return self._runner.get_event(timeout=timeout)

    def cancel(self) -> None:
        self._pending_messages.clear()
        if self._runner:
            self._runner.cancel()

    def queue_message(self, text: str) -> None:
        self._pending_messages.append(text)
        log_debug(f"Message queued, {len(self._pending_messages)} pending")

    def on_agent_finished(self) -> Optional[str]:
        self._runner = None

        session = self._sessions.get(self._active_tab_id)
        if session and self.config.checkpoint_auto_save and session.messages:
            try:
                history = SessionHistory(self.config)
                path = history.save_session(session)
                log_debug(f"Session auto-saved: {path}")
            except Exception as e:
                log_error(f"Failed to auto-save session: {e}")

        if self._pending_messages:
            return self._pending_messages.pop(0)
        return None

    def new_chat(self) -> None:
        """Reset the active tab to a fresh session."""
        self._pending_messages.clear()
        session = self._sessions.get(self._active_tab_id)
        if session and self.config.checkpoint_auto_save and session.messages:
            try:
                history = SessionHistory(self.config)
                history.save_session(session)
            except OSError as e:
                log_debug(f"Failed to save session on new chat: {e}")
        self._sessions[self._active_tab_id] = SessionState(
            provider_name=self.config.provider.name,
            model_name=self.config.provider.model,
            idb_path=self._idb_path,
        )
        log_info("Started new chat session (active tab)")

    def restore_sessions(self) -> List[Tuple[str, SessionState]]:
        """Load ALL saved sessions for the current idb_path and return (tab_id, session) pairs."""
        results: List[Tuple[str, SessionState]] = []
        try:
            history = SessionHistory(self.config)
            summaries = history.list_sessions(idb_path=self._idb_path)
            summaries.sort(key=lambda s: s.get("created_at", 0))
            for summary in summaries:
                session = history.load_session(summary["id"])
                if session and session.messages:
                    tab_id = uuid.uuid4().hex[:8]
                    self._sessions[tab_id] = session
                    results.append((tab_id, session))
                    log_debug(f"Restored session {session.id} as tab {tab_id}")
        except Exception as e:
            log_error(f"Failed to restore sessions: {e}")
        if results:
            # Remove the default empty session that was created in __init__
            # and set the first restored tab as active
            if self._active_tab_id in self._sessions:
                default_session = self._sessions[self._active_tab_id]
                if not default_session.messages:
                    del self._sessions[self._active_tab_id]
            self._active_tab_id = results[-1][0]  # most recent
        return results

    def restore_session(self) -> Optional[SessionState]:
        """Legacy: restore only the latest session into the active tab."""
        try:
            history = SessionHistory(self.config)
            session = history.get_latest_session(idb_path=self._idb_path)
            if session and session.messages:
                log_debug(f"Restoring session {session.id} with {len(session.messages)} messages")
                self._sessions[self._active_tab_id] = session
                log_info(f"Restored session {session.id} ({len(session.messages)} messages)")
                return session
        except Exception as e:
            log_error(f"Failed to restore session: {e}")
        return None

    def reset_for_new_file(self, new_idb_path: str) -> None:
        """Save all sessions and reset for a new database file."""
        self.cancel()
        for tab_id, session in self._sessions.items():
            if session.messages:
                try:
                    history = SessionHistory(self.config)
                    history.save_session(session)
                except Exception as e:
                    log_error(f"Failed to save session {tab_id} on file change: {e}")
        self._sessions.clear()
        self._idb_path = new_idb_path
        tab_id = self._create_session()
        self._active_tab_id = tab_id

    def update_settings(self) -> None:
        for session in self._sessions.values():
            session.provider_name = self.config.provider.name
            session.model_name = self.config.provider.model

    def shutdown(self) -> None:
        if self._runner:
            self._runner.cancel()
            self._runner = None
        for tab_id, session in self._sessions.items():
            if self.config.checkpoint_auto_save and session.messages:
                try:
                    history = SessionHistory(self.config)
                    history.save_session(session)
                except Exception as e:
                    log_error(f"Failed to save session {tab_id} on shutdown: {e}")
        self._mcp_manager.stop_all()
