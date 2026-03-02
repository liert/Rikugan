"""IDA UI hooks and context menu integration.

Data-driven table of 9 context-menu actions under IRIS/.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ...core.logging import log_debug

try:
    ida_funcs = importlib.import_module("ida_funcs")
    ida_kernwin = importlib.import_module("ida_kernwin")
    ida_name = importlib.import_module("ida_name")
    idaapi = importlib.import_module("idaapi")
    idc = importlib.import_module("idc")
    _HAS_IDA = True
except ImportError:
    _HAS_IDA = False


def _get_context() -> Dict[str, Any]:
    """Extract context from the current IDA view.

    Returns dict with keys: ea, func_ea, func_name, selected_text.
    """
    ea = idc.get_screen_ea()
    ctx: Dict[str, Any] = {
        "ea": ea,
        "func_ea": None,
        "func_name": None,
        "selected_text": "",
    }

    func = ida_funcs.get_func(ea)
    if func:
        ctx["func_ea"] = func.start_ea
        ctx["func_name"] = ida_name.get_name(func.start_ea)

    # Try to grab viewer selection
    viewer = ida_kernwin.get_current_viewer()
    if viewer:
        sel_ok, start, end = ida_kernwin.read_range_selection(viewer)
        if sel_ok:
            ctx["selected_text"] = f"0x{start:x}-0x{end:x}"

    return ctx


if _HAS_IDA:

    # ------------------------------------------------------------------
    # Action handler factory
    # ------------------------------------------------------------------

    class _IRISAction(idaapi.action_handler_t):
        """Generic context-menu action backed by a handler callback."""

        def __init__(self, panel_getter: Callable[[], Any], handler: Callable[[Dict[str, Any]], str], auto_submit: bool = False):
            super().__init__()
            self._get_panel = panel_getter
            self._handler = handler
            self._auto_submit = auto_submit

        def activate(self, ctx) -> int:
            panel = self._get_panel()
            if panel is None:
                return 0
            context = _get_context()
            text = self._handler(context)
            if text:
                panel._input_area.setPlainText(text)
                if self._auto_submit:
                    panel._on_submit(text)
                else:
                    panel._input_area.setFocus()
            return 1

        def update(self, ctx) -> int:
            return idaapi.AST_ENABLE_ALWAYS

    # ------------------------------------------------------------------
    # Handler functions — each returns the text to place in the input
    # ------------------------------------------------------------------

    def _handle_send_to(ctx: Dict[str, Any]) -> str:
        sel = ctx["selected_text"]
        if sel:
            return sel
        name = ctx["func_name"]
        ea = ctx["ea"]
        if name:
            return f"Analyze the function {name} at 0x{ea:x}"
        return f"Analyze the code at 0x{ea:x}"

    def _handle_explain(ctx: Dict[str, Any]) -> str:
        name = ctx["func_name"] or f"sub_{ctx['ea']:x}"
        ea = ctx["func_ea"] or ctx["ea"]
        return (
            f"Explain the function {name} at 0x{ea:x}. "
            "Decompile it and provide a detailed analysis."
        )

    def _handle_rename(ctx: Dict[str, Any]) -> str:
        name = ctx["func_name"] or f"sub_{ctx['ea']:x}"
        ea = ctx["func_ea"] or ctx["ea"]
        return (
            f"Analyze the function {name} at 0x{ea:x}. "
            "Based on its behavior, suggest better names for the function "
            "and its local variables. Apply the renames."
        )

    def _handle_deobfuscate(ctx: Dict[str, Any]) -> str:
        name = ctx["func_name"] or f"sub_{ctx['ea']:x}"
        ea = ctx["func_ea"] or ctx["ea"]
        return (
            f"Deobfuscate the function {name} at 0x{ea:x}. "
            "Identify obfuscation patterns (opaque predicates, junk code, "
            "control-flow flattening, encrypted strings) and explain them. "
            "If possible, apply microcode optimizations to clean the output."
        )

    def _handle_vuln_audit(ctx: Dict[str, Any]) -> str:
        name = ctx["func_name"] or f"sub_{ctx['ea']:x}"
        ea = ctx["func_ea"] or ctx["ea"]
        return (
            f"Audit the function {name} at 0x{ea:x} for security vulnerabilities. "
            "Check for buffer overflows, format strings, integer overflows, "
            "use-after-free, command injection, and other memory-safety issues. "
            "List each finding with severity and evidence."
        )

    def _handle_suggest_types(ctx: Dict[str, Any]) -> str:
        name = ctx["func_name"] or f"sub_{ctx['ea']:x}"
        ea = ctx["func_ea"] or ctx["ea"]
        return (
            f"Analyze the function {name} at 0x{ea:x} and infer types. "
            "Examine pointer dereference patterns to suggest structs, "
            "identify enum-like constants, and propose proper parameter types. "
            "Apply the type changes."
        )

    def _handle_annotate(ctx: Dict[str, Any]) -> str:
        name = ctx["func_name"] or f"sub_{ctx['ea']:x}"
        ea = ctx["func_ea"] or ctx["ea"]
        return (
            f"Annotate the function {name} at 0x{ea:x} with comments. "
            "Add a function-level comment summarizing its purpose, and "
            "add inline comments to key basic blocks explaining the logic."
        )

    def _handle_clean_mcode(ctx: Dict[str, Any]) -> str:
        name = ctx["func_name"] or f"sub_{ctx['ea']:x}"
        ea = ctx["func_ea"] or ctx["ea"]
        return (
            f"Clean the microcode for {name} at 0x{ea:x}. "
            "Read the microcode, identify junk or obfuscated instructions, "
            "NOP them or install a microcode optimizer to clean them, "
            "then redecompile to verify the result."
        )

    def _handle_xref_analysis(ctx: Dict[str, Any]) -> str:
        name = ctx["func_name"] or f"sub_{ctx['ea']:x}"
        ea = ctx["func_ea"] or ctx["ea"]
        return (
            f"Perform a deep cross-reference analysis on {name} at 0x{ea:x}. "
            "Trace all callers and callees, identify data references, "
            "and map out the call graph around this function."
        )

    # ------------------------------------------------------------------
    # Action definitions table
    # ------------------------------------------------------------------
    # (action_id, label, handler_fn, auto_submit, hotkey, tooltip, allowed_views)

    _ACTION_DEFS: List[Tuple[str, str, Callable, bool, str, str, Set[str]]] = [
        (
            "iris:send_to",
            "Send to IRIS",
            _handle_send_to, False,
            "Ctrl+Shift+A",
            "Send selection or address to IRIS input",
            {"disasm", "pseudo"},
        ),
        (
            "iris:explain",
            "Explain this",
            _handle_explain, True,
            "",
            "Explain the current function with IRIS",
            {"disasm", "pseudo"},
        ),
        (
            "iris:rename",
            "Rename with IRIS",
            _handle_rename, True,
            "",
            "Analyze and rename the current function",
            {"disasm", "pseudo"},
        ),
        (
            "iris:deobfuscate",
            "Deobfuscate with IRIS",
            _handle_deobfuscate, True,
            "",
            "Deobfuscate the current function",
            {"disasm", "pseudo"},
        ),
        (
            "iris:vuln_audit",
            "Find vulnerabilities",
            _handle_vuln_audit, True,
            "",
            "Audit the current function for security bugs",
            {"disasm", "pseudo"},
        ),
        (
            "iris:suggest_types",
            "Suggest types",
            _handle_suggest_types, True,
            "",
            "Infer and apply types for the current function",
            {"disasm", "pseudo"},
        ),
        (
            "iris:annotate",
            "Annotate function",
            _handle_annotate, True,
            "",
            "Add comments to the current function",
            {"pseudo"},
        ),
        (
            "iris:clean_mcode",
            "Clean microcode",
            _handle_clean_mcode, True,
            "",
            "Clean the microcode for the current function",
            {"pseudo"},
        ),
        (
            "iris:xref_analysis",
            "Xref analysis",
            _handle_xref_analysis, True,
            "",
            "Deep cross-reference analysis on the current function",
            {"disasm", "pseudo"},
        ),
    ]

    _WIDGET_TYPE_MAP = {
        idaapi.BWN_DISASM: "disasm",
        idaapi.BWN_PSEUDOCODE: "pseudo",
    }

    # ------------------------------------------------------------------
    # UI hooks
    # ------------------------------------------------------------------

    class IRISUIHooks(idaapi.UI_Hooks):
        """UI hooks for adding IRIS to context menus."""

        def __init__(self, panel_getter: Callable[[], Any]):
            super().__init__()
            self._get_panel = panel_getter
            self._registered = False

        def ready_to_run(self) -> None:
            self._register_actions()

        def _register_actions(self) -> None:
            if self._registered:
                return

            for action_id, label, handler_fn, auto_submit, hotkey, tooltip, _views in _ACTION_DEFS:
                desc = idaapi.action_desc_t(
                    action_id,
                    label,
                    _IRISAction(self._get_panel, handler_fn, auto_submit),
                    hotkey,
                    tooltip,
                )
                idaapi.register_action(desc)

            self._registered = True

        def finish_populating_widget_popup(self, widget, popup) -> None:
            widget_type = idaapi.get_widget_type(widget)
            view_key = _WIDGET_TYPE_MAP.get(widget_type)
            if view_key is None:
                return

            for action_id, _label, _handler, _auto, _hk, _tt, views in _ACTION_DEFS:
                if view_key in views:
                    idaapi.attach_action_to_popup(widget, popup, action_id, "IRIS/")

        def database_inited(self, is_new_database: bool, idc_script: str) -> None:
            """Called when a database is opened or created."""
            panel = self._get_panel()
            if panel is None:
                return
            try:
                new_path = idaapi.get_path(idaapi.PATH_TYPE_IDB)
                if not new_path:
                    new_path = idaapi.get_input_file_path() or ""
                if new_path and hasattr(panel, "on_database_changed"):
                    panel.on_database_changed(new_path)
                    log_debug(f"Database changed notification: {new_path}")
            except Exception as e:
                log_debug(f"database_inited hook error: {e}")

        def term(self) -> None:
            if self._registered:
                for action_id, *_ in _ACTION_DEFS:
                    idaapi.unregister_action(action_id)
                self._registered = False

else:

    class IRISUIHooks:
        """Stub when IDA is not available."""
        def __init__(self, *args, **kwargs):
            self._panel_getter = kwargs.get("panel_getter")
        def hook(self):
            return False
        def unhook(self):
            return False
