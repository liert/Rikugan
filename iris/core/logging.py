"""Logging to IDA's output window AND a crash-proof log file.

The file log at ~/.idapro/iris/iris_debug.log is flushed after every
write so the last line survives even if IDA crashes hard (SIGSEGV).
"""

from __future__ import annotations

import logging
import os
import sys
import time
import threading
import traceback
from typing import Optional

from ..constants import IDA_AVAILABLE as _IDA_AVAILABLE
if _IDA_AVAILABLE:
    import ida_kernwin

_logger: Optional[logging.Logger] = None

# --- Crash-proof file path ---

def _log_file_path() -> str:
    try:
        import idaapi
        base = idaapi.get_user_idadir()
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".idapro")
    d = os.path.join(base, "iris")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "iris_debug.log")


class _FlushFileHandler(logging.FileHandler):
    """FileHandler that flushes + fsync after every record."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        try:
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError:
            pass  # fsync can fail on pipes/redirected streams — non-fatal for logging


class IDAHandler(logging.Handler):
    """Logging handler that writes to IDA's output window."""

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if _IDA_AVAILABLE:
            try:
                ida_kernwin.msg(f"{msg}\n")
            except RuntimeError:
                pass  # IDA output window may be destroyed during shutdown
        else:
            sys.stderr.write(f"{msg}\n")


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    _logger = logging.getLogger("IRIS")
    _logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[IRIS %(asctime)s.%(msecs)03d %(levelname)s %(threadName)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # IDA output handler (INFO and above to avoid spamming)
    ida_handler = IDAHandler()
    ida_handler.setLevel(logging.INFO)
    ida_handler.setFormatter(logging.Formatter("[IRIS] %(levelname)s: %(message)s"))
    _logger.addHandler(ida_handler)

    # File handler (DEBUG — everything, flush immediately)
    try:
        path = _log_file_path()
        file_handler = _FlushFileHandler(path, mode="w", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        _logger.addHandler(file_handler)
        _logger.debug(f"=== IRIS debug log started — {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        _logger.debug(f"Log file: {path}")
        _logger.debug(f"Python: {sys.version}")
        _logger.debug(f"Thread: {threading.current_thread().name}")
    except Exception as e:
        _logger.warning(f"Could not open debug log file: {e}")

    return _logger


def log_info(msg: str) -> None:
    get_logger().info(msg)


def log_warning(msg: str) -> None:
    get_logger().warning(msg)


def log_error(msg: str) -> None:
    get_logger().error(msg)


def log_debug(msg: str) -> None:
    get_logger().debug(msg)


def log_trace(label: str) -> None:
    """Verbose trace-level log (logged at DEBUG level with TRACE prefix)."""
    get_logger().debug(f"TRACE {label}")
