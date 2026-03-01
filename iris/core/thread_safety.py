"""Thread-safety utilities for IDA API access."""

from __future__ import annotations

import builtins
import contextlib
import functools
import importlib
import threading
import traceback
from typing import Any, Callable, Generator, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

from ..constants import IDA_AVAILABLE as _IDA_AVAILABLE
if _IDA_AVAILABLE:
    import ida_kernwin


def _log(msg: str) -> None:
    """Low-level log that avoids circular imports with logging.py."""
    try:
        from .logging import log_trace
        log_trace(msg)
    except ImportError:
        pass  # logging.py not yet loaded during early bootstrap


def idasync(func: F) -> F:
    """Decorator: execute *func* on IDA's main thread via execute_sync.

    When called from the main thread, runs directly.
    When called from a background thread, marshals through MFF_WRITE.
    Returns the result synchronously in both cases.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        fname = func.__name__
        if not _IDA_AVAILABLE:
            return func(*args, **kwargs)

        if threading.current_thread() is threading.main_thread():
            _log(f"idasync: {fname} on main thread — direct call")
            return func(*args, **kwargs)

        _log(f"idasync: {fname} on {threading.current_thread().name} — execute_sync START")
        result_holder: list = []
        error_holder: list = []

        def _thunk():
            try:
                _log(f"idasync: {fname} _thunk executing on main thread")
                result_holder.append(func(*args, **kwargs))
                _log(f"idasync: {fname} _thunk OK")
            except Exception as exc:
                _log(f"idasync: {fname} _thunk ERROR: {exc}")
                error_holder.append(exc)
            return 0

        rc = ida_kernwin.execute_sync(_thunk, ida_kernwin.MFF_WRITE)
        _log(f"idasync: {fname} execute_sync returned rc={rc}")

        if error_holder:
            raise error_holder[0]
        return result_holder[0] if result_holder else None

    return wrapper  # type: ignore[return-value]


_shiboken_lock = threading.Lock()


@contextlib.contextmanager
def shiboken_bypass() -> Generator[None, None, None]:
    """Context manager: temporarily restore CPython's real __import__.

    PySide6/Shiboken patches ``builtins.__import__`` with a hook that can
    interfere with bulk module imports — IDA modules already in sys.modules
    may spuriously fail to resolve when many imports hit the hook in quick
    succession.

    Thread-safe: a lock prevents concurrent ``__import__`` swaps.

    Usage::

        with shiboken_bypass():
            provider.ensure_ready()   # safely imports SDK packages
    """
    with _shiboken_lock:
        saved = builtins.__import__
        builtins.__import__ = importlib.__import__
        try:
            yield
        finally:
            builtins.__import__ = saved


def run_in_background(func: Callable[..., Any], *args: Any, **kwargs: Any) -> threading.Thread:
    """Run *func* in a daemon background thread."""
    thread = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
    thread.start()
    return thread
