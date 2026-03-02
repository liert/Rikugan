"""Binary Ninja session controller."""

from __future__ import annotations

from ...core.config import IRISConfig
from ...core.host import get_database_path
from ..tools.registry import create_default_registry
from ...ui.session_controller_base import SessionControllerBase


class BinaryNinjaSessionController(SessionControllerBase):
    """Binary Ninja-oriented controller."""

    def __init__(self, config: IRISConfig):
        super().__init__(
            config=config,
            tool_registry_factory=create_default_registry,
            database_path_getter=get_database_path,
            host_name="Binary Ninja",
        )
