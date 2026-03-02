"""IDA session controller."""

from __future__ import annotations

from iris.core.config import IRISConfig
from iris.core.host import get_database_path
from iris.ida.tools.registry import create_default_registry
from iris.ui.session_controller_base import SessionControllerBase


class SessionController(SessionControllerBase):
    """IDA-oriented controller."""

    def __init__(self, config: IRISConfig):
        super().__init__(
            config=config,
            tool_registry_factory=create_default_registry,
            database_path_getter=get_database_path,
            host_name="IDA Pro",
        )
