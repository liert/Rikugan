"""Function listing, searching, and info tools."""

from __future__ import annotations

from typing import Annotated, Optional

from ..core.logging import log_debug
from .base import tool

try:
    import ida_funcs
    import ida_gdl
    import ida_name
    import idc
    import idautils
except ImportError:
    pass


@tool(category="functions")
def list_functions(
    offset: Annotated[int, "Start index for pagination"] = 0,
    limit: Annotated[int, "Max number of functions to return"] = 50,
) -> str:
    """List functions in the binary with pagination."""

    funcs = list(idautils.Functions())
    total = len(funcs)
    page = funcs[offset:offset + limit]

    lines = [f"Functions {offset}–{offset + len(page)} of {total}:"]
    for ea in page:
        name = ida_name.get_name(ea)
        lines.append(f"  0x{ea:x}  {name}")
    return "\n".join(lines)


@tool(category="functions")
def get_function_info(address: Annotated[str, "Function address (hex string)"]) -> str:
    """Get detailed information about a specific function."""

    ea = int(address, 0)
    func = ida_funcs.get_func(ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    name = ida_name.get_name(func.start_ea)
    size = func.end_ea - func.start_ea
    flags = func.flags

    # Count basic blocks and instructions
    blocks = 0
    instrs = 0
    try:
        fc = ida_gdl.FlowChart(func)
        for block in fc:
            blocks += 1
            head = block.start_ea
            while head < block.end_ea:
                instrs += 1
                head = idc.next_head(head, block.end_ea)
    except Exception as e:
        log_debug(f"FlowChart analysis failed for 0x{ea:x}: {e}")

    # Get callers and callees
    callers = []
    for ref in idautils.CodeRefsTo(func.start_ea, 0):
        caller_func = ida_funcs.get_func(ref)
        if caller_func:
            cname = ida_name.get_name(caller_func.start_ea)
            callers.append(cname)
    callers = list(set(callers))[:10]

    callees = []
    for item in idautils.FuncItems(func.start_ea):
        for ref in idautils.CodeRefsFrom(item, 0):
            callee_func = ida_funcs.get_func(ref)
            if callee_func and callee_func.start_ea != func.start_ea:
                cname = ida_name.get_name(callee_func.start_ea)
                callees.append(cname)
    callees = list(set(callees))[:10]

    parts = [
        f"Name: {name}",
        f"Address: 0x{func.start_ea:x} – 0x{func.end_ea:x}",
        f"Size: {size} bytes",
        f"Basic blocks: {blocks}",
        f"Instructions: {instrs}",
    ]
    if callers:
        parts.append(f"Callers ({len(callers)}): {', '.join(callers)}")
    if callees:
        parts.append(f"Callees ({len(callees)}): {', '.join(callees)}")
    return "\n".join(parts)


@tool(category="functions")
def search_functions(
    query: Annotated[str, "Search string (substring match on function name)"],
    limit: Annotated[int, "Max results"] = 20,
) -> str:
    """Search for functions by name substring."""

    results = []
    q = query.lower()
    for ea in idautils.Functions():
        name = ida_name.get_name(ea)
        if q in name.lower():
            results.append(f"  0x{ea:x}  {name}")
            if len(results) >= limit:
                break

    if not results:
        return f"No functions matching '{query}'"
    return f"Found {len(results)} function(s):\n" + "\n".join(results)
