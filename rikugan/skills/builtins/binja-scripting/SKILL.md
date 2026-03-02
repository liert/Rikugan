---
name: Binary Ninja Scripting
description: Write and execute Binary Ninja Python scripts — full API reference included
tags: [scripting, binja, python, automation]
author: Rikugan
version: 1.0
---
Task: Help the user write Binary Ninja Python scripts. You have `execute_python` which runs code with `bv` (the current BinaryView), `binaryninja` module, and `current_address` pre-loaded.

## Guidelines

- Use `print()` for all output — it's captured and returned to you.
- Prefer the Binary Ninja Python API over raw tool calls when the task requires iteration, filtering, or complex logic that a single tool can't express.
- Always handle `None` returns (e.g., `bv.get_function_at()` returns `None` if no function at that address).
- Use `bv.update_analysis_and_wait()` after bulk modifications (defining types, creating functions).
- For large outputs, summarize or paginate — don't dump thousands of lines.
- User types (`define_user_*`, `add_user_*`) persist to the database; auto types may be overwritten by analysis.
- When modifying the database (renaming, retyping, creating structs), prefer `_user_` methods.

## Environment

The `execute_python` tool provides:
- `bv` — the active `BinaryView`
- `binaryninja` — the full `binaryninja` module
- `binaryninjaui` — UI module (if available)
- `current_address` — cursor address (int, 0 if unavailable)
- Full Python stdlib (except subprocess/os.exec — blocked for safety)

## Quick Reference

### Reading Data
```python
data = bv.read(addr, length)       # raw bytes
val = bv.read32(addr)              # 32-bit int
ptr = bv.read_pointer(addr)        # pointer-sized int
strings = bv.get_strings()         # all StringReference objects
s = bv.get_string_at(addr)         # single string
```

### Functions
```python
func = bv.get_function_at(addr)           # exact start
funcs = bv.get_functions_containing(addr) # containing addr
funcs = bv.get_functions_by_name("main")  # by name (list)
bv.add_user_function(addr)                # create function
func.name = "NewName"                     # rename
func.type = Type.function(ret, params)    # retype
func.set_comment_at(addr, "note")         # comment
```

### IL Access
```python
# Three levels: llil < mlil < hlil (prefer hlil for analysis)
for inst in func.hlil.instructions:
    print(f"{hex(inst.address)}: {inst}")

# SSA form for data flow
defn = func.hlil.ssa_form.get_ssa_var_definition(ssa_var)
uses = func.hlil.ssa_form.get_ssa_var_uses(ssa_var)

# Navigate between levels
llil_inst = func.get_llil_at(addr)
hlil_from_llil = llil_inst.hlil
```

### Cross-References
```python
refs = bv.get_code_refs(addr)        # code refs TO addr
refs = bv.get_data_refs(addr)        # data refs TO addr
refs = bv.get_code_refs_from(addr)   # code refs FROM addr
callers = func.callers               # calling functions
callees = func.callees               # called functions
```

### Types
```python
from binaryninja import Type, StructureBuilder

# Primitives
Type.int(4)                          # int32
Type.pointer(bv.arch, Type.char())   # char*
Type.array(Type.int(1), 256)         # uint8_t[256]

# Struct
s = StructureBuilder.create()
s.append(Type.int(4), "field_a")
s.append(Type.pointer(bv.arch, Type.char()), "name")
bv.define_user_type("MyStruct", Type.structure_type(s))

# Apply to data
ntr = Type.named_type_from_registered_type(bv, "MyStruct")
bv.define_user_data_var(addr, ntr)

# Enum
Type.enumeration(members=[("VAL_A", 0), ("VAL_B", 1)])

# Parse C
t, name = bv.parse_type_string("uint64_t*")
```

### Symbols
```python
from binaryninja import Symbol, SymbolType
sym = Symbol(SymbolType.DataSymbol, addr, "g_config")
bv.define_user_symbol(sym)
bv.get_symbol_at(addr)
bv.get_symbols_by_name("main")
```

### Segments & Sections
```python
for seg in bv.segments:
    print(f"{hex(seg.start)}-{hex(seg.end)}")
for name, sec in bv.sections.items():
    print(f"{name}: {hex(sec.start)}-{hex(sec.end)}")
bv.get_segment_at(addr)
bv.get_sections_at(addr)
```

### UI Interaction
```python
from binaryninja.interaction import (
    show_message_box, show_plain_text_report,
    show_markdown_report, show_html_report,
    get_text_line_input, get_int_input,
    get_choice_input, get_address_input,
)
# Reports are the best way to show formatted output
show_markdown_report("Title", "# Results\n- item 1\n- item 2")
show_plain_text_report("Title", large_text_output)
```

### Common Patterns
```python
# Find functions calling a specific import
target = bv.get_functions_by_name("CreateFileW")
if target:
    for caller in target[0].callers:
        print(f"{hex(caller.start)}: {caller.name}")

# Search for byte pattern
addr = bv.find_next_data(bv.start, b"\x48\x89\x5C\x24")

# Iterate all data variables
for addr, dv in bv.data_vars.items():
    print(f"{hex(addr)}: {dv.type} = {dv.name or '(unnamed)'}")

# Bulk rename with evidence
for func in bv.functions:
    if func.name.startswith("sub_"):
        hlil = func.hlil_if_available
        if hlil:
            for inst in hlil.instructions:
                # ... analyze and rename based on evidence
                pass

# Background task for long operations
from binaryninja import BackgroundTaskThread
class MyTask(BackgroundTaskThread):
    def __init__(self, bv):
        super().__init__("Processing...", can_cancel=True)
        self.bv = bv
    def run(self):
        for i, func in enumerate(self.bv.functions):
            if self.cancelled:
                break
            self.progress = f"{func.name} ({i}/{len(self.bv.functions)})"
```

## Important Notes

- `func.hlil_if_available` returns `None` if HLIL hasn't been generated yet — safer than `func.hlil` which may block.
- `bv.functions` returns a snapshot list — safe to iterate while modifying.
- Use `Type.named_type_from_registered_type(bv, name)` to reference a type you've defined, not the raw Type object.
- `_user_` methods persist; `_auto_` methods may be overwritten by re-analysis.
- Process execution (subprocess, os.system, etc.) is blocked. Static analysis only.
