"""Mutation tools: rename, comment, set type."""

from __future__ import annotations

from typing import Annotated, Optional

from .base import tool

_HAS_HEXRAYS = False
try:
    import ida_funcs
    import ida_hexrays
    import ida_name
    import idc
    _HAS_HEXRAYS = True
except ImportError:
    pass


@tool(category="annotations", mutating=True)
def rename_function(
    address: Annotated[str, "Function address (hex string)"],
    new_name: Annotated[str, "New function name"],
) -> str:
    """Rename a function."""

    ea = int(address, 0)
    func = ida_funcs.get_func(ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    old_name = ida_name.get_name(func.start_ea)
    ok = ida_name.set_name(func.start_ea, new_name, ida_name.SN_NOWARN | ida_name.SN_NOCHECK)
    if ok:
        return f"Renamed 0x{func.start_ea:x}: {old_name} → {new_name}"
    return f"Failed to rename function at 0x{func.start_ea:x}"


@tool(category="annotations", mutating=True)
def rename_variable(
    func_address: Annotated[str, "Function address (hex string)"],
    old_name: Annotated[str, "Current variable name"],
    new_name: Annotated[str, "New variable name"],
) -> str:
    """Rename a local variable in a decompiled function."""
    if not _HAS_HEXRAYS:
        return "Hex-Rays decompiler not available"

    ea = int(func_address, 0)
    try:
        cfunc = ida_hexrays.decompile(ea)
    except Exception as e:
        return f"Decompilation failed: {e}"

    if cfunc is None:
        return f"No decompilation for 0x{ea:x}"

    lvars = cfunc.get_lvars()
    for lv in lvars:
        if lv.name == old_name:
            ok = ida_hexrays.rename_lvar(cfunc.entry_ea, lv.name, new_name)
            if ok:
                return f"Renamed variable: {old_name} → {new_name}"
            return f"Failed to rename variable {old_name}"

    return f"Variable '{old_name}' not found in function at 0x{ea:x}"


@tool(category="annotations", mutating=True)
def set_comment(
    address: Annotated[str, "Address (hex string)"],
    comment: Annotated[str, "Comment text"],
    repeatable: Annotated[bool, "Set as repeatable comment"] = False,
) -> str:
    """Set a comment at the given address."""

    ea = int(address, 0)
    ok = idc.set_cmt(ea, comment, repeatable)
    if ok:
        kind = "repeatable " if repeatable else ""
        return f"Set {kind}comment at 0x{ea:x}: {comment}"
    return f"Failed to set comment at 0x{ea:x}"


@tool(category="annotations", mutating=True)
def set_function_comment(
    address: Annotated[str, "Function address (hex string)"],
    comment: Annotated[str, "Comment text"],
    repeatable: Annotated[bool, "Set as repeatable comment"] = False,
) -> str:
    """Set a function-level comment."""

    ea = int(address, 0)
    func = ida_funcs.get_func(ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    ok = ida_funcs.set_func_cmt(func, comment, repeatable)
    if ok:
        return f"Set function comment at 0x{func.start_ea:x}"
    return f"Failed to set function comment at 0x{func.start_ea:x}"


@tool(category="annotations", mutating=True)
def rename_address(
    address: Annotated[str, "Address (hex string)"],
    new_name: Annotated[str, "New name/label"],
) -> str:
    """Set or change the name/label at an address."""

    ea = int(address, 0)
    old = ida_name.get_name(ea)
    ok = ida_name.set_name(ea, new_name, ida_name.SN_NOWARN | ida_name.SN_NOCHECK)
    if ok:
        return f"Named 0x{ea:x}: {old or '(unnamed)'} → {new_name}"
    return f"Failed to set name at 0x{ea:x}"


@tool(category="annotations", mutating=True)
def set_type(
    address: Annotated[str, "Address (hex string)"],
    type_string: Annotated[str, "C type string (e.g. 'int __fastcall(void*, int)')"],
) -> str:
    """Set the type of a function or data item."""

    ea = int(address, 0)
    ok = idc.SetType(ea, type_string)
    if ok:
        return f"Set type at 0x{ea:x}: {type_string}"
    return f"Failed to set type at 0x{ea:x}. Check syntax: {type_string}"
