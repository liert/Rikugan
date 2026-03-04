"""Binary Ninja plugin entry point for Rikugan."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

try:
    import binaryninja as bn  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - loaded only in Binary Ninja runtime
    bn = None

if bn is not None:
    # Binary Ninja loads this file as part of the plugin package.
    # Use relative imports to reach the framework package at ./rikugan/.
    from .rikugan.core.host import get_database_path, set_binary_ninja_context
    from .rikugan.core.logging import log_debug
    from .rikugan.binja.ui.actions import ACTION_DEFS, build_context
    from .rikugan.binja.ui.panel import RikuganPanel
    from .rikugan.binja.tools.common import get_function_at, get_function_name

    try:
        import binaryninjaui as bnui  # type: ignore[import-not-found]
    except Exception:
        bnui = None
else:  # pragma: no cover - imported outside Binary Ninja
    set_binary_ninja_context = None  # type: ignore[assignment]
    get_database_path = lambda: ""  # noqa: E731 — no-op stub outside BN
    log_debug = lambda *a, **k: None  # noqa: E731 — no-op stub outside BN
    RikuganPanel = Any  # type: ignore[misc,assignment]
    ACTION_DEFS = ()
    bnui = None

    get_function_at = lambda *_a, **_k: None  # noqa: E731 — no-op stub outside BN
    get_function_name = lambda _f: ""  # noqa: E731 — no-op stub outside BN
    build_context = lambda *_a, **_k: {}  # noqa: E731 — no-op stub outside BN

RIKUGAN_SIDEBAR_NAME = "Rikugan"

_PANEL: Optional[RikuganPanel] = None
_LAST_BV: Any = None
_REGISTERED = False
_SIDEBAR_REGISTERED = False


def _navigate_cb(ea: int) -> bool:
    """Best-effort Binary Ninja UI navigation callback."""
    global _LAST_BV
    bv = _LAST_BV
    if bv is None:
        return False

    # Try BinaryView.navigate(view, addr)
    nav = getattr(bv, "navigate", None)
    if callable(nav):
        for view in ("Graph:IL", "Graph:Disassembly", "Linear:Disassembly", "Linear"):
            try:
                if bool(nav(view, int(ea))):
                    return True
            except Exception as e:
                log_debug(f"_navigate_cb nav({view!r}) failed at 0x{ea:x}: {e}")
                continue
        try:
            if bool(nav(int(ea))):
                return True
        except Exception as e:
            log_debug(f"_navigate_cb nav(ea) failed at 0x{ea:x}: {e}")

    # Try UIContext navigation APIs if available
    if bnui is not None:
        try:
            ui_ctx_cls = getattr(bnui, "UIContext", None)
            if ui_ctx_cls is not None:
                active = ui_ctx_cls.activeContext()
                if active is not None:
                    vf = active.getCurrentViewFrame()
                    if vf is not None:
                        for meth_name in ("navigate", "setCurrentOffset"):
                            meth = getattr(vf, meth_name, None)
                            if callable(meth):
                                try:
                                    rc = meth(int(ea))
                                    if rc is None or bool(rc):
                                        return True
                                except Exception as e:
                                    log_debug(f"_navigate_cb UIContext.{meth_name} failed at 0x{ea:x}: {e}")
        except Exception as e:
            log_debug(f"_navigate_cb UIContext navigation failed at 0x{ea:x}: {e}")

    return False


def _update_context(bv: Any, address: Optional[int] = None) -> None:
    global _LAST_BV
    changed_view = (bv is not _LAST_BV) and (_LAST_BV is not None)
    _LAST_BV = bv
    if set_binary_ninja_context is not None:
        set_binary_ninja_context(bv=bv, address=address, navigate_cb=_navigate_cb)
    if changed_view:
        # BinaryView changed — notify panel with normalized path from host context.
        panel = _get_sidebar_panel(create_if_missing=False)
        if panel is not None and hasattr(panel, "on_database_changed"):
            try:
                panel.on_database_changed(get_database_path())
            except Exception as e:
                log_debug(f"_update_context on_database_changed failed: {e}")


def _active_sidebar() -> Any:
    if bnui is None:
        return None
    try:
        ui_ctx_cls = getattr(bnui, "UIContext", None)
        if ui_ctx_cls is None:
            return None
        ui_ctx = ui_ctx_cls.activeContext()
        if ui_ctx is None:
            return None
        sidebar_get = getattr(ui_ctx, "sidebar", None)
        if not callable(sidebar_get):
            return None
        return sidebar_get()
    except Exception:
        return None


def _get_sidebar_panel(create_if_missing: bool = True) -> Optional[RikuganPanel]:
    sidebar = _active_sidebar()
    if sidebar is None:
        return None
    try:
        widget = sidebar.widget(RIKUGAN_SIDEBAR_NAME)
        if widget is None and create_if_missing:
            sidebar.activate(RIKUGAN_SIDEBAR_NAME)
            widget = sidebar.widget(RIKUGAN_SIDEBAR_NAME)
        if widget is not None and hasattr(widget, "panel"):
            panel = getattr(widget, "panel")
            if isinstance(panel, RikuganPanel):
                return panel
    except Exception:
        return None
    return None


def _ensure_panel(bv: Any, address: Optional[int] = None) -> RikuganPanel:
    global _PANEL
    _update_context(bv, address)

    # Preferred mode: sidebar panel (like Sidekick)
    sidebar_panel = _get_sidebar_panel(create_if_missing=True)
    if sidebar_panel is not None:
        return sidebar_panel

    # Fallback: floating widget
    if _PANEL is None:
        _PANEL = RikuganPanel()

    _PANEL.show()
    try:
        _PANEL.raise_()
        _PANEL.activateWindow()
    except Exception as e:
        log_debug(f"_ensure_panel raise_/activateWindow failed: {e}")
    return _PANEL


def _action_callback(handler: Callable[[Dict[str, Any]], str], auto_submit: bool):
    def _cb(bv, addr):
        _update_context(bv, int(addr))
        panel = _ensure_panel(bv, int(addr))
        ctx = build_context(bv, int(addr), get_function_at, get_function_name)
        text = handler(ctx)
        if text:
            panel.prefill_input(text, auto_submit=auto_submit)
    return _cb


def _open_panel_command(bv):
    _ensure_panel(bv, None)


def _register_sidebar() -> None:
    global _SIDEBAR_REGISTERED
    if _SIDEBAR_REGISTERED or bnui is None:
        return

    Sidebar = getattr(bnui, "Sidebar", None)
    SidebarWidget = getattr(bnui, "SidebarWidget", None)
    SidebarWidgetType = getattr(bnui, "SidebarWidgetType", None)
    SidebarWidgetLocation = getattr(bnui, "SidebarWidgetLocation", None)
    SidebarContextSensitivity = getattr(bnui, "SidebarContextSensitivity", None)
    if Sidebar is None or SidebarWidget is None or SidebarWidgetType is None:
        return

    from PySide6.QtGui import QImage

    class RikuganSidebarWidget(SidebarWidget):
        def __init__(self, view_frame, binary_view):
            super().__init__(RIKUGAN_SIDEBAR_NAME)
            self.view_frame = view_frame
            self.binary_view = binary_view
            # Ensure host DB context exists before panel/controller construction.
            _update_context(binary_view, None)
            self.panel = RikuganPanel()
            self.panel.mount(self)

        def notifyViewLocationChanged(self, view, location):  # type: ignore[override]
            try:
                ea = int(location.getOffset())
            except Exception:
                ea = None
            _update_context(self.binary_view, ea)

        def closing(self):  # noqa: D401
            """Sidebar lifecycle callback."""
            try:
                self.panel.shutdown()
            except Exception as e:
                log_debug(f"RikuganSidebarWidget.closing panel.shutdown failed: {e}")

    class RikuganSidebarWidgetType(SidebarWidgetType):
        def __init__(self):
            icon_dir = os.path.join(os.path.dirname(__file__), "assets")
            icon = QImage(os.path.join(icon_dir, "rikugan_icon_light.png"))
            if icon.isNull():
                icon = QImage(":/icons/sidekick-assistant.png")
            if icon.isNull():
                icon = QImage(os.path.join(icon_dir, "chat.png"))
            SidebarWidgetType.__init__(self, icon, RIKUGAN_SIDEBAR_NAME)

        def createWidget(self, frame, data):
            if data is None:
                return None
            return RikuganSidebarWidget(frame, data)

        def defaultLocation(self):
            if SidebarWidgetLocation is not None:
                return SidebarWidgetLocation.LeftContent
            return super().defaultLocation()

        def contextSensitivity(self):
            if SidebarContextSensitivity is not None:
                return SidebarContextSensitivity.PerViewTypeSidebarContext
            return super().contextSensitivity()

        def isInReferenceArea(self):
            return False

    try:
        Sidebar.addSidebarWidgetType(RikuganSidebarWidgetType())
        _SIDEBAR_REGISTERED = True
    except Exception:
        _SIDEBAR_REGISTERED = False


def _register_commands() -> None:
    global _REGISTERED
    if _REGISTERED or bn is None:
        return

    _register_sidebar()

    plugin_cmd = getattr(bn, "PluginCommand", None)
    if plugin_cmd is None:
        return

    plugin_cmd.register(
        "Rikugan\\Open Panel",
        "Open Rikugan chat panel",
        _open_panel_command,
    )

    register_for_address = getattr(plugin_cmd, "register_for_address", None)
    if callable(register_for_address):
        for label, desc, handler, auto_submit in ACTION_DEFS:
            register_for_address(
                f"Rikugan\\{label}",
                desc,
                _action_callback(handler, auto_submit),
            )

    _REGISTERED = True


if bn is not None:
    _register_commands()
