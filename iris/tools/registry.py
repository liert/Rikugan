"""Tool registry: discovers, stores, and dispatches tool calls."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from ..core.errors import ToolError, ToolNotFoundError, ToolValidationError
from ..core.logging import log_debug
from ..constants import TOOL_RESULT_TRUNCATE_LEN
from .base import ToolDefinition


class ToolRegistry:
    """Central registry of all available tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    @staticmethod
    def _coerce_arguments(defn: ToolDefinition, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce mistyped tool arguments to match the schema.

        LLMs sometimes send integers as strings (e.g. "30" instead of 30).
        Walk the parameter schema and cast values to their declared types.
        """
        if not defn.parameters or not arguments:
            return arguments

        param_types = {p.name: p.type for p in defn.parameters}
        coerced = dict(arguments)

        for key, value in coerced.items():
            expected = param_types.get(key)
            if expected is None:
                continue

            try:
                if expected == "integer" and not isinstance(value, int):
                    # Handle "30", "30.0", "0x1e" etc.
                    coerced[key] = int(float(value))
                elif expected == "integer" and isinstance(value, bool):
                    # bool is a subclass of int but should be coerced to plain int
                    coerced[key] = int(value)
                elif expected == "number" and not isinstance(value, (int, float)):
                    coerced[key] = float(value)
                elif expected == "boolean" and not isinstance(value, bool):
                    coerced[key] = str(value).lower() in ("true", "1", "yes")
                elif expected == "string" and not isinstance(value, str):
                    coerced[key] = str(value)
            except (ValueError, TypeError):
                pass  # Let the handler raise a proper validation error

        return coerced

    def register(self, defn: ToolDefinition) -> None:
        self._tools[defn.name] = defn
        log_debug(f"Registered tool: {defn.name}")

    def register_function(self, func: Callable[..., Any]) -> None:
        defn = getattr(func, "_tool_definition", None)
        if defn is None:
            raise ValueError(f"{func.__name__} is not decorated with @tool")
        self.register(defn)

    def register_module(self, module: Any) -> None:
        """Register all @tool-decorated functions in a module."""
        for name in dir(module):
            obj = getattr(module, name)
            if callable(obj) and isinstance(getattr(obj, "_tool_definition", None), ToolDefinition):
                self.register(obj._tool_definition)

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def list_names(self) -> List[str]:
        return list(self._tools.keys())

    def to_provider_format(self) -> List[Dict[str, Any]]:
        return [t.to_provider_format() for t in self._tools.values()]

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        defn = self._tools.get(name)
        if defn is None:
            raise ToolNotFoundError(f"Unknown tool: {name}", tool_name=name)
        if defn.handler is None:
            raise ToolError(f"Tool {name} has no handler", tool_name=name)

        arguments = self._coerce_arguments(defn, arguments)

        try:
            result = defn.handler(**arguments)
        except (ToolError, ToolValidationError):
            raise
        except TypeError as e:
            raise ToolValidationError(
                f"Invalid arguments for {name}: {e}", tool_name=name
            ) from e
        except Exception as e:
            raise ToolError(f"Tool {name} failed: {e}", tool_name=name) from e

        result_str = self._format_result(result)
        if len(result_str) > TOOL_RESULT_TRUNCATE_LEN:
            result_str = result_str[:TOOL_RESULT_TRUNCATE_LEN] + "\n... (truncated)"
        return result_str

    @staticmethod
    def _format_result(result: Any) -> str:
        if result is None:
            return "OK"
        if isinstance(result, str):
            return result
        if isinstance(result, (dict, list)):
            return json.dumps(result, indent=2, default=str)
        return str(result)


def create_default_registry() -> ToolRegistry:
    """Create a registry with all built-in IDA tools.

    Backward-compat shim — canonical location is iris.ida.tools.registry.
    """
    from ..ida.tools.registry import create_default_registry as _create
    return _create()
