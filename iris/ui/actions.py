"""Backward-compatible re-export for IDA action hooks.

Canonical location: iris.ida.ui.actions
"""

from iris.ida.ui import actions as _ida_actions

for _name in dir(_ida_actions):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_ida_actions, _name)

__all__ = [n for n in dir(_ida_actions) if not n.startswith("__")]
