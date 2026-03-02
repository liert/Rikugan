---
name: IDA Scripting
description: Write and execute IDAPython scripts — full API reference included
tags: [scripting, ida, python, automation]
author: Rikugan
version: 1.0
---
Task: Help the user write IDAPython scripts. You have `execute_python` which runs code with all `ida_*` modules, `idaapi`, `idautils`, and `idc` pre-loaded.

## Guidelines

- Use `print()` for all output — it's captured and returned to you.
- Prefer the IDAPython API over raw tool calls when the task requires iteration, filtering, or complex logic that a single tool can't express.
- Always handle `None` / `BADADDR` returns (e.g., `ida_funcs.get_func()` returns `None` if no function).
- Use `ida_auto.auto_wait()` after bulk modifications to let auto-analysis settle.
- For large outputs, summarize or paginate — don't dump thousands of lines.
- Call `ida_hexrays.mark_cfunc_dirty(ea)` before re-decompiling a function you've modified.
- IDA 9+ removed `ida_struct` and `ida_enum` — use `ida_typeinf` for all type operations.

## Environment

The `execute_python` tool provides:
- `idaapi`, `idautils`, `idc` — high-level wrappers
- `ida_funcs`, `ida_name`, `ida_bytes`, `ida_segment`, `ida_typeinf`, `ida_nalt`, `ida_xref`, `ida_kernwin`, `ida_hexrays`, `ida_lines`, `ida_search`, `ida_ida`, `ida_entry`, `ida_frame`, `ida_auto`, `ida_gdl`, `ida_netnode` — low-level modules
- Full Python stdlib (except subprocess/os.exec — blocked for safety)
- `BADADDR` is available via `idaapi.BADADDR`

## Quick Reference

### Reading Data
```python
val = ida_bytes.get_byte(ea)            # uint8
val = ida_bytes.get_dword(ea)           # uint32
val = ida_bytes.get_qword(ea)           # uint64
raw = ida_bytes.get_bytes(ea, size)     # bytes
s = ida_bytes.get_strlit_contents(ea, -1, ida_nalt.STRTYPE_C)
```

### Functions
```python
for func_ea in idautils.Functions():
    name = idc.get_func_name(func_ea)

func = ida_funcs.get_func(ea)           # func_t or None
# func.start_ea, func.end_ea, func.flags
idc.add_func(ea)                        # create function
ida_name.set_name(ea, "new_name", ida_name.SN_CHECK)
```

### Decompiler (Hex-Rays)
```python
cfunc = ida_hexrays.decompile(ea)       # cfuncptr_t
pseudocode = cfunc.get_pseudocode()     # simpleline_t vector
for line in pseudocode:
    print(ida_lines.tag_remove(line.line))

# Local variables
for lvar in cfunc.get_lvars():
    print(f"{lvar.name}: {lvar.type()}")

# CTree visitor
class MyVisitor(ida_hexrays.ctree_visitor_t):
    def __init__(self):
        super().__init__(ida_hexrays.CV_FAST)
    def visit_expr(self, expr):
        if expr.op == ida_hexrays.cot_call:
            print(f"Call at {hex(expr.ea)}")
        return 0

visitor = MyVisitor()
visitor.apply_to(cfunc.body, None)
```

### Cross-References
```python
for xref in idautils.XrefsTo(ea):
    print(f"from {hex(xref.frm)}, type={xref.type}")
for xref in idautils.XrefsFrom(ea):
    print(f"to {hex(xref.to)}")
for ref in idautils.CodeRefsTo(ea, False):   # False = no flow
    print(hex(ref))
for ref in idautils.DataRefsTo(ea):
    print(hex(ref))
```

### Types (IDA 9+)
```python
# Create struct
tif = ida_typeinf.tinfo_t()
udt = ida_typeinf.udt_type_data_t()
udm = ida_typeinf.udm_t()
udm.name = "field1"
udm.type = ida_typeinf.tinfo_t(ida_typeinf.BT_INT32)
udm.offset = 0
udt.push_back(udm)
tif.create_udt(udt, ida_typeinf.BTF_STRUCT)
tif.set_named_type(None, "MyStruct")

# Apply type to address
ida_typeinf.apply_tinfo(ea, tif, ida_typeinf.TINFO_DEFINITE)

# Parse C declaration
ida_typeinf.apply_cdecl(None, ea, "int __cdecl func(int a, char *b)")

# Create enum
edt = ida_typeinf.enum_type_data_t()
edm = ida_typeinf.edm_t()
edm.name = "VAL_A"; edm.value = 0
edt.push_back(edm)
tif2 = ida_typeinf.tinfo_t()
tif2.create_enum(edt)
tif2.set_named_type(None, "MyEnum")
```

### Segments & Strings
```python
for seg_ea in idautils.Segments():
    seg = ida_segment.getseg(seg_ea)
    print(f"{ida_segment.get_segm_name(seg)}: {hex(seg.start_ea)}-{hex(seg.end_ea)}")

for s in idautils.Strings():
    refs = list(idautils.DataRefsTo(s.ea))
    print(f"'{s}' @ {hex(s.ea)}, refs={len(refs)}")
```

### Names & Comments
```python
for ea, name in idautils.Names():
    print(f"{hex(ea)}: {name}")

ida_name.set_name(ea, "my_label", ida_name.SN_CHECK)
idc.set_cmt(ea, "note", 0)              # 0=regular, 1=repeatable
idc.set_func_cmt(ea, "description", 0)
```

### Search
```python
# IDA 9+
ea = ida_bytes.find_bytes(start_ea, "48 8B ?? ?? 90", 0)

# Pattern search loop
ea = start_ea
while ea != idaapi.BADADDR:
    ea = ida_search.find_binary(ea, idaapi.BADADDR, "E8 ?? ?? ?? ??", 16,
                                 ida_search.SEARCH_DOWN | ida_search.SEARCH_NEXT)
    if ea != idaapi.BADADDR:
        print(hex(ea))
```

### Patching
```python
ida_bytes.patch_byte(ea, 0x90)           # NOP
ida_bytes.patch_bytes(ea, b"\x90" * 5)   # NOP sled
ida_bytes.patch_dword(ea, 0)
```

### UI
```python
ea = ida_kernwin.get_screen_ea()
ida_kernwin.jumpto(target_ea)
ida_kernwin.msg("Info message\n")
name = ida_kernwin.ask_str("default", 0, "Enter name:")
choice = ida_kernwin.ask_yn(1, "Sure?")
ida_kernwin.show_wait_box("Processing...")
# ... work ...
ida_kernwin.hide_wait_box()
```

### Control Flow Graph
```python
func = ida_funcs.get_func(ea)
fc = ida_gdl.FlowChart(func)
for block in fc:
    print(f"Block {hex(block.start_ea)}-{hex(block.end_ea)}")
    for succ in block.succs():
        print(f"  -> {hex(succ.start_ea)}")
```

### Common Patterns
```python
# Find all callers of a function
target = ida_name.get_name_ea(idaapi.BADADDR, "malloc")
if target != idaapi.BADADDR:
    for ref in idautils.CodeRefsTo(target, False):
        func = ida_funcs.get_func(ref)
        if func:
            print(f"Called from {idc.get_func_name(func.start_ea)} @ {hex(ref)}")

# Batch decompile
for func_ea in idautils.Functions():
    try:
        cfunc = ida_hexrays.decompile(func_ea)
        text = "\n".join(ida_lines.tag_remove(l.line) for l in cfunc.get_pseudocode())
    except ida_hexrays.DecompilationFailure:
        pass

# Persistent storage via netnodes
node = ida_netnode.netnode("$my_data", 0, True)
node.hashset("key", "value")
val = node.hashstr("key")
```

## Important Notes

- `BADADDR` = `0xFFFFFFFF` (32-bit) or `0xFFFFFFFFFFFFFFFF` (64-bit) — always compare against it.
- `ida_hexrays.decompile()` can raise `DecompilationFailure` — always wrap in try/except.
- IDA 9 removed `ida_struct`/`ida_enum` — use `ida_typeinf` with `udt_type_data_t`/`udm_t`/`enum_type_data_t`/`edm_t`.
- `ida_bytes.get_strlit_contents()` returns `bytes`, not `str` — decode with `.decode('utf-8', errors='replace')`.
- Process execution (subprocess, os.system, etc.) is blocked. Static analysis only.
