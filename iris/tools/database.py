"""Database-level tools: segments, imports, exports."""

from __future__ import annotations

from typing import Annotated

from .base import tool


try:
    import ida_ida
    import ida_nalt
    import ida_segment
    import idaapi
    import idautils
    import idc
except ImportError:
    pass



@tool(category="database")
def list_segments() -> str:
    """List all segments in the binary."""

    lines = ["Segments:"]
    for seg_ea in idautils.Segments():
        name = idc.get_segm_name(seg_ea)
        end = idc.get_segm_end(seg_ea)
        size = end - seg_ea
        perms = ""
        seg = ida_segment.getseg(seg_ea)
        if seg:
            perms = ""
            if seg.perm & ida_segment.SFL_READ:
                perms += "R"
            if seg.perm & ida_segment.SFL_WRITE:
                perms += "W"
            if seg.perm & ida_segment.SFL_EXEC:
                perms += "X"
        lines.append(f"  {name:16s}  0x{seg_ea:x}–0x{end:x}  ({size:#x} bytes)  {perms}")
    return "\n".join(lines)


@tool(category="database")
def list_imports() -> str:
    """List all imported functions."""

    lines = ["Imports:"]
    nimps = ida_nalt.get_import_module_qty()
    for i in range(nimps):
        mod_name = ida_nalt.get_import_module_name(i)
        entries: list = []

        def _cb(ea, name, ordinal):
            if name:
                entries.append(f"    0x{ea:x}  {name}")
            else:
                entries.append(f"    0x{ea:x}  ordinal #{ordinal}")
            return True

        ida_nalt.enum_import_names(i, _cb)
        lines.append(f"  [{mod_name}] ({len(entries)} imports)")
        lines.extend(entries[:50])
        if len(entries) > 50:
            lines.append(f"    ... and {len(entries) - 50} more")
    return "\n".join(lines)


@tool(category="database")
def list_exports() -> str:
    """List all exported functions/symbols."""

    lines = ["Exports:"]
    for i, (ea, _, name) in enumerate(idautils.Entries()):
        lines.append(f"  0x{ea:x}  {name}")
        if i >= 200:
            lines.append("  ... (truncated)")
            break
    return "\n".join(lines)


@tool(category="database")
def get_binary_info() -> str:
    """Get general information about the loaded binary."""

    lines = [f"File: {ida_nalt.get_root_filename()}"]

    # IDA 9.x uses ida_ida.inf_get_procname() etc. instead of get_inf_structure()
    try:
        lines.append(f"Processor: {ida_ida.inf_get_procname()}")
        if ida_ida.inf_is_64bit():
            lines.append("Bits: 64")
        elif ida_ida.inf_is_32bit():
            lines.append("Bits: 32")
        else:
            lines.append("Bits: 16")
        lines.append(f"Entry point: 0x{ida_ida.inf_get_start_ea():x}")
        lines.append(f"Min address: 0x{ida_ida.inf_get_min_ea():x}")
        lines.append(f"Max address: 0x{ida_ida.inf_get_max_ea():x}")
    except AttributeError:
        # Fallback for older IDA
        try:
            info = idaapi.get_inf_structure()
            lines.append(f"Processor: {info.procname}")
            lines.append(f"Bits: {16 if info.is_16bit() else 32 if info.is_32bit() else 64}")
            lines.append(f"Entry point: 0x{info.start_ea:x}")
            lines.append(f"Min address: 0x{info.min_ea:x}")
            lines.append(f"Max address: 0x{info.max_ea:x}")
        except (AttributeError, TypeError):
            lines.append("Processor: (unavailable)")  # IDA API not supported

    try:
        lines.append(f"File type: {idaapi.get_file_type_name()}")
    except AttributeError:
        pass  # get_file_type_name not available in this IDA version

    func_count = sum(1 for _ in idautils.Functions())
    lines.append(f"Functions: {func_count}")

    return "\n".join(lines)


@tool(category="database")
def read_bytes(
    address: Annotated[str, "Start address (hex string)"],
    size: Annotated[int, "Number of bytes to read"] = 64,
) -> str:
    """Read raw bytes at an address and return as hex dump."""

    _MAX_READ_BYTES = 1024
    ea = int(address, 0)
    if size > _MAX_READ_BYTES:
        size = _MAX_READ_BYTES

    lines = []
    for off in range(0, size, 16):
        row_ea = ea + off
        hex_parts = []
        ascii_parts = []
        for j in range(16):
            if off + j >= size:
                hex_parts.append("  ")
                ascii_parts.append(" ")
            else:
                b = idc.get_wide_byte(row_ea + j)
                hex_parts.append(f"{b:02x}")
                ascii_parts.append(chr(b) if 0x20 <= b < 0x7f else ".")
        hex_str = " ".join(hex_parts[:8]) + "  " + " ".join(hex_parts[8:])
        ascii_str = "".join(ascii_parts)
        lines.append(f"  0x{row_ea:08x}  {hex_str}  |{ascii_str}|")
    return "\n".join(lines)
