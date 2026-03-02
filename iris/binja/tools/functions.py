"""Function listing, searching, and info tools for Binary Ninja."""

from __future__ import annotations

from typing import Annotated

from ...core.logging import log_debug
from ...tools.base import tool
from .common import (
    get_function_at,
    get_function_end,
    get_function_name,
    get_instruction_len,
    iter_function_instruction_addresses,
    iter_functions,
    parse_addr_like,
    require_bv,
)


def _collect_callers(func) -> list[str]:
    callers = set()
    direct = getattr(func, "callers", None)
    if direct is not None:
        try:
            for c in direct:
                callers.add(get_function_name(c))
        except Exception:
            pass
    return sorted(callers)


def _collect_callees(func) -> list[str]:
    callees = set()
    direct = getattr(func, "callees", None)
    if direct is not None:
        try:
            for c in direct:
                callees.add(get_function_name(c))
        except Exception:
            pass
    return sorted(callees)


@tool(category="functions")
def list_functions(
    offset: Annotated[int, "Start index for pagination"] = 0,
    limit: Annotated[int, "Max number of functions to return"] = 50,
) -> str:
    """List functions in the binary with pagination."""
    bv = require_bv()
    funcs = iter_functions(bv)
    total = len(funcs)
    page = funcs[offset:offset + limit]

    lines = [f"Functions {offset}\u2013{offset + len(page)} of {total}:"]
    for f in page:
        start = int(getattr(f, "start", 0))
        lines.append(f"  0x{start:x}  {get_function_name(f)}")
    return "\n".join(lines)


@tool(category="functions")
def get_function_info(address: Annotated[str, "Function address (hex string)"]) -> str:
    """Get detailed information about a specific function."""
    bv = require_bv()
    ea = parse_addr_like(address)
    func = get_function_at(bv, ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    start = int(getattr(func, "start", ea))
    end = get_function_end(func)
    size = max(0, end - start)
    blocks = 0
    instrs = 0

    try:
        bbs = list(getattr(func, "basic_blocks", []) or [])
        blocks = len(bbs)
        if blocks:
            for bb in bbs:
                ic = getattr(bb, "instruction_count", None)
                if isinstance(ic, int) and ic >= 0:
                    instrs += ic
                else:
                    cur = int(getattr(bb, "start", 0))
                    bb_end = int(getattr(bb, "end", cur))
                    while cur < bb_end:
                        instrs += 1
                        step = max(1, get_instruction_len(bv, cur))
                        cur += step
        else:
            instrs = len(list(iter_function_instruction_addresses(func)))
    except Exception as e:
        log_debug(f"Basic block analysis failed for 0x{start:x}: {e}")

    callers = _collect_callers(func)[:10]
    callees = _collect_callees(func)[:10]

    parts = [
        f"Name: {get_function_name(func)}",
        f"Address: 0x{start:x} \u2013 0x{end:x}",
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
    bv = require_bv()
    q = query.lower()
    results = []
    for func in iter_functions(bv):
        name = get_function_name(func)
        if q in name.lower():
            start = int(getattr(func, "start", 0))
            results.append(f"  0x{start:x}  {name}")
            if len(results) >= limit:
                break
    if not results:
        return f"No functions matching '{query}'"
    return f"Found {len(results)} function(s):\n" + "\n".join(results)
