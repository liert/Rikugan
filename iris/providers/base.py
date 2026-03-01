"""LLM provider abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional, Tuple

from ..core.logging import log_debug
from ..core.thread_safety import shiboken_bypass
from ..core.types import Message, ModelInfo, ProviderCapabilities, StreamChunk, TokenUsage


class LLMProvider(ABC):
    """Abstract base for all LLM provider adapters.

    Subclasses must implement: ``name``, ``capabilities``, ``chat``,
    ``chat_stream``, ``_get_client``, ``_fetch_models_live``,
    ``_builtin_models``.

    Common patterns (lazy client init, list-models-with-fallback) are
    implemented here so that subclasses only override the provider-specific
    parts.
    """

    def __init__(self, api_key: str = "", api_base: str = "", model: str = ""):
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self._client: Any = None

    # -- Abstract interface ----------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g. 'anthropic', 'openai')."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Provider capabilities."""
        ...

    @abstractmethod
    def _get_client(self) -> Any:
        """Return the SDK client, creating it lazily if needed."""
        ...

    @abstractmethod
    def _fetch_models_live(self) -> List[ModelInfo]:
        """Fetch models from the remote API. May raise on failure."""
        ...

    @staticmethod
    @abstractmethod
    def _builtin_models() -> List[ModelInfo]:
        """Return built-in fallback model list (no network required)."""
        ...

    @abstractmethod
    def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        system: str = "",
    ) -> Message:
        """Non-streaming chat completion."""
        ...

    @abstractmethod
    def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        system: str = "",
    ) -> Generator[StreamChunk, None, None]:
        """Streaming chat completion. Yields StreamChunks."""
        ...

    # -- Concrete shared implementations ---------------------------------------

    def list_models(self) -> List[ModelInfo]:
        """List available models.

        Attempts a live API fetch via ``_fetch_models_live()``.  On any
        failure, logs the error and returns ``_builtin_models()`` so callers
        never see an exception.
        """
        try:
            return self._fetch_models_live()
        except Exception as exc:
            log_debug(f"{self.name} list_models failed, using builtins: {exc}")
            return self._builtin_models()

    def _format_messages(self, messages: List[Message]) -> Any:
        """Convert internal messages to provider wire format. Override per provider."""
        raise NotImplementedError

    def _normalize_response(self, raw: Any) -> Message:
        """Convert provider response to internal Message. Override per provider."""
        raise NotImplementedError

    def ensure_ready(self) -> None:
        """Pre-initialize the provider (imports, client objects, etc.).

        MUST be called on the main thread before handing the provider to a
        background thread.  Python 3.14 crashes when heavy C-extension
        packages (httpx, h2, ssl …) are first imported from a non-main
        thread, so providers that lazy-import SDK packages override
        ``_init_client`` to force the import on the caller's thread.

        The Shiboken bypass is applied here so callers don't need to know
        about the PySide6 import hook workaround.
        """
        with shiboken_bypass():
            self._init_client()

    def _init_client(self) -> None:
        """Pre-import SDK and create client. Delegates to ``_get_client()``."""
        self._get_client()

    def auth_status(self) -> Tuple[str, str]:
        """Return (label, status_type) describing the current auth state.

        status_type is one of: "ok", "error", "none".
        Subclasses override for provider-specific logic (e.g. OAuth detection).
        """
        if self.api_key:
            return "API Key", "ok"
        return "", "none"

    def validate_key(self) -> bool:
        """Quick check that the API key is valid."""
        try:
            self.list_models()
            return True
        except Exception as e:
            log_debug(f"validate_key failed for {self.name}: {e}")
            return False
