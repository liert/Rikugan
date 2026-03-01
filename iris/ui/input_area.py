"""Multi-line input area with Enter/Shift+Enter handling and /skill autocomplete."""

from __future__ import annotations

from typing import List, Optional

from .qt_compat import (
    QPlainTextEdit, QWidget, QVBoxLayout, QLabel, QFrame, Qt, Signal, QSizePolicy,
)


class _SkillPopup(QFrame):
    """Lightweight autocomplete popup for /skill slugs.

    Uses QLabel items inside a QFrame — avoids QListWidget Shiboken surface.
    NO Signal definitions here — this class is defined during the Shiboken
    bypass window and adding Signal descriptors corrupts Shiboken's internal
    signal registry on Python 3.14 + Shiboken 6.8.2, causing SIGSEGV in
    checkQtSignal() on any later signal operation (e.g. QTimer.singleShot).
    """

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("skill_popup")
        self.setWindowFlags(Qt.WindowType.ToolTip)
        self.setStyleSheet(
            "QFrame#skill_popup { background: #2d2d2d; border: 1px solid #555; "
            "border-radius: 4px; padding: 2px; }"
            "QLabel { color: #d4d4d4; padding: 3px 8px; }"
            "QLabel[selected=\"true\"] { background: #094771; border-radius: 3px; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(0)
        self._labels: List[QLabel] = []
        self._slugs: List[str] = []
        self._selected_idx = 0

    def set_items(self, slugs: List[str]) -> None:
        """Replace popup contents with filtered slugs."""
        # Clear old labels
        for lbl in self._labels:
            self._layout.removeWidget(lbl)
            lbl.setParent(None)
        self._labels.clear()
        self._slugs = list(slugs)
        self._selected_idx = 0

        for slug in slugs:
            lbl = QLabel(f"/{slug}")
            self._labels.append(lbl)
            self._layout.addWidget(lbl)

        self._update_highlight()
        self.adjustSize()

    def _update_highlight(self) -> None:
        for i, lbl in enumerate(self._labels):
            lbl.setProperty("selected", "true" if i == self._selected_idx else "false")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def move_selection(self, delta: int) -> None:
        if not self._slugs:
            return
        self._selected_idx = (self._selected_idx + delta) % len(self._slugs)
        self._update_highlight()

    def current_slug(self) -> Optional[str]:
        if 0 <= self._selected_idx < len(self._slugs):
            return self._slugs[self._selected_idx]
        return None

    def is_empty(self) -> bool:
        return len(self._slugs) == 0


class InputArea(QPlainTextEdit):
    """Chat input area with keyboard shortcuts.

    - Enter: submit message
    - Shift+Enter: newline
    - Escape: cancel running agent
    - /: skill autocomplete popup
    """

    submit_requested = Signal(str)
    cancel_requested = Signal()

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("input_area")
        self.setPlaceholderText("Ask IRIS about this binary... (Enter to send, Shift+Enter for newline)")
        self.setMaximumHeight(100)
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._enabled = True
        self._skill_slugs: List[str] = []
        self._popup: Optional[_SkillPopup] = None
        # NOTE: Do NOT connect textChanged here.  Connecting a C++ signal
        # to a Python slot adds Shiboken signal surface.  Instead we check
        # the autocomplete trigger directly inside keyPressEvent after the
        # key has been processed by the base class.

    def set_skill_slugs(self, slugs: List[str]) -> None:
        """Set the list of available skill slugs for autocomplete."""
        self._skill_slugs = sorted(slugs)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Handle popup navigation when popup is visible
        if self._popup and self._popup.isVisible():
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                slug = self._popup.current_slug()
                if slug:
                    self._accept_completion(slug)
                return
            elif event.key() == Qt.Key.Key_Escape:
                self._dismiss_popup()
                return
            elif event.key() == Qt.Key.Key_Down:
                self._popup.move_selection(1)
                return
            elif event.key() == Qt.Key.Key_Up:
                self._popup.move_selection(-1)
                return

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                text = self.toPlainText().strip()
                if text and self._enabled:
                    self.submit_requested.emit(text)
                    self.clear()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
        else:
            # Let the base class process the key first (inserts character),
            # then check if we need to show/update/dismiss the autocomplete.
            super().keyPressEvent(event)
            self._check_autocomplete()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.setReadOnly(not enabled)
        if enabled:
            self.setPlaceholderText("Ask IRIS about this binary... (Enter to send, Shift+Enter for newline)")
        else:
            self.setPlaceholderText("IRIS is thinking...")

    # ------------------------------------------------------------------
    # Autocomplete
    # ------------------------------------------------------------------

    def _check_autocomplete(self) -> None:
        """Check current text and show/hide the skill autocomplete popup."""
        text = self.toPlainText()
        if not text.startswith("/") or not self._skill_slugs:
            self._dismiss_popup()
            return

        # Extract partial slug (everything after / up to first space)
        parts = text[1:].split(None, 1)
        # If there's already a space, the slug is complete — dismiss
        if len(parts) > 1:
            self._dismiss_popup()
            return

        partial = parts[0] if parts else ""
        matches = [s for s in self._skill_slugs if s.startswith(partial)]

        if not matches:
            self._dismiss_popup()
            return

        self._show_popup(matches)

    def _show_popup(self, slugs: List[str]) -> None:
        if self._popup is None:
            self._popup = _SkillPopup()
        self._popup.set_items(slugs)

        # Position above the input area
        pos = self.mapToGlobal(self.rect().topLeft())
        popup_height = self._popup.sizeHint().height()
        self._popup.move(pos.x(), pos.y() - popup_height - 4)
        self._popup.show()

    def _dismiss_popup(self) -> None:
        if self._popup and self._popup.isVisible():
            self._popup.hide()

    def _accept_completion(self, slug: str) -> None:
        """Replace current text with /slug and a trailing space."""
        self._dismiss_popup()
        self.setPlainText(f"/{slug} ")
        # Move cursor to end
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)
