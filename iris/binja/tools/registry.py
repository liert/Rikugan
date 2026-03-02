"""Binary Ninja tool registry.

Wires Binary Ninja-specific tool modules into the shared ToolRegistry.
"""

from __future__ import annotations

from ...tools.registry import ToolRegistry
from . import (
    navigation, functions, strings, database,
    disassembly, decompiler, xrefs, annotations,
    types_tools, scripting, il,
)

_TOOL_MODULES = (
    navigation, functions, strings, database,
    disassembly, decompiler, xrefs, annotations,
    types_tools, scripting, il,
)


def create_default_registry() -> ToolRegistry:
    """Create a Binary Ninja registry with all built-in BN tools."""
    registry = ToolRegistry()
    for mod in _TOOL_MODULES:
        registry.register_module(mod)
    return registry
