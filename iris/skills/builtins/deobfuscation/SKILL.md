---
name: Deobfuscation
description: Systematic deobfuscation — string decryption, CFF removal, opaque predicates, MBA simplification, microcode cleaning
tags: [deobfuscation, obfuscation, cff, mba, opaque-predicates]
---
# Deobfuscation Mode

Deobfuscate fully first. Analyze afterward.
NEVER analyze obfuscated code and draw conclusions — it misleads.
An if-statement that always takes one branch is noise. A loop updating a state variable is a dispatcher. MBA expressions are noise wrapping simple values.

## Mandatory Order of Operations

### Phase 1: String Decryption (do first — unlocks context for all other phases)

Strings are the fastest path to understanding.

1. Use `search_strings` and `list_strings` to check for readable strings
2. If very few readable strings in a large binary → strings are encrypted
3. Look for the string decode stub: a small function called before every string use
4. Decompile it with `decompile_function`, identify the algorithm (XOR, RC4, custom)
5. Use `xrefs_to` on the decode function to find all encrypted string call sites
6. Decrypted strings give you: C2 addresses, file paths, registry keys, API names

**RC4 hunting shortcut:** When you find RC4 S-box constants, use xrefs_to
on the constant's address → finds KSA → decompile → xrefs_to → finds
the decrypt wrapper. Do NOT search for KSA byte-swap hex pattern — too
many false positives.

### Phase 2: Structural Deobfuscation (CFF + Opaque Predicates)

**Control Flow Flattening (CFF):**
Red flags: a switch with all cases assigning the same variable, a loop
updating a state variable, cyclomatic complexity > 40 with few behaviors.

- Read the microcode with `get_microcode` to see the raw control flow
- Use `install_microcode_optimizer` to write a custom optimizer that:
  - Identifies the dispatcher variable and switch
  - NOPs the dispatcher overhead
  - Redecompile with `redecompile_function`

**Opaque Predicates:**
Red flags: `x * (x-1) % 2 == 0` (always true), constant comparisons
with computed values that always evaluate one way.

- Use `get_microcode` to identify them, `nop_microcode` to remove dead branches
- Run after CFF removal — CFF removal often exposes hidden opaque predicates

### Phase 3: Expression Deobfuscation (MBA + Arithmetic Encoding)

**Mixed Boolean-Arithmetic (MBA):**
Red flags: `(x ^ y) + 2*(x & y)` equals `x + y`, complex expressions
for simple operations.

- Look for these in decompiled output after structural deobfuscation
- Use `install_microcode_optimizer` to simplify recognized MBA patterns
- Redecompile to verify

**Arithmetic Encoding:**
- Instruction substitution: addition via SUB of negated value, XOR via AND+OR combinations
- Often resolved by the decompiler after CFF/opaque predicate removal
- If still present: write a microcode optimizer to constant-fold

### Phase 4: VM Boundary (if detected)

VM virtualization is NOT automatically deobfuscatable.
1. Identify the VM entry point, bytecode buffer, handler table
2. Document: entry address, bytecode location, handler table address, handler count
3. Focus analysis on non-virtualized code paths
4. Recommend specialized VM lifting tooling to the user

### Phase 5: Post-Deobfuscation

After all phases complete:
- Redecompile all previously analyzed functions in their cleaned form
- Proceed with normal analysis (malware kill chain, CTF solve, etc.)
- The code should now be readable — if it isn't, check if more obfuscation layers remain

## Critical Rules

- If unsure whether code is obfuscated: decompile it and read the microcode. Spend 1 tool call to know for certain rather than 20 analyzing noise.
- String decryption ALWAYS comes first — it unlocks context for everything else.
- After each deobfuscation step, redecompile to verify improvement.
- Use microcode tools (`get_microcode`, `nop_microcode`, `install_microcode_optimizer`, `redecompile_function`) — they give you direct control over the decompiler pipeline.
- Batch independent deobfuscation calls: if 5 functions need CFF unflattening, launch them in parallel.
