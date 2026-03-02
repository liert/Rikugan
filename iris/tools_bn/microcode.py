"""Backward-compat shim — canonical location: iris.binja.tools.il.

The il module was renamed from microcode to use proper Binary Ninja terminology.
Old tool names (get_microcode, etc.) are still available as aliases.
"""

from iris.binja.tools.il import *  # noqa: F401,F403
# Explicit aliases for backward compat
from iris.binja.tools.il import (  # noqa: F401
    get_il as get_microcode,
    get_il_block as get_microcode_block,
    nop_instructions as nop_microcode,
    install_il_optimizer as install_microcode_optimizer,
    remove_il_optimizer as remove_microcode_optimizer,
    list_il_optimizers as list_microcode_optimizers,
    redecompile_function,
)
