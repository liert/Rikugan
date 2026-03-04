"""Type engineering tools: struct/enum/typedef creation and manipulation."""

from __future__ import annotations

import importlib
import json
from typing import Annotated, Any, Dict, List, Optional, Tuple

from ..core.errors import ToolError
from ..core.logging import log_debug
from .base import parse_addr, tool

# Import each module independently so a single missing module (e.g. ida_struct
# removed in IDA 9.x) does not prevent the others from loading.
_HAS_HEXRAYS = False
_HAS_IDA_STRUCT = False

ida_auto = None
ida_bytes = None
ida_hexrays = None
ida_struct = None
ida_typeinf = None
idc = None
ida_enum = None

for _mod_name, _target in (
    ("ida_auto", "ida_auto"),
    ("ida_bytes", "ida_bytes"),
    ("ida_hexrays", "ida_hexrays"),
    ("ida_struct", "ida_struct"),
    ("ida_typeinf", "ida_typeinf"),
    ("idc", "idc"),
):
    try:
        globals()[_target] = importlib.import_module(_mod_name)
    except ImportError as _e:
        log_debug(f"IDA module not available: {_mod_name}: {_e}")

_HAS_HEXRAYS = ida_hexrays is not None
_HAS_IDA_STRUCT = ida_struct is not None

# ida_enum was removed in IDA 9.x (enums merged into ida_typeinf).
try:
    ida_enum = importlib.import_module("ida_enum")
except ImportError as e:
    log_debug(f"ida_enum not available (IDA 9.x+): {e}")

if _HAS_HEXRAYS:
    class _OffsetCollector(ida_hexrays.ctree_visitor_t):  # type: ignore[misc]
        """ctree visitor that collects pointer field access offsets and sizes."""

        def __init__(self) -> None:
            super().__init__(ida_hexrays.CV_FAST)
            self.accesses: Dict[int, tuple] = {}  # offset -> (size, count)

        def visit_expr(self, expr: Any) -> int:
            if expr.op in (ida_hexrays.cot_memref, ida_hexrays.cot_memptr):
                off = expr.m
                size = expr.ptrsize if hasattr(expr, "ptrsize") else 0
                if size == 0:
                    tif = expr.type
                    size = tif.get_size() if tif else 4
                if off in self.accesses:
                    prev_size, prev_count = self.accesses[off]
                    self.accesses[off] = (max(prev_size, size), prev_count + 1)
                else:
                    self.accesses[off] = (size, 1)
            return 0


# ---------------------------------------------------------------------------
# Helpers — parse a C type string into a tinfo_t
# ---------------------------------------------------------------------------

def _parse_type(type_str: str) -> "ida_typeinf.tinfo_t":
    """Parse a C type string into a tinfo_t, with named-type fallback."""
    tif = ida_typeinf.tinfo_t()
    # Try parsing as a C declaration first (e.g. "unsigned int", "void *")
    decl = type_str if type_str.rstrip().endswith(";") else f"{type_str};"
    if ida_typeinf.parse_decl(tif, None, decl, ida_typeinf.PT_SIL):
        return tif
    # Fallback: maybe it's a named type (struct/enum/typedef name)
    if tif.get_named_type(None, type_str):
        return tif
    # Fallback: try without the semicolon
    if ida_typeinf.parse_decl(tif, None, type_str, ida_typeinf.PT_SIL):
        return tif
    return None


# ---------------------------------------------------------------------------
# Structs — IDA 9.x path (ida_struct removed; everything via ida_typeinf)
# ---------------------------------------------------------------------------

def _create_struct_ida9(name: str, field_list: list) -> str:
    """Create a struct using the IDA 9.x ida_typeinf UDT API."""
    # Check struct doesn't already exist
    existing = ida_typeinf.tinfo_t()
    if existing.get_named_type(None, name) and existing.is_udt():
        return f"Struct '{name}' already exists"

    udt = ida_typeinf.udt_type_data_t()
    for fld in field_list:
        fname = fld["name"]
        ftype_str = fld.get("type", "int")

        ftif = _parse_type(ftype_str)
        if ftif is None:
            # Ultimate fallback to int
            ftif = ida_typeinf.tinfo_t()
            ida_typeinf.parse_decl(ftif, None, "int;", ida_typeinf.PT_SIL)

        udm = ida_typeinf.udm_t()
        udm.name = fname
        udm.type = ftif
        if fld.get("comment"):
            udm.cmt = fld["comment"]
        udt.push_back(udm)

    tif = ida_typeinf.tinfo_t()
    if not tif.create_udt(udt):
        return f"Failed to build UDT for struct '{name}'"

    # Register in the local type library (None = local IDB TIL)
    err = tif.set_named_type(None, name)
    TERR_OK = getattr(ida_typeinf, "TERR_OK", 0)
    if err != TERR_OK:
        return f"Failed to register struct '{name}' (err={err})"

    total_size = tif.get_size()
    return f"Created struct '{name}' with {len(field_list)} fields, size={total_size}"


def _get_struct_tinfo(name: str) -> "Optional[ida_typeinf.tinfo_t]":
    """Look up a named struct/union in the local TIL. Returns tinfo_t or None."""
    tif = ida_typeinf.tinfo_t()
    if tif.get_named_type(None, name) and tif.is_udt():
        return tif
    return None


def _modify_struct_ida9(
    name: str, action: str, field_name: str, new_name: str,
    field_type: str, offset: int, comment: str, new_size: int,
) -> str:
    """Modify a struct using the IDA 9.x tinfo_t UDT methods."""
    tif = _get_struct_tinfo(name)
    if tif is None:
        return f"Struct '{name}' not found"

    TERR_OK = getattr(ida_typeinf, "TERR_OK", 0)

    if action == "add_field":
        ftif = _parse_type(field_type)
        if ftif is None:
            return f"Failed to parse type '{field_type}'"
        udm = ida_typeinf.udm_t()
        udm.name = field_name
        udm.type = ftif
        if offset >= 0:
            udm.offset = offset * 8  # bytes → bits
        err = tif.add_udm(udm)
        if err == TERR_OK:
            return f"Added field '{field_name}' ({field_type}) to '{name}'"
        return f"Failed to add field (error code {err})"

    elif action == "remove_field":
        udm = ida_typeinf.udm_t()
        udm.name = field_name
        idx = tif.find_udm(udm, ida_typeinf.STRMEM_NAME)
        if idx == -1:
            return f"Field '{field_name}' not found in '{name}'"
        err = tif.del_udm(idx)
        if err == TERR_OK:
            return f"Removed field '{field_name}' from '{name}'"
        return f"Failed to remove field (error code {err})"

    elif action == "rename_field":
        udm = ida_typeinf.udm_t()
        udm.name = field_name
        idx = tif.find_udm(udm, ida_typeinf.STRMEM_NAME)
        if idx == -1:
            return f"Field '{field_name}' not found"
        err = tif.rename_udm(idx, new_name)
        if err == TERR_OK:
            return f"Renamed '{field_name}' → '{new_name}'"
        return f"Rename failed (error code {err})"

    elif action == "retype_field":
        udm = ida_typeinf.udm_t()
        udm.name = field_name
        idx = tif.find_udm(udm, ida_typeinf.STRMEM_NAME)
        if idx == -1:
            return f"Field '{field_name}' not found"
        ftif = _parse_type(field_type)
        if ftif is None:
            return f"Failed to parse type '{field_type}'"
        err = tif.set_udm_type(idx, ftif)
        if err == TERR_OK:
            return f"Retyped '{field_name}' to '{field_type}'"
        return f"Retype failed (error code {err})"

    elif action == "set_field_comment":
        udm = ida_typeinf.udm_t()
        udm.name = field_name
        idx = tif.find_udm(udm, ida_typeinf.STRMEM_NAME)
        if idx == -1:
            return f"Field '{field_name}' not found"
        # Access the actual udm from the UDT details
        udt = ida_typeinf.udt_type_data_t()
        tif.get_udt_details(udt)
        if 0 <= idx < len(udt):
            udt[idx].cmt = comment
            # Rebuild from modified UDT
            new_tif = ida_typeinf.tinfo_t()
            new_tif.create_udt(udt)
            new_tif.set_named_type(None, name, ida_typeinf.NTF_REPLACE)
            return f"Set comment on '{field_name}'"
        return f"Field index {idx} out of range"

    elif action == "resize":
        if new_size <= 0:
            return "New size must be positive"
        current = tif.get_size()
        if new_size <= current:
            return f"Cannot shrink struct (current={current}, requested={new_size})"
        # Add padding bytes at the end to reach the desired size
        pad_size = new_size - current
        pad_tif = ida_typeinf.tinfo_t()
        if pad_size == 1:
            ida_typeinf.parse_decl(pad_tif, None, "char;", ida_typeinf.PT_SIL)
        else:
            ida_typeinf.parse_decl(pad_tif, None, f"char[{pad_size}];", ida_typeinf.PT_SIL)
        udm = ida_typeinf.udm_t()
        udm.name = f"_padding_{current:x}"
        udm.type = pad_tif
        tif.add_udm(udm)
        return f"Resized '{name}' from {current} to {new_size}"

    return f"Unknown action: {action}"


def _get_struct_info_ida9(name: str) -> str:
    """Get struct layout using IDA 9.x ida_typeinf API."""
    tif = _get_struct_tinfo(name)
    if tif is None:
        return f"Struct '{name}' not found"

    size = tif.get_size()
    nmembers = tif.get_udt_nmembers()
    lines = [f"Struct: {name}", f"Size: {size} (0x{size:x})", f"Members: {nmembers}", ""]

    udt = ida_typeinf.udt_type_data_t()
    if not tif.get_udt_details(udt):
        return f"Struct '{name}' found but could not read UDT details"

    for idx, udm in enumerate(udt):
        if hasattr(udm, "is_gap") and udm.is_gap():
            continue
        offset_bytes = udm.offset // 8
        size_bytes = udm.size // 8
        mname = udm.name
        mtype = str(udm.type)
        cmt = getattr(udm, "cmt", "") or ""
        cmt_str = f"  ; {cmt}" if cmt else ""
        lines.append(f"  +0x{offset_bytes:04x}  {mtype:24s} {mname:24s} ({size_bytes} bytes){cmt_str}")

    return "\n".join(lines)


def _list_structs_ida9(name_filter: str) -> str:
    """List all structs using IDA 9.x ordinal iteration."""
    lines = ["Structs:"]
    count = 0
    limit = ida_typeinf.get_ordinal_limit()
    for ordinal in range(1, limit):
        tif = ida_typeinf.tinfo_t()
        if not tif.get_numbered_type(None, ordinal):
            continue
        if not tif.is_udt():
            continue
        sname = tif.get_type_name()
        if not sname:
            continue
        if name_filter and name_filter.lower() not in sname.lower():
            continue
        kind = "union" if tif.is_union() else "struct"
        size = tif.get_size()
        lines.append(f"  {sname:40s} size={size}  ({kind})")
        count += 1
        if count >= 200:
            lines.append("  ... (truncated)")
            break

    if count == 0:
        lines.append("  (none)")
    return "\n".join(lines)


def _apply_struct_to_address_ida9(struct_name: str, ea: int) -> str:
    """Apply a struct at a data address using IDA 9.x apply_tinfo."""
    tif = _get_struct_tinfo(struct_name)
    if tif is None:
        return f"Struct '{struct_name}' not found"

    size = tif.get_size()
    TINFO_DEFINITE = getattr(ida_typeinf, "TINFO_DEFINITE", 0x0001)
    ok = ida_typeinf.apply_tinfo(ea, tif, TINFO_DEFINITE)
    if ok:
        return f"Applied struct '{struct_name}' at 0x{ea:x} ({size} bytes)"
    return f"Failed to apply struct at 0x{ea:x}"


def _propagate_type_ida9(struct_name: str) -> str:
    """Trigger type propagation using IDA 9.x API."""
    tif = _get_struct_tinfo(struct_name)
    if tif is None:
        return f"Struct '{struct_name}' not found"
    # In IDA 9.x, modifying an attached tinfo_t auto-propagates.
    # We force re-analysis by touching the type via set_named_type + auto_wait.
    tif.set_named_type(None, struct_name, ida_typeinf.NTF_REPLACE)
    if ida_auto is not None:
        ida_auto.auto_wait()
    return f"Triggered type propagation for '{struct_name}'"


# --- Structs: public tool functions ---

@tool(category="types", mutating=True)
def create_struct(
    name: Annotated[str, "Struct name"],
    fields: Annotated[str, "JSON array of fields: [{name, type, offset?, comment?}, ...]"],
) -> str:
    """Create a new struct with typed fields."""
    field_list = json.loads(fields)

    if not _HAS_IDA_STRUCT:
        # IDA 9.x path — ida_struct was removed, use ida_typeinf UDT API
        if ida_typeinf is None:
            return "ida_typeinf not available"
        return _create_struct_ida9(name, field_list)

    # IDA 8.x path
    sid = ida_struct.get_struc_id(name)
    if sid != idc.BADADDR:
        return f"Struct '{name}' already exists (id={sid})"

    sid = ida_struct.add_struc(idc.BADADDR, name, False)
    if sid == idc.BADADDR:
        return f"Failed to create struct '{name}'"

    sptr = ida_struct.get_struc(sid)

    for fld in field_list:
        fname = fld["name"]
        ftype_str = fld.get("type", "int")
        foffset = fld.get("offset", idc.BADADDR)

        tif = ida_typeinf.tinfo_t()
        if ida_typeinf.parse_decl(tif, None, f"{ftype_str};", ida_typeinf.PT_SIL):
            size = tif.get_size() or 4
            err = ida_struct.add_struc_member(sptr, fname, foffset, 0, None, size)
            if err == 0:
                memb = ida_struct.get_member_by_name(sptr, fname)
                if memb:
                    ida_struct.set_member_tinfo(sptr, memb, 0, tif, 0)
                    if fld.get("comment"):
                        ida_struct.set_member_cmt(memb, fld["comment"], False)
            else:
                ida_struct.add_struc_member(sptr, fname, foffset, 0, None, 4)
        else:
            ida_struct.add_struc_member(sptr, fname, foffset, 0, None, 4)

    total_size = ida_struct.get_struc_size(sptr)
    return f"Created struct '{name}' with {len(field_list)} fields, size={total_size}"


@tool(category="types", mutating=True)
def modify_struct(
    name: Annotated[str, "Struct name"],
    action: Annotated[str, "Action: add_field, remove_field, rename_field, retype_field, set_field_comment, resize"],
    field_name: Annotated[str, "Field name to modify"] = "",
    new_name: Annotated[str, "New name (for rename_field)"] = "",
    field_type: Annotated[str, "Type string (for add_field/retype_field)"] = "int",
    offset: Annotated[int, "Offset (for add_field)"] = -1,
    comment: Annotated[str, "Comment text (for set_field_comment)"] = "",
    new_size: Annotated[int, "New struct size (for resize)"] = 0,
) -> str:
    """Modify an existing struct: add/remove/rename/retype fields."""
    if not _HAS_IDA_STRUCT:
        # IDA 9.x path
        if ida_typeinf is None:
            return "ida_typeinf not available"
        return _modify_struct_ida9(name, action, field_name, new_name,
                                    field_type, offset, comment, new_size)

    # IDA 8.x path
    sid = ida_struct.get_struc_id(name)
    if sid == idc.BADADDR:
        return f"Struct '{name}' not found"

    sptr = ida_struct.get_struc(sid)

    if action == "add_field":
        tif = ida_typeinf.tinfo_t()
        size = 4
        if ida_typeinf.parse_decl(tif, None, f"{field_type};", ida_typeinf.PT_SIL):
            size = tif.get_size() or 4
        off = offset if offset >= 0 else idc.BADADDR
        err = ida_struct.add_struc_member(sptr, field_name, off, 0, None, size)
        if err == 0:
            memb = ida_struct.get_member_by_name(sptr, field_name)
            if memb and tif.is_correct():
                ida_struct.set_member_tinfo(sptr, memb, 0, tif, 0)
            return f"Added field '{field_name}' ({field_type}) to '{name}'"
        return f"Failed to add field (error code {err})"

    elif action == "remove_field":
        memb = ida_struct.get_member_by_name(sptr, field_name)
        if memb is None:
            return f"Field '{field_name}' not found in '{name}'"
        ida_struct.del_struc_member(sptr, memb.soff)
        return f"Removed field '{field_name}' from '{name}'"

    elif action == "rename_field":
        memb = ida_struct.get_member_by_name(sptr, field_name)
        if memb is None:
            return f"Field '{field_name}' not found"
        ok = ida_struct.set_member_name(sptr, memb.soff, new_name)
        return f"Renamed '{field_name}' → '{new_name}'" if ok else "Rename failed"

    elif action == "retype_field":
        memb = ida_struct.get_member_by_name(sptr, field_name)
        if memb is None:
            return f"Field '{field_name}' not found"
        tif = ida_typeinf.tinfo_t()
        if ida_typeinf.parse_decl(tif, None, f"{field_type};", ida_typeinf.PT_SIL):
            ok = ida_struct.set_member_tinfo(sptr, memb, 0, tif, 0)
            return f"Retyped '{field_name}' to '{field_type}'" if ok else "Retype failed"
        return f"Failed to parse type '{field_type}'"

    elif action == "set_field_comment":
        memb = ida_struct.get_member_by_name(sptr, field_name)
        if memb is None:
            return f"Field '{field_name}' not found"
        ida_struct.set_member_cmt(memb, comment, False)
        return f"Set comment on '{field_name}'"

    elif action == "resize":
        if new_size <= 0:
            return "New size must be positive"
        current = ida_struct.get_struc_size(sptr)
        if new_size > current:
            ida_struct.expand_struc(sptr, 0, new_size - current)
            return f"Resized '{name}' from {current} to {new_size}"
        return f"Cannot shrink struct (current={current}, requested={new_size})"

    return f"Unknown action: {action}"


@tool(category="types")
def get_struct_info(name: Annotated[str, "Struct name"]) -> str:
    """Get full struct layout: fields, types, offsets, sizes."""
    if not _HAS_IDA_STRUCT:
        # IDA 9.x path
        if ida_typeinf is None:
            return "ida_typeinf not available"
        return _get_struct_info_ida9(name)

    sid = ida_struct.get_struc_id(name)
    if sid == idc.BADADDR:
        return f"Struct '{name}' not found"

    sptr = ida_struct.get_struc(sid)
    size = ida_struct.get_struc_size(sptr)
    nmembers = sptr.memqty

    lines = [f"Struct: {name}", f"Size: {size} (0x{size:x})", f"Members: {nmembers}", ""]

    for i in range(nmembers):
        memb = sptr.get_member(i)
        mname = ida_struct.get_member_name(memb.id)
        msize = ida_struct.get_member_size(memb)
        moff = memb.soff

        # Get type
        tif = ida_typeinf.tinfo_t()
        if ida_struct.get_member_tinfo(tif, memb):
            tname = str(tif)
        else:
            tname = "?"

        cmt = ida_struct.get_member_cmt(memb, False) or ""
        cmt_str = f"  ; {cmt}" if cmt else ""
        lines.append(f"  +0x{moff:04x}  {tname:24s} {mname:24s} ({msize} bytes){cmt_str}")

    return "\n".join(lines)


@tool(category="types")
def list_structs(
    filter: Annotated[str, "Name filter (substring match)"] = "",
) -> str:
    """List all structs in the IDB."""
    if not _HAS_IDA_STRUCT:
        # IDA 9.x path
        if ida_typeinf is None:
            return "ida_typeinf not available"
        return _list_structs_ida9(filter)

    lines = ["Structs:"]
    idx = ida_struct.get_first_struc_idx()
    count = 0
    while idx != idc.BADADDR:
        sid = ida_struct.get_struc_by_idx(idx)
        sptr = ida_struct.get_struc(sid)
        sname = ida_struct.get_struc_name(sid)
        if not filter or filter.lower() in sname.lower():
            size = ida_struct.get_struc_size(sptr)
            lines.append(f"  {sname:40s} size={size}")
            count += 1
        idx = ida_struct.get_next_struc_idx(idx)
        if count >= 200:
            lines.append("  ... (truncated)")
            break

    if count == 0:
        lines.append("  (none)")
    return "\n".join(lines)


# --- Enums ---

def _require_ida_enum() -> None:
    if ida_enum is None:
        raise ToolError(
            "ida_enum module not available (removed in IDA 9.x; "
            "use ida_typeinf for enum operations)",
            tool_name="types",
        )


@tool(category="types", mutating=True)
def create_enum(
    name: Annotated[str, "Enum name"],
    members: Annotated[str, "JSON array of members: [{name, value}, ...]"],
    bitfield: Annotated[bool, "Create as bitfield enum"] = False,
) -> str:
    """Create a new enum with name/value pairs."""
    _require_ida_enum()
    eid = ida_enum.get_enum(name)
    if eid != idc.BADADDR:
        return f"Enum '{name}' already exists"

    eid = ida_enum.add_enum(idc.BADADDR, name, 0)
    if eid == idc.BADADDR:
        return f"Failed to create enum '{name}'"

    if bitfield:
        ida_enum.set_enum_bf(eid, True)

    member_list = json.loads(members)
    for m in member_list:
        mname = m["name"]
        mval = m["value"]
        bmask = mval if bitfield else 0xFFFFFFFF
        err = ida_enum.add_enum_member(eid, mname, mval, bmask)
        if err:
            pass  # Non-fatal: duplicate values etc.

    return f"Created enum '{name}' with {len(member_list)} members"


@tool(category="types", mutating=True)
def modify_enum(
    name: Annotated[str, "Enum name"],
    action: Annotated[str, "Action: add_member, remove_member, rename_member"],
    member_name: Annotated[str, "Member name"] = "",
    new_name: Annotated[str, "New name (for rename)"] = "",
    value: Annotated[int, "Value (for add_member)"] = 0,
) -> str:
    """Modify an existing enum."""
    _require_ida_enum()
    eid = ida_enum.get_enum(name)
    if eid == idc.BADADDR:
        return f"Enum '{name}' not found"

    if action == "add_member":
        err = ida_enum.add_enum_member(eid, member_name, value)
        return f"Added '{member_name}' = {value}" if err == 0 else f"Failed (error {err})"
    elif action == "remove_member":
        cid = ida_enum.get_enum_member_by_name(member_name)
        if cid == idc.BADADDR:
            return f"Member '{member_name}' not found"
        val = ida_enum.get_enum_member_value(cid)
        serial = ida_enum.get_enum_member_serial(cid)
        bmask = ida_enum.get_enum_member_bmask(cid)
        ok = ida_enum.del_enum_member(eid, val, serial, bmask)
        return f"Removed '{member_name}'" if ok else "Remove failed"
    elif action == "rename_member":
        cid = ida_enum.get_enum_member_by_name(member_name)
        if cid == idc.BADADDR:
            return f"Member '{member_name}' not found"
        ok = ida_enum.set_enum_member_name(cid, new_name)
        return f"Renamed '{member_name}' → '{new_name}'" if ok else "Rename failed"

    return f"Unknown action: {action}"


@tool(category="types")
def get_enum_info(name: Annotated[str, "Enum name"]) -> str:
    """Get all enum members with values."""
    _require_ida_enum()
    eid = ida_enum.get_enum(name)
    if eid == idc.BADADDR:
        return f"Enum '{name}' not found"

    is_bf = ida_enum.is_bf(eid)
    lines = [f"Enum: {name}" + (" (bitfield)" if is_bf else ""), ""]

    bmask = ida_enum.get_first_bmask(eid) if is_bf else 0xFFFFFFFF
    while True:
        val = ida_enum.get_first_enum_member(eid, bmask)
        while val != 0xFFFFFFFFFFFFFFFF and val != 0xFFFFFFFF:
            cid = ida_enum.get_enum_member(eid, val, 0, bmask)
            if cid != idc.BADADDR:
                mname = ida_enum.get_enum_member_name(cid)
                lines.append(f"  {mname:40s} = 0x{val:x} ({val})")
            val = ida_enum.get_next_enum_member(eid, val, bmask)

        if not is_bf:
            break
        bmask = ida_enum.get_next_bmask(eid, bmask)
        if bmask == 0xFFFFFFFFFFFFFFFF or bmask == 0xFFFFFFFF:
            break

    return "\n".join(lines)


@tool(category="types")
def list_enums(
    filter: Annotated[str, "Name filter (substring match)"] = "",
) -> str:
    """List all enums in the IDB."""
    _require_ida_enum()
    lines = ["Enums:"]
    count = ida_enum.get_enum_qty()
    found = 0
    for i in range(count):
        eid = ida_enum.getn_enum(i)
        ename = ida_enum.get_enum_name(eid)
        if not filter or filter.lower() in ename.lower():
            nmembs = ida_enum.get_enum_size(eid)
            lines.append(f"  {ename:40s} ({nmembs} members)")
            found += 1
        if found >= 200:
            lines.append("  ... (truncated)")
            break

    if found == 0:
        lines.append("  (none)")
    return "\n".join(lines)


# --- Typedefs & type application ---

@tool(category="types", mutating=True)
def create_typedef(
    name: Annotated[str, "New type alias name"],
    base_type: Annotated[str, "Base type (e.g. 'unsigned int', 'DWORD')"],
) -> str:
    """Create a type alias (typedef)."""
    if idc is None:
        return "idc module not available"
    decl = f"typedef {base_type} {name};"
    result = idc.parse_decls(decl, 0)
    if result is not None and result >= 0:
        return f"Created typedef: {decl}"
    return f"Failed to create typedef: {decl}"


@tool(category="types", mutating=True)
def apply_struct_to_address(
    struct_name: Annotated[str, "Struct name to apply"],
    address: Annotated[str, "Data address (hex string)"],
) -> str:
    """Apply a struct type at a data address."""
    ea = parse_addr(address)

    if not _HAS_IDA_STRUCT:
        # IDA 9.x path — use apply_tinfo
        if ida_typeinf is None:
            return "ida_typeinf not available"
        return _apply_struct_to_address_ida9(struct_name, ea)

    # IDA 8.x path
    sid = ida_struct.get_struc_id(struct_name)
    if sid == idc.BADADDR:
        return f"Struct '{struct_name}' not found"

    sptr = ida_struct.get_struc(sid)
    size = ida_struct.get_struc_size(sptr)
    ok = ida_bytes.create_struct(ea, size, sid)
    if ok:
        return f"Applied struct '{struct_name}' at 0x{ea:x} ({size} bytes)"
    return f"Failed to apply struct at 0x{ea:x}"


@tool(category="types", mutating=True)
def apply_type_to_variable(
    func_address: Annotated[str, "Function address (hex string)"],
    var_name: Annotated[str, "Variable name in the decompiler"],
    type_str: Annotated[str, "C type string to apply"],
) -> str:
    """Retype a local variable in a decompiled function."""
    if not _HAS_HEXRAYS:
        return "Hex-Rays not available"
    if ida_typeinf is None:
        return "ida_typeinf not available"

    ea = parse_addr(func_address)
    try:
        cfunc = ida_hexrays.decompile(ea)
    except Exception as e:
        return f"Decompilation failed: {e}"

    tif = _parse_type(type_str)
    if tif is None:
        return f"Failed to parse type: {type_str}"

    for lv in cfunc.get_lvars():
        if lv.name == var_name:
            ok = ida_hexrays.set_lvar_type(cfunc.entry_ea, lv, tif)
            if ok:
                return f"Set type of '{var_name}' to '{type_str}'"
            return f"Failed to set type on '{var_name}'"

    return f"Variable '{var_name}' not found in 0x{ea:x}"


@tool(category="types", mutating=True)
def set_function_prototype(
    address: Annotated[str, "Function address (hex string)"],
    prototype: Annotated[str, "Full C prototype (e.g. 'int __fastcall foo(void* ctx, int len)')"],
) -> str:
    """Set a function's full calling convention and prototype."""
    if idc is None:
        return "idc module not available"

    ea = parse_addr(address)
    ok = idc.SetType(ea, prototype)
    if ok:
        return f"Set prototype at 0x{ea:x}: {prototype}"
    return f"Failed to set prototype. Check syntax: {prototype}"


@tool(category="types", mutating=True)
def import_c_header(
    c_code: Annotated[str, "C header code containing struct/enum/typedef definitions"],
) -> str:
    """Parse C header code and define all structs/enums/typedefs found."""
    if idc is None:
        return "idc module not available"

    result = idc.parse_decls(c_code, 0)
    if result is not None and result >= 0:
        return f"Successfully parsed C declarations ({result} type(s) defined)"
    return "Failed to parse C declarations. Check syntax."


@tool(category="types", requires_decompiler=True)
def suggest_struct_from_accesses(
    address: Annotated[str, "Function or pointer address to analyze (hex string)"],
) -> str:
    """Analyze field access patterns and suggest a struct layout.

    Uses the Hex-Rays CTree to collect pointer dereference offsets and
    proposes a candidate struct definition.
    """
    if not _HAS_HEXRAYS:
        return "Hex-Rays not available"

    ea = parse_addr(address)
    try:
        cfunc = ida_hexrays.decompile(ea)
    except Exception as e:
        return f"Decompilation failed: {e}"

    # Visitor to collect member access offsets
    collector = _OffsetCollector()
    collector.apply_to(cfunc.body, None)

    if not collector.accesses:
        return "No pointer field accesses detected in this function"

    # Sort by offset and build struct suggestion
    sorted_offsets = sorted(collector.accesses.items())
    lines = [f"Suggested struct from access analysis at 0x{ea:x}:", ""]

    size_type_map = {1: "uint8_t", 2: "uint16_t", 4: "uint32_t", 8: "uint64_t"}
    total_size = 0
    for off, (size, count) in sorted_offsets:
        tname = size_type_map.get(size, f"char[{size}]")
        lines.append(f"  +0x{off:04x}  {tname:16s} field_{off:x};    // accessed {count}x")
        total_size = max(total_size, off + size)

    lines.append(f"\nEstimated struct size: {total_size} (0x{total_size:x}) bytes")

    # Also produce a C declaration
    lines.append("\nSuggested C declaration:")
    lines.append(f"struct auto_struct_{ea:x} {{")
    prev_end = 0
    for off, (size, count) in sorted_offsets:
        if off > prev_end:
            pad = off - prev_end
            lines.append(f"    char _pad_{prev_end:x}[{pad}];")
        tname = size_type_map.get(size, f"char[{size}]" if size > 8 else "uint32_t")
        if size > 8 and size not in size_type_map:
            lines.append(f"    char field_{off:x}[{size}];")
        else:
            lines.append(f"    {tname} field_{off:x};")
        prev_end = off + size
    lines.append("};")

    return "\n".join(lines)


@tool(category="types", mutating=True)
def propagate_type(
    struct_name: Annotated[str, "Struct name to propagate"],
    field_index: Annotated[int, "Specific field index to propagate (-1 for all)"] = -1,
) -> str:
    """Re-run type propagation after struct changes to update xrefs and decompilation."""
    if not _HAS_IDA_STRUCT:
        # IDA 9.x path
        if ida_typeinf is None:
            return "ida_typeinf not available"
        return _propagate_type_ida9(struct_name)

    sid = ida_struct.get_struc_id(struct_name)
    if sid == idc.BADADDR:
        return f"Struct '{struct_name}' not found"

    # Force reanalysis by touching the struct
    sptr = ida_struct.get_struc(sid)
    tif = ida_typeinf.tinfo_t()
    if tif.get_named_type(None, struct_name):
        # Re-import the type to trigger propagation
        ida_auto.auto_wait()
        return f"Triggered type propagation for '{struct_name}'"

    return f"Type propagation requested for '{struct_name}' (manual refresh may be needed)"


@tool(category="types")
def get_type_libraries() -> str:
    """List loaded type libraries (TILs)."""

    lines = ["Type libraries:"]
    try:
        ti = ida_typeinf.get_idati()
        if ti is None:
            return "Type libraries: (unavailable)"
        # IDA 9.x: iterate loaded TILs via til_t.base[]
        count = ti.nbases
        for i in range(count):
            til = ti.base(i)
            if til:
                name = getattr(til, "name", None) or "(unnamed)"
                desc = getattr(til, "desc", "") or ""
                lines.append(f"  {name}" + (f" - {desc}" if desc else ""))
    except (AttributeError, TypeError) as e:
        log_debug(f"TIL base iteration not supported in this IDA version: {e}")
        # Fallback: just report the main TIL name
        try:
            ti = ida_typeinf.get_idati()
            name = getattr(ti, "name", "(unknown)")
            lines.append(f"  {name} (main)")
        except Exception as e:
            log_debug(f"Could not retrieve main TIL name: {e}")
            lines.append("  (enumeration not supported in this IDA version)")

    return "\n".join(lines)


@tool(category="types", mutating=True)
def import_type_from_library(
    til_name: Annotated[str, "Type library name"],
    type_name: Annotated[str, "Type name to import"],
) -> str:
    """Import a specific type from a loaded TIL."""

    tif = ida_typeinf.tinfo_t()
    if tif.get_named_type(None, type_name):
        return f"Type '{type_name}' already exists locally"

    # Try to find in the specified TIL
    til = ida_typeinf.load_til(til_name, None)
    if til is None:
        return f"Type library '{til_name}' not found"

    if tif.get_named_type(til, type_name):
        # Import to local types
        if idc is None:
            return "idc module not available"
        decl = str(tif)
        result = idc.parse_decls(f"typedef {decl} {type_name};", 0)
        if result is not None and result >= 0:
            return f"Imported '{type_name}' from '{til_name}'"

    return f"Type '{type_name}' not found in '{til_name}'"
