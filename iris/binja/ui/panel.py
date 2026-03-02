"""Binary Ninja QWidget wrapper around the shared IRIS panel core."""

from __future__ import annotations

from ...ui.qt_compat import QVBoxLayout, QWidget
from ...ui.panel_core import IRISPanelCore
from .session_controller import BinaryNinjaSessionController


class IRISPanel(QWidget):
    """Binary Ninja panel widget."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._core = IRISPanelCore(
            controller_factory=BinaryNinjaSessionController,
            ui_hooks_factory=None,
            parent=self,
        )
        layout.addWidget(self._core)

    def mount(self, parent: QWidget) -> None:
        if self.parent() is not parent:
            self.setParent(parent)
        layout = parent.layout()
        if layout is None:
            layout = QVBoxLayout(parent)
            layout.setContentsMargins(0, 0, 0, 0)
        if layout.indexOf(self) < 0:
            layout.addWidget(self)

    def prefill_input(self, text: str, auto_submit: bool = False) -> None:
        self._core.prefill_input(text, auto_submit=auto_submit)

    def shutdown(self) -> None:
        self._core.shutdown()

    def __getattr__(self, name: str):
        if hasattr(self._core, name):
            return getattr(self._core, name)
        raise AttributeError(name)
