"""IRIS configuration with JSON persistence."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from ..constants import (
    CONFIG_DIR_NAME,
    CONFIG_FILE_NAME,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    MCP_CONFIG_FILE,
    SKILLS_DIR_NAME,
)

_IDA_DIR: Optional[str] = None
try:
    import idaapi
    _IDA_DIR = idaapi.get_user_idadir()
except ImportError:
    _IDA_DIR = None  # Running outside IDA (tests, standalone)


def _default_config_dir() -> str:
    if _IDA_DIR:
        return os.path.join(_IDA_DIR, CONFIG_DIR_NAME)
    return os.path.join(Path.home(), ".idapro", CONFIG_DIR_NAME)


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
        for k in ("auto_context", "plan_mode_default",
                   "checkpoint_auto_save", "theme"):
            if k in data:
                setattr(self, k, data[k])

    @classmethod
    def load_or_create(cls) -> "IRISConfig":
        cfg = cls()
        cfg.load()
        return cfg
