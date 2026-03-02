"""IRIS configuration with JSON persistence."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict

from ..constants import (
    CONFIG_DIR_NAME,
    CONFIG_FILE_NAME,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    MCP_CONFIG_FILE,
    SKILLS_DIR_NAME,
)
from .host import get_user_config_base_dir


def _default_config_dir() -> str:
    return os.path.join(get_user_config_base_dir(), CONFIG_DIR_NAME)


@dataclass
class ProviderConfig:
    name: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    api_base: str = ""
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    context_window: int = DEFAULT_CONTEXT_WINDOW
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IRISConfig:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    providers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    auto_context: bool = True
    plan_mode_default: bool = False
    checkpoint_auto_save: bool = True
    theme: str = "dark"

    _config_dir: str = field(default_factory=_default_config_dir, repr=False)

    @property
    def config_path(self) -> str:
        return os.path.join(self._config_dir, CONFIG_FILE_NAME)

    @property
    def checkpoints_dir(self) -> str:
        return os.path.join(self._config_dir, "checkpoints")

    @property
    def skills_dir(self) -> str:
        return os.path.join(self._config_dir, SKILLS_DIR_NAME)

    @property
    def mcp_config_path(self) -> str:
        return os.path.join(self._config_dir, MCP_CONFIG_FILE)

    def save(self) -> None:
        os.makedirs(self._config_dir, exist_ok=True)
        # Snapshot current provider into the providers dict before saving
        self._snapshot_current_provider()
        d = asdict(self)
        d.pop("_config_dir", None)
        with open(self.config_path, "w") as f:
            json.dump(d, f, indent=2)

    def load(self) -> None:
        if not os.path.exists(self.config_path):
            return
        with open(self.config_path, "r") as f:
            data = json.load(f)
        if "provider" in data:
            for k, v in data["provider"].items():
                if hasattr(self.provider, k):
                    setattr(self.provider, k, v)
        self.providers = data.get("providers", {})
        for k in ("auto_context", "plan_mode_default",
                   "checkpoint_auto_save", "theme"):
            if k in data:
                setattr(self, k, data[k])

    def _snapshot_current_provider(self) -> None:
        """Store current provider settings into the providers dict."""
        name = self.provider.name
        self.providers[name] = {
            "model": self.provider.model,
            "api_key": self.provider.api_key,
            "api_base": self.provider.api_base,
            "temperature": self.provider.temperature,
            "max_tokens": self.provider.max_tokens,
            "context_window": self.provider.context_window,
        }

    def switch_provider(self, new_name: str) -> None:
        """Switch to a different provider, preserving current settings.

        Saves the current provider's config and restores the new one
        (if previously configured).
        """
        self._snapshot_current_provider()
        self.provider.name = new_name

        saved = self.providers.get(new_name, {})
        if saved:
            self.provider.model = saved.get("model", "")
            self.provider.api_key = saved.get("api_key", "")
            self.provider.api_base = saved.get("api_base", "")
            self.provider.temperature = saved.get("temperature", DEFAULT_TEMPERATURE)
            self.provider.max_tokens = saved.get("max_tokens", DEFAULT_MAX_TOKENS)
            self.provider.context_window = saved.get("context_window", DEFAULT_CONTEXT_WINDOW)
        else:
            # Fresh provider — clear key/base, keep defaults
            self.provider.api_key = ""
            self.provider.api_base = ""
            self.provider.model = ""
            self.provider.temperature = DEFAULT_TEMPERATURE
            self.provider.max_tokens = DEFAULT_MAX_TOKENS
            self.provider.context_window = DEFAULT_CONTEXT_WINDOW

    @classmethod
    def load_or_create(cls) -> "IRISConfig":
        cfg = cls()
        cfg.load()
        return cfg
