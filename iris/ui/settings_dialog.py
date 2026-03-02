"""Settings dialog for provider, model, API key, and temperature configuration."""

from __future__ import annotations

import queue
import threading
from typing import List, Optional

from .qt_compat import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QComboBox, QLineEdit, QDoubleSpinBox, QSpinBox, QCheckBox,
    QLabel, QPushButton, QWidget, Qt, QTimer,
)
from ..core.config import IRISConfig
from ..core.logging import log_debug, log_error
from ..core.types import ModelInfo
from ..providers.anthropic_provider import resolve_anthropic_auth
from ..providers.ollama_provider import DEFAULT_OLLAMA_URL
from ..providers.registry import ProviderRegistry

# Known default API base URLs per provider — used to auto-clear on switch
_PROVIDER_BASES = {
    "ollama": DEFAULT_OLLAMA_URL,
}

# Placeholder/default keys that should be cleared on provider switch
_PROVIDER_DEFAULT_KEYS = {"ollama"}

# Module-level cache to avoid subprocess.run during widget construction
_cached_oauth: Optional[tuple] = None  # (token, auth_type)


def _resolve_auth_cached(explicit_key: str = "") -> tuple:
    """Resolve Anthropic auth with caching to avoid subprocess spawns.

    Uses the module-level ``resolve_anthropic_auth`` import (resolved
    during the Shiboken bypass window) so no runtime ``from`` import
    goes through the hook.
    """
    global _cached_oauth
    if explicit_key:
        return resolve_anthropic_auth(explicit_key)
    if _cached_oauth is not None:
        return _cached_oauth
    _cached_oauth = resolve_anthropic_auth("")
    return _cached_oauth


class _ModelFetcher:
    """Fetches models in a background thread. Results collected via queue.

    This is a plain Python class — no QObject, no Qt signals.
    Results are polled from the main thread via a QTimer, eliminating
    all cross-thread Shiboken/PySide6 signal delivery crashes.
    """

    def __init__(self, registry: ProviderRegistry):
        self._registry = registry
        self._queue: queue.Queue = queue.Queue()
        self._alive = True

    def shutdown(self) -> None:
        self._alive = False
        # Drain the queue to unblock any pending puts
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def fetch(self, provider_name: str, api_key: str, api_base: str) -> None:
        # Create the provider and pre-import its SDK on the MAIN thread.
        # Python 3.14 crashes when heavy C-extension packages are first
        # imported from a background thread.
        try:
            provider = self._registry.create(
                provider_name, api_key=api_key, api_base=api_base,
            )
            provider.ensure_ready()
        except Exception as e:
            if self._alive:
                self._queue.put(("error", str(e)))
            return

        def _run():
            try:
                models = provider.list_models()
                if self._alive:
                    self._queue.put(("models", models))
            except Exception as e:
                if self._alive:
                    self._queue.put(("error", str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def poll(self) -> Optional[tuple]:
        """Non-blocking poll. Returns ('models', list) or ('error', str) or None."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None


class SettingsDialog(QDialog):
    """Configuration dialog for IRIS."""

    def __init__(self, config: IRISConfig, registry: Optional[ProviderRegistry] = None, parent: QWidget = None):
        # Use None parent to avoid lifecycle coupling with IDA PluginForm widgets
        super().__init__(None)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._config = config
        self._registry = registry or ProviderRegistry()
        self._fetcher = _ModelFetcher(self._registry)
        self._fetched_models: List[ModelInfo] = []
        self._resolved_token: str = ""
        self._shown = False
        self._closed = False
        self.setWindowTitle("IRIS Settings")
        from .qt_compat import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.resize(min(int(avail.width() * 0.45), 900), min(int(avail.height() * 0.7), 800))
        else:
            self.resize(700, 600)
        self.setMinimumWidth(400)
        self._build_ui()

        # Poll timer for fetcher results — NO cross-thread signals
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_fetcher)
        self._poll_timer.start(150)

        # Deferred init timer — parented to self, safe if dialog closes instantly
        self._init_timer = QTimer(self)
        self._init_timer.setSingleShot(True)
        self._init_timer.setInterval(0)
        self._init_timer.timeout.connect(self._deferred_init)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- Provider group ---
        provider_group = QGroupBox("LLM Provider")
        provider_form = QFormLayout(provider_group)

        self._provider_combo = QComboBox()
        self._provider_combo.addItems([
            "anthropic", "openai", "gemini", "ollama", "openai_compat",
        ])
        idx = self._provider_combo.findText(self._config.provider.name)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        # Connect AFTER setting index so it doesn't fire during construction
        provider_form.addRow("Provider:", self._provider_combo)

        # API key — only show explicit user keys, NOT auto-resolved OAuth tokens
        key_layout = QHBoxLayout()
        self._api_key_edit = QLineEdit(self._config.provider.api_key)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("sk-... or leave empty for auto-detect")
        key_layout.addWidget(self._api_key_edit, 1)

        self._auth_status = QLabel()
        key_layout.addWidget(self._auth_status)
        provider_form.addRow("API Key:", key_layout)

        self._api_base_edit = QLineEdit(self._config.provider.api_base)
        self._api_base_edit.setPlaceholderText("Custom endpoint URL (optional)")
        provider_form.addRow("API Base:", self._api_base_edit)

        # Model dropdown with fetch button
        model_layout = QHBoxLayout()
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setMinimumWidth(300)
        self._model_combo.setCurrentText(self._config.provider.model)
        model_layout.addWidget(self._model_combo, 1)

        self._fetch_btn = QPushButton("Refresh")
        self._fetch_btn.setFixedWidth(70)
        self._fetch_btn.setStyleSheet(
            "QPushButton { background: #2d2d2d; color: #d4d4d4; border: 1px solid #3c3c3c; "
            "border-radius: 4px; padding: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #3c3c3c; }"
        )
        self._fetch_btn.clicked.connect(self._fetch_models)
        model_layout.addWidget(self._fetch_btn)

        self._model_status = QLabel()
        self._model_status.setStyleSheet("color: #808080; font-size: 10px;")
        self._model_status.setWordWrap(True)
        model_layout.addWidget(self._model_status)

        provider_form.addRow("Model:", model_layout)

        layout.addWidget(provider_group)

        # --- Generation group ---
        gen_group = QGroupBox("Generation")
        gen_form = QFormLayout(gen_group)

        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 2.0)
        self._temp_spin.setSingleStep(0.05)
        self._temp_spin.setDecimals(2)
        self._temp_spin.setValue(self._config.provider.temperature)
        gen_form.addRow("Temperature:", self._temp_spin)

        self._max_tokens_spin = QSpinBox()
        self._max_tokens_spin.setRange(256, 65536)
        self._max_tokens_spin.setSingleStep(1024)
        self._max_tokens_spin.setValue(self._config.provider.max_tokens)
        gen_form.addRow("Max Output Tokens:", self._max_tokens_spin)

        self._context_spin = QSpinBox()
        self._context_spin.setRange(4096, 2000000)
        self._context_spin.setSingleStep(10000)
        self._context_spin.setValue(self._config.provider.context_window)
        gen_form.addRow("Context Window:", self._context_spin)

        layout.addWidget(gen_group)

        # --- Behavior group ---
        behavior_group = QGroupBox("Behavior")
        behavior_form = QFormLayout(behavior_group)

        self._auto_context_cb = QCheckBox("Auto-inject binary context into system prompt")
        self._auto_context_cb.setChecked(self._config.auto_context)
        behavior_form.addRow(self._auto_context_cb)

        self._auto_save_cb = QCheckBox("Auto-save sessions")
        self._auto_save_cb.setChecked(self._config.checkpoint_auto_save)
        behavior_form.addRow(self._auto_save_cb)

        layout.addWidget(behavior_group)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Connect provider/key change signals AFTER everything is built
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self._api_key_edit.editingFinished.connect(self._on_key_edited)

    # --- Show event: defer all non-widget work to here ---

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._shown:
            self._shown = True
            # Defer auth resolution and model fetch to AFTER the dialog is painted.
            # This avoids subprocess.run() and background threads during construction.
            self._init_timer.start()

    def _deferred_init(self) -> None:
        """Runs after the dialog is fully painted. Safe for subprocesses/threads."""
        if self._closed:
            return
        try:
            self._update_auth_status()
            self._fetch_models()
        except Exception as e:
            log_error(f"SettingsDialog deferred init error: {e}")

    # --- Cleanup ---

    def done(self, result: int) -> None:
        self._closed = True
        try:
            self._init_timer.stop()
            self._poll_timer.stop()
        except RuntimeError:
            pass  # timer already destroyed during Qt cleanup  # noqa: S110
        self._fetcher.shutdown()
        super().done(result)

    # --- Fetcher polling (main thread only, no cross-thread signals) ---

    def _poll_fetcher(self) -> None:
        """Poll the fetcher queue from the main thread. Safe for Shiboken."""
        if self._closed:
            return
        result = self._fetcher.poll()
        if result is None:
            return
        try:
            kind, data = result
            if kind == "models":
                self._on_models_ready(data)
            elif kind == "error":
                self._on_fetch_error(data)
        except (ValueError, TypeError) as e:
            log_debug(f"Malformed fetcher result: {e}")

    # --- Provider switching ---

    def _on_provider_changed(self, provider: str) -> None:
        # Use config.switch_provider() to snapshot current & restore saved
        self._config.switch_provider(provider)

        # Update UI fields from the (possibly restored) config
        self._api_key_edit.setText(self._config.provider.api_key)
        self._api_base_edit.setText(self._config.provider.api_base)
        self._model_combo.setCurrentText(self._config.provider.model)
        self._temp_spin.setValue(self._config.provider.temperature)
        self._max_tokens_spin.setValue(self._config.provider.max_tokens)
        self._context_spin.setValue(self._config.provider.context_window)

        # Auto-fill API base for providers that need it
        if provider == "ollama" and not self._api_base_edit.text().strip():
            self._api_base_edit.setText(_PROVIDER_BASES["ollama"])

        # Update placeholder
        if provider == "anthropic":
            self._api_key_edit.setPlaceholderText("sk-... or leave empty for OAuth auto-detect")
        elif provider == "ollama":
            self._api_key_edit.setPlaceholderText("Not required for local Ollama")
        elif provider == "openai_compat":
            self._api_key_edit.setPlaceholderText("API key for the endpoint")
        else:
            self._api_key_edit.setPlaceholderText("API key")

        self._update_auth_status()
        self._fetch_models()

    def _on_key_edited(self) -> None:
        self._update_auth_status()
        self._fetch_models()

    # --- Auth status ---

    _OK_STYLE = "color: #4ec9b0; font-size: 11px; font-weight: bold;"
    _ERR_STYLE = "color: #f44747; font-size: 11px;"

    def _update_auth_status(self) -> None:
        provider_name = self._provider_combo.currentText()
        explicit_key = self._api_key_edit.text().strip()
        base = self._api_base_edit.text().strip()

        try:
            provider = self._registry.create(provider_name, api_key=explicit_key, api_base=base)
            label, status_type = provider.auth_status()
            self._resolved_token = provider.api_key
        except Exception as e:
            log_debug(f"Auth status check failed for {provider_name}: {e}")
            label, status_type = "", "none"
            self._resolved_token = ""

        if status_type == "ok":
            self._auth_status.setText(label)
            self._auth_status.setStyleSheet(self._OK_STYLE)
        elif status_type == "error":
            self._auth_status.setText(label)
            self._auth_status.setStyleSheet(self._ERR_STYLE)
        else:
            self._auth_status.setText("")
            self._auth_status.setStyleSheet("")

    # --- Model fetching ---

    def _fetch_models(self) -> None:
        provider = self._provider_combo.currentText()
        key = self._api_key_edit.text().strip()
        base = self._api_base_edit.text().strip()

        # For providers with auto-detect auth, use resolved token if no explicit key
        if not key and self._resolved_token:
            key = self._resolved_token

        self._model_status.setText("Fetching...")
        self._fetch_btn.setEnabled(False)
        self._fetcher.fetch(provider, key, base)

    def _on_models_ready(self, models: list) -> None:
        self._fetch_btn.setEnabled(True)
        self._fetched_models = models

        current_id = self._get_selected_model_id()
        self._model_combo.clear()
        for m in models:
            label = f"{m.name}  ({m.id})" if m.name != m.id else m.id
            self._model_combo.addItem(label, m.id)

        # Restore previous selection by model ID
        matched = False
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == current_id:
                self._model_combo.setCurrentIndex(i)
                matched = True
                break
        if not matched and models:
            # If the previous model ID doesn't match any fetched model
            # (e.g. stale error text, wrong provider), select the first one
            # instead of keeping garbage text in the editable combo.
            self._model_combo.setCurrentIndex(0)

        self._model_status.setText(f"{len(models)} models")
        self._model_status.setStyleSheet("color: #4ec9b0; font-size: 10px;")

        # Auto-fill generation defaults based on selected model
        self._update_generation_defaults()

    def _on_fetch_error(self, error: str) -> None:
        self._fetch_btn.setEnabled(True)
        self._model_status.setText(error)
        self._model_status.setStyleSheet("color: #f44747; font-size: 10px;")

    def _update_generation_defaults(self) -> None:
        model_id = self._get_selected_model_id()
        for m in self._fetched_models:
            if m.id == model_id:
                self._context_spin.setValue(m.context_window)
                self._max_tokens_spin.setValue(min(m.max_output_tokens, 16384))
                break

    def _get_selected_model_id(self) -> str:
        idx = self._model_combo.currentIndex()
        data = self._model_combo.itemData(idx) if idx >= 0 else None
        if data:
            return data
        return self._model_combo.currentText().strip()

    # --- Accept ---

    def _on_accept(self) -> None:
        self._config.provider.name = self._provider_combo.currentText()
        self._config.provider.model = self._get_selected_model_id()
        # ONLY save what the user explicitly typed — never save auto-resolved OAuth tokens
        self._config.provider.api_key = self._api_key_edit.text().strip()
        self._config.provider.api_base = self._api_base_edit.text().strip()
        self._config.provider.temperature = self._temp_spin.value()
        self._config.provider.max_tokens = self._max_tokens_spin.value()
        self._config.provider.context_window = self._context_spin.value()
        self._config.auto_context = self._auto_context_cb.isChecked()
        self._config.checkpoint_auto_save = self._auto_save_cb.isChecked()
        self.accept()
