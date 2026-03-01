"""Qt compatibility layer for IRIS.

IDA 9+ ships PySide6 exclusively (its ``PyQt5`` module is a thin shim over
PySide6, not a separate binding).  We import from PySide6 directly to
minimize Shiboken type-wrapper initialization and reduce the crash surface
on Python 3.14.
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt, QObject, QTimer  # noqa: F401
from PySide6.QtWidgets import (  # noqa: F401
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QScrollArea, QFrame,
    QDialog, QDialogButtonBox, QComboBox, QLineEdit, QSpinBox,
    QDoubleSpinBox, QCheckBox, QGroupBox, QFormLayout,
    QToolButton, QSizePolicy,
)

QT_BINDING = "PySide6"


def is_pyside6() -> bool:
    return True
