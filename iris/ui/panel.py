"""Backward-compatible panel import path."""

from __future__ import annotations

from ..core.host import is_binary_ninja, is_ida

if is_binary_ninja():
    from ..hosts.binary_ninja.panel import IRISPanel  # noqa: F401
elif is_ida():
    from ..hosts.ida.panel import IRISPanel  # noqa: F401
else:
    from .panel_core import IRISPanelCore as IRISPanel  # noqa: F401

