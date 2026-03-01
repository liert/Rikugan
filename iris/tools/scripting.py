"""Python scripting execution tool."""

from __future__ import annotations

import importlib
import io
import contextlib
from typing import Annotated

from .base import tool

# Cached namespace of common IDA modules — populated once, reused across calls.
_IDA_MODULE_NAMES = (
    "idaapi", "idautils", "idc", "ida_funcs", "ida_name",
    "ida_bytes", "ida_segment", "ida_struct", "ida_enum",
    "ida_typeinf", "ida_nalt", "ida_xref", "ida_kernwin",
)
_cached_namespace: dict | None = None


def _get_base_namespace() -> dict:
    """Return a cached namespace with common IDA modules pre-imported."""
    global _cached_namespace
    if _cached_namespace is None:
        ns: dict = {}
        for mod_name in _IDA_MODULE_NAMES:
            try:
                ns[mod_name] = importlib.import_module(mod_name)
            except ImportError:
                pass
        _cached_namespace = ns
    # Return a copy so user code can't pollute the cache
    result: dict = {"__builtins__": __builtins__}
    result.update(_cached_namespace)
    return result


@tool(category="scripting", mutating=True)
def execute_python(
    code: Annotated[str, "Python code to execute in IDA's scripting environment"],
) -> str:
    """Execute arbitrary Python code in IDA's context and return stdout/stderr.

    The code runs with full access to IDA's Python API (idaapi, idautils, idc, etc.).
    Use print() to produce output that will be returned.
    """
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    namespace = _get_base_namespace()

    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        try:
            exec(code, namespace)  # noqa: S102 — intentional scripting tool
        except Exception as e:
            stderr_buf.write(f"{type(e).__name__}: {e}\n")

    stdout = stdout_buf.getvalue()
    stderr = stderr_buf.getvalue()

    parts = []
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    if not parts:
        parts.append("(no output)")
    return "\n".join(parts)
