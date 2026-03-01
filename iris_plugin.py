"""IRIS - Intelligent Reverse-engineering Integrated System.

IDA Pro plugin entry point.
All iris.* imports are deferred to avoid crashes during plugin enumeration.
"""

import builtins
import importlib

import idaapi

_real_import = importlib.__import__


class IRISPlugmod(idaapi.plugmod_t):
    """Per-database plugin module."""

    def __init__(self):
        super().__init__()
        self._panel = None

    def run(self, arg: int) -> bool:
        self._toggle_panel()
        return True

    def term(self) -> None:
        _log("IRISPlugmod.term() called")
        panel = self._panel
        self._panel = None
        if panel is not None:
            try:
                panel.close()
            except Exception as e:
                idaapi.msg(f"[IRIS] Panel close error: {e}\n")

    def _toggle_panel(self) -> None:
        try:
            _log("_toggle_panel: entry")
            if self._panel is not None:
                _log("_toggle_panel: panel exists, calling show()")
                self._panel.show()
                return

            # Bulk-load all iris.* modules with Shiboken's __import__ hook
            # temporarily replaced by CPython's real import.
            #
            # Why: Shiboken's hook intercepts every `import` / `from X import Y`
            # in the process.  When dozens of iris modules load simultaneously
            # (each triggering transitive ida_*/PySide6 lookups through the hook),
            # Shiboken's internal state can corrupt — IDA modules that are
            # already in sys.modules fail to resolve, causing spurious
            # "No module named 'ida_...'" errors on the first open attempt.
            #
            # The bypass swaps builtins.__import__ to importlib.__import__
            # (CPython's C-level import) for the duration of the bulk load.
            # This is safe because:
            #   - PySide6/IDA modules are already loaded; lookups are cache hits
            #   - iris.* modules use importlib.import_module() (bypasses the hook
            #     natively) and their transitive `from` imports resolve from
            #     sys.modules with zero nesting through either hook
            #   - The swap is short-lived and runs only on the main thread
            _log("_toggle_panel: importing iris modules (Shiboken bypass)")
            saved = builtins.__import__
            builtins.__import__ = _real_import
            try:
                import pkgutil
                import iris
                for _finder, modname, _ispkg in pkgutil.walk_packages(
                    iris.__path__, prefix="iris."
                ):
                    try:
                        importlib.import_module(modname)
                    except Exception:
                        pass  # Non-critical: skip modules that fail to load
                _log("_toggle_panel: all iris modules loaded")
                from iris.ui.panel import IRISPanel
            finally:
                builtins.__import__ = saved

            _log("_toggle_panel: creating IRISPanel()")
            self._panel = IRISPanel()
            _log("_toggle_panel: calling show()")
            self._panel.show()
            _log("_toggle_panel: done")
        except Exception as e:
            import sys
            import traceback
            tb_str = traceback.format_exc()
            idaapi.msg(f"[IRIS] Failed to open panel: {e}\n{tb_str}\n")
            try:
                from iris.core.logging import log_error
                log_error(f"Failed to open panel: {e}\n{tb_str}")
            except Exception:
                try:
                    import os
                    log_path = os.path.join(os.path.expanduser("~"), ".idapro", "iris", "iris_debug.log")
                    with open(log_path, "a") as f:
                        f.write(f"[IRIS CRASH] {e}\n{tb_str}\n")
                        f.flush()
                        os.fsync(f.fileno())
                except Exception:
                    print(f"[IRIS CRASH] {e}\n{tb_str}", file=sys.stderr)


class IRISPlugin(idaapi.plugin_t):
    flags = idaapi.PLUGIN_MULTI | idaapi.PLUGIN_FIX
    comment = "Intelligent Reverse-engineering Integrated System"
    help = ""
    wanted_name = "IRIS"
    wanted_hotkey = "Ctrl+Shift+I"

    def init(self) -> idaapi.plugmod_t:
        idaapi.msg("[IRIS] Plugin loaded (v0.1.0)\n")
        return IRISPlugmod()


def _log(msg: str) -> None:
    """Best-effort log to IDA output and debug file."""
    idaapi.msg(f"[IRIS] {msg}\n")
    try:
        from iris.core.logging import log_trace
        log_trace(msg)
    except Exception:
        pass  # noqa: S110 — logging not yet available during bootstrap


def PLUGIN_ENTRY():  # noqa: N802
    return IRISPlugin()
