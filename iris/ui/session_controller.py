"""Session controller: orchestrates provider, tools, agent loop, and session state.

This is a plain Python class with no Qt dependencies, making the orchestration
logic testable without a running Qt event loop.
"""

from __future__ import annotations

import importlib
from typing import List, Optional

from ..core.config import IRISConfig
from ..core.logging import log_debug, log_error, log_info
from ..agent.loop import AgentLoop, BackgroundAgentRunner
from ..agent.turn import TurnEvent
from ..providers.registry import ProviderRegistry
from ..tools.registry import create_default_registry
from ..skills.registry import SkillRegistry
from ..mcp.manager import MCPManager
from ..state.session import SessionState
from ..state.history import SessionHistory


def _get_idb_path() -> str:
    """Get the path of the currently loaded IDB/binary file."""
    try:
        idaapi = importlib.import_module("idaapi")
        idb = idaapi.get_path(idaapi.PATH_TYPE_IDB)
        if idb:
            return idb
        return idaapi.get_input_file_path() or ""
    except Exception:
        return ""


class SessionController:
    """Non-Qt orchestrator for IRIS sessions.

    Owns provider/tool/skill/MCP registries, the session state, the agent
    runner, and the pending-message queue.  The UI layer (IRISPanel) delegates
    all business logic here and handles only Qt wiring.
    """

    def __init__(self, config: IRISConfig):
        self.config = config
        self._provider_registry = ProviderRegistry()
        self._tool_registry = create_default_registry()
        self._skill_registry = SkillRegistry()
        self._skill_registry.discover()
        self._mcp_manager = MCPManager()
        self._mcp_manager.load_config()
        self._idb_path = _get_idb_path()
        self._session = SessionState(
            provider_name=config.provider.name,
            model_name=config.provider.model,
            idb_path=self._idb_path,
        )
        self._runner: Optional[BackgroundAgentRunner] = None
        self._pending_messages: List[str] = []

        # Start MCP servers — their tools register into _tool_registry
        self._mcp_manager.start_servers(self._tool_registry)

    # -- Properties --

    @property
    def session(self) -> SessionState:
        return self._session

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
        """Return the current BackgroundAgentRunner, or None."""
        return self._runner

    # -- Agent lifecycle --

    def start_agent(self, user_message: str) -> Optional[str]:
        """Create provider + agent loop and start the background runner.

        Returns an error message string on failure, or None on success.
        """
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
            provider, self._tool_registry, self.config, self._session,
            skill_registry=self._skill_registry,
        )
        self._runner = BackgroundAgentRunner(loop)
        self._runner.start(user_message)
        return None

    def get_event(self, timeout: float = 0) -> Optional[TurnEvent]:
        """Get the next event from the agent runner, or None."""
        if self._runner is None:
            return None
        return self._runner.get_event(timeout=timeout)

    def cancel(self) -> None:
        """Cancel the running agent and clear pending messages."""
        self._pending_messages.clear()
        if self._runner:
            self._runner.cancel()

    def queue_message(self, text: str) -> None:
        """Queue a message to send after the current agent run finishes."""
        self._pending_messages.append(text)
        log_debug(f"Message queued, {len(self._pending_messages)} pending")

    def on_agent_finished(self) -> Optional[str]:
        """Handle agent completion: auto-save, return next queued message.

        Returns the next pending user message if any, or None.
        """
        self._runner = None

        if self.config.checkpoint_auto_save and self._session.messages:
            try:
                history = SessionHistory(self.config)
                path = history.save_session(self._session)
                log_debug(f"Session auto-saved: {path}")
            except Exception as e:
                log_error(f"Failed to auto-save session: {e}")

        if self._pending_messages:
            return self._pending_messages.pop(0)
        return None

    # -- Session management --

    def new_chat(self) -> None:
        """Save current session and create a fresh one."""
        self._pending_messages.clear()
        if self.config.checkpoint_auto_save and self._session.messages:
            try:
                history = SessionHistory(self.config)
                history.save_session(self._session)
            except OSError as e:
                log_debug(f"Failed to save session on new chat: {e}")
        self._session = SessionState(
            provider_name=self.config.provider.name,
            model_name=self.config.provider.model,
            idb_path=self._idb_path,
        )
        log_info("Started new chat session")

    def restore_session(self) -> Optional[SessionState]:
        """Restore the most recent session for this IDB. Returns it if found, else None."""
        try:
            history = SessionHistory(self.config)
            session = history.get_latest_session(idb_path=self._idb_path)
            if session and session.messages:
                log_debug(f"Restoring session {session.id} with {len(session.messages)} messages")
                self._session = session
                log_info(f"Restored session {session.id} ({len(session.messages)} messages)")
                return session
        except Exception as e:
            log_error(f"Failed to restore session: {e}")
        return None

    def update_settings(self) -> None:
        """Sync session state with current config after settings change."""
        self._session.provider_name = self.config.provider.name
        self._session.model_name = self.config.provider.model

    # -- Shutdown --

    def shutdown(self) -> None:
        """Stop MCP servers and cancel any running agent."""
        if self._runner:
            self._runner.cancel()
            self._runner = None
        self._mcp_manager.stop_all()
