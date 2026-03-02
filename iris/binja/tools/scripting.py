"""Python scripting execution tool for Binary Ninja."""

from __future__ import annotations

import contextlib
import importlib
import io
from typing import Annotated

from ...tools.base import tool
from .common import current_ea_or_default, require_bv

_BN_MODULE_NAMES = (
    "binaryninja",
    "binaryninjaui",
)
_cached_namespace: dict | None = None


def _get_base_namespace() -> dict:
    """Return a cached namespace with common Binary Ninja modules pre-imported."""
    global _cached_namespace
    if _cached_namespace is None:
        ns: dict = {}
        for mod_name in _BN_MODULE_NAMES:
            try:
                ns[mod_name] = importlib.import_module(mod_name)
            except ImportError:
                pass
        _cached_namespace = ns

    bv = require_bv()
    result: dict = {"__builtins__": __builtins__}
    result.update(_cached_namespace)
    result["bv"] = bv
    result["current_address"] = current_ea_or_default(0)
    return result


@tool(category="scripting", mutating=True)
def execute_python(
    code: Annotated[str, "Python code to execute in Binary Ninja's scripting environment"],
) -> str:
    """Execute arbitrary Python code in Binary Ninja context and return stdout/stderr.

    The code runs with access to `binaryninja`, `binaryninjaui`, `bv`, and
    `current_address`.
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
