"""IDA PluginForm wrapper around the shared IRIS panel core."""

from __future__ import annotations

import importlib
from typing import Optional

from iris.ui.qt_compat import QVBoxLayout, QWidget
from iris.ui.panel_core import IRISPanelCore
from iris.ida.ui.session_controller import SessionController
from iris.ida.ui.actions import IRISUIHooks

idaapi = importlib.import_module("idaapi")


class IRISPanel(idaapi.PluginForm):
    """IDA dockable form embedding the shared panel core widget."""

    def __init__(self):
        super().__init__()
        self._form_widget: Optional[QWidget] = None
        self._root: Optional[QWidget] = None
        self._core: Optional[IRISPanelCore] = None

    def OnCreate(self, form):  # noqa: N802
        try:
            self._form_widget = self.FormToPyQtWidget(form)
        except Exception:
            self._form_widget = self.FormToPySideWidget(form)

        self._root = QWidget()
        form_layout = QVBoxLayout(self._form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.addWidget(self._root)

        root_layout = QVBoxLayout(self._root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self._core = IRISPanelCore(
            controller_factory=SessionController,
            ui_hooks_factory=lambda panel_getter: IRISUIHooks(panel_getter=panel_getter),
            parent=self._root,
        )
        root_layout.addWidget(self._core)

    def OnClose(self, form):  # noqa: N802
        self.shutdown()
        if self._root is not None:
            self._root.setParent(None)
            self._root = None

    def show(self):
        return self.Show(
            "IRIS",
            options=(
                idaapi.PluginForm.WOPN_TAB
                | idaapi.PluginForm.WOPN_PERSIST
            ),
        )

    def close(self):
        self.Close(0)

    def shutdown(self) -> None:
        if self._core is not None:
            self._core.shutdown()
            self._core.setParent(None)
            self._core = None

    def prefill_input(self, text: str, auto_submit: bool = False) -> None:
        if self._core is not None:
            self._core.prefill_input(text, auto_submit=auto_submit)

    def __getattr__(self, name: str):
        # Forward UI action accessors like _input_area / _on_submit.
        core = object.__getattribute__(self, "_core")
        if core is not None and hasattr(core, name):
            return getattr(core, name)
        raise AttributeError(name)
