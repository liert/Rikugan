---
name: General Reverse Engineering
description: General-purpose binary analysis — understand functionality, architecture, and behavior
tags: [analysis, reverse-engineering, general]
---
Task: General Reverse Engineering. You are analyzing a binary to understand its functionality, architecture, or behavior. No assumption about maliciousness.

## Approach

Build a mental map of the binary's structure. Start at the entry point or user-specified function. Name functions as you understand them — each rename makes the next function easier to read. Focus on what the user is interested in, not exhaustive coverage.

## Workflow

1. `get_binary_info` — format, architecture, size, function count
2. `list_imports` + `list_exports` — understand the binary's interface
3. Start at the function of interest (or entry if exploring)
4. `decompile_function` → understand → `rename_function` / `rename_variable` → follow call chains
5. Use `xrefs_to` and `xrefs_from` to trace data and code references
6. Build up a picture of the binary's modules, data structures, and control flow

## Domain-Specific Tips

**Libraries/frameworks:** Focus on exported functions and their calling conventions. Use `list_exports` to map the public API.

**Drivers/kernel modules:** Identify dispatch routines, IOCTL handlers, initialization. Consider using `/driver-analysis` for Windows drivers.

**Proprietary formats:** Trace the parsing code. Use `create_struct` and `suggest_struct_from_accesses` to reconstruct data structures. Apply with `apply_struct_to_address`.

**Firmware/embedded:** Check for known library signatures in function prologues. Map memory-mapped I/O regions via `list_segments`.

## Renaming Strategy

- Before renaming, form a hypothesis from: decompiled code + xrefs + string references
- Rename in semantic batches: all network functions together, all crypto together
- After renaming a batch: re-decompile to verify the renamed code reads correctly
- Use `set_comment` and `set_function_comment` to document non-obvious logic

## Output

Deliver what the user asks for:
- Function summaries with addresses
- Architectural overview
- Data structure definitions (C-style)
- Specific answers about behavior
