"""Cross-reference tools."""

from __future__ import annotations

from typing import Annotated

from .base import tool


try:
    import ida_funcs
    import ida_name
    import ida_xref
    import idautils
except ImportError:
    pass



@tool(category="xrefs")
def xrefs_to(
    address: Annotated[str, "Target address (hex string)"],
    limit: Annotated[int, "Max results"] = 30,
) -> str:
    """Get all cross-references to the given address."""

    ea = int(address, 0)
    target_name = ida_name.get_name(ea)
    lines = [f"Cross-references to 0x{ea:x}" + (f" ({target_name})" if target_name else "") + ":"]

    count = 0
    for xref in idautils.XrefsTo(ea, 0):
        if count >= limit:
            lines.append(f"  ... (truncated at {limit})")
            break

        xtype = ida_xref.get_xref_type_name(xref.type)
        func = ida_funcs.get_func(xref.frm)
        fname = ida_name.get_name(func.start_ea) if func else "?"
        lines.append(f"  0x{xref.frm:x}  [{xtype:12s}]  in {fname}")
        count += 1

    if count == 0:
        lines.append("  (none)")
    return "\n".join(lines)


@tool(category="xrefs")
def xrefs_from(
    address: Annotated[str, "Source address (hex string)"],
    limit: Annotated[int, "Max results"] = 30,
) -> str:
    """Get all cross-references from the given address."""

    ea = int(address, 0)
    lines = [f"Cross-references from 0x{ea:x}:"]

    count = 0
    for xref in idautils.XrefsFrom(ea, 0):
        if count >= limit:
            lines.append(f"  ... (truncated at {limit})")
            break
        xtype = ida_xref.get_xref_type_name(xref.type)
        target_name = ida_name.get_name(xref.to) or ""
        lines.append(f"  0x{xref.to:x}  [{xtype:12s}]  {target_name}")
        count += 1

    if count == 0:
        lines.append("  (none)")
    return "\n".join(lines)


@tool(category="xrefs")
def function_xrefs(
    address: Annotated[str, "Function address (hex string)"],
) -> str:
    """Get cross-references to and from a function (callers + callees)."""

    ea = int(address, 0)
    func = ida_funcs.get_func(ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    fname = ida_name.get_name(func.start_ea)

    # Callers
    callers = set()
    for ref in idautils.CodeRefsTo(func.start_ea, 0):
        cf = ida_funcs.get_func(ref)
        if cf and cf.start_ea != func.start_ea:
            callers.add(ida_name.get_name(cf.start_ea))

    # Callees
    callees = set()
    for item in idautils.FuncItems(func.start_ea):
        for ref in idautils.CodeRefsFrom(item, 0):
            cf = ida_funcs.get_func(ref)
            if cf and cf.start_ea != func.start_ea:
                callees.add(ida_name.get_name(cf.start_ea))

    parts = [f"Function: {fname} (0x{func.start_ea:x})"]
    parts.append(f"\nCallers ({len(callers)}):")
    for c in sorted(callers):
        parts.append(f"  {c}")
    parts.append(f"\nCallees ({len(callees)}):")
    for c in sorted(callees):
        parts.append(f"  {c}")
    return "\n".join(parts)
