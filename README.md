# Rikugan (六眼)

A reverse-engineering agent for **IDA Pro** and **Binary Ninja** that integrates a multi-provider LLM directly into your analysis UI. This project was built together with my friend, Claude Code.


![alt text](assets/binja_showcase.png)


![alt text](assets/ida_showcase.png)


## Is this another MCP client?

No, Rikugan is an ***agent*** built to live inside your RE host (**IDA Pro or Binary Ninja**). It does not consume an MCP server to interact with the host database; it has its own agentic loop, context management, its own role prompt (you can check it [here](rikugan/agent/system_prompt.py)), and an in-process tool orchestration layer.

The agent loop is a generator-based turn cycle: each user message kicks off a stream→execute→repeat pipeline where the LLM response is streamed token-by-token and tool calls are intercepted and dispatched.

The results are fed back as the next turn's context. It supports automatic error recovery, mid-run user questions, plan mode for multi-step workflows, and message queuing — all without leaving the disassembler.

The agent really ***lives*** and ***breathes*** reversing.

Advantages:

- No need to switch to an external MCP client such as Claude Code
- Assistant-first, not designed to do your job (unless you ask it to)
- Extensible to many LLM providers and local installations (Ollama)
- Quick to enable — just hit Ctrl+Shift+I and the chat will appear

Also, building agents is a fascinating area of study, especially when coding alongside them.


## Features

There are 50+ tools available to the agent, covering:

- Navigation
- Code reading (decompiler, disassembly)
- Cross-references
- Strings (list, filter)
- Annotations (retype, rename, comments)
- IL reading/writing (Binary Ninja's LLIL/MLIL/HLIL) — Experimental
- Scripting to extend its capabilities (Binary Ninja Python and IDAPython)

Tool details can be found in the [ARCHITECTURE.md](ARCHITECTURE.md) document. You can use these tools to do things like:

- "Explain this function"
- "Analyze this binary and tell me what it does"
- "Batch rename all functions in this binary"
- "Try to deobfuscate this function"

Depending on the complexity, the agent may invoke subagents to assist with the analysis. It will **always** ask your permission before running scripts and will never execute the target binary.


### Exploration

Exploration mode is directly inspired by how code agents work, but applied to binaries instead of source code.

|![alt text](assets/subagents_example_1.png)|
|:--:|
|Triggering exploration mode with /explore|

When you trigger it, the main orchestrator first orients itself — it reads imports, exports, strings, and key functions to build a map of what the binary is doing. 


|![alt text](assets/subagents_example_2.png)|
|:--:|
|Logging a high-relevance finding via exploration_report|

Then, instead of doing everything in a single context, it spawns subagents and delegates focused tasks to each one: "analyze this function", "trace this data structure", "figure out what this import cluster is doing".

|![alt text](assets/subagents_example_3.png)|
|:--:|
|Orchestrator spawning subagents in parallel to tackle the binary|

Subagents run in complete isolation from the parent session. They are essentially independent instances of Rikugan with a single task and zero prior knowledge. After finishing, each one reports its findings back to the orchestrator, which synthesizes everything and continues toward your goal.

The result is a much deeper and faster analysis than a single agent could do alone — and it keeps the main context window clean.


```mermaid
stateDiagram-v2
    direction LR

    [*] --> EXPLORE : /modify or /explore

    EXPLORE --> EXPLORE : report / rename / save
    EXPLORE --> PLAN : phase_transition to plan

    PLAN --> EXECUTE : plan ready

    note right of PLAN
        /explore stops here
        read-only, no patching
    end note

    EXECUTE --> EXECUTE : patch and verify loop
    EXECUTE --> SAVE : all patches applied

    SAVE --> Done : Save All
    SAVE --> Rollback : Discard All

    Done --> [*]
    Rollback --> [*]
```

During exploration, it also renames functions when it has high confidence about what a function actually does.

### Natural Language Patches/modding

This is an feature designed to treat the entire binary as source code. The idea is, binary is code, in a certain way a project and in certain instance, it's ***text***, LLMs are great in reading text. 

We know that agentic coding is excellent in reading and editing code, so why not do the same for binaries ? the `/modify` feature is exactly that, it's like code agent now can work on the compiled binary rather the project itself!

`/modify make this maze game easy to me, make me pass thought the walls`

![alt text](assets/modify_example_01.png)

And that's it. Rikugan will start exploration mode, understand the binary's full context, and systematically apply the necessary patches to achieve your goal. Of course, this can produce issues (segfaults, crashes), but you can feed those back and it will attempt to fix them. 

This is literally ***vibe modding*** (or agentic modding for the ones who has shame to use the word "vibe").



|![alt text](assets/modify_example_02.png)|
|:--:|
|Discovered a function purpose|



|![alt text](assets/modify_example_03.png)|
|:--:|
|Present you the modification/patch plan|

Then it will proceed to the plan implementation state.

![alt text](assets/modify_example_04.png)

Done

![alt text](assets/maze_solve.gif)

### Memory

Rikugan is inspired by how Claude Code maintains its memory. Every important finding during a session is saved to `RIKUGAN.md` — a running synthesis of what was discovered across analysis sessions.

![alt text](assets/memory.png)

## Requirements

- IDA Pro 9.0+ with Hex-Rays decompiler or Binary Ninja (UI mode)
- Python 3.9+
- At least one LLM provider
- Windows, macOS, or Linux


## Installation

Clone this repository, then run the installer for your target host:

**IDA Pro (Linux / macOS):**
```bash
./install_ida.sh
```

**IDA Pro (Windows):**
```bat
install_ida.bat
```

**Binary Ninja (Linux / macOS):**
```bash
./install_binaryninja.sh
```

**Binary Ninja (Windows):**
```bat
install_binaryninja.bat
```

All scripts auto-detect the user directory for their host. If detection fails (or you have a non-standard setup), pass the path explicitly:

```bash
./install_ida.sh /path/to/ida/user/dir
install_ida.bat "C:\Users\you\AppData\Roaming\Hex-Rays\IDA Pro"
./install_binaryninja.sh /path/to/binaryninja/user/dir
install_binaryninja.bat "C:\Users\you\AppData\Roaming\Binary Ninja"
```

Installers create plugin links/junctions, install dependencies, and initialize host-specific Rikugan config directories.

### Set your API key

Rikugan has a settings dialog to configure your model of choice. Open Rikugan → click Settings → paste your key.

- IDA config: `~/.idapro/rikugan/config.json`
- Binary Ninja config: `~/.binaryninja/rikugan/config.json` (or platform-equivalent user dir)

![alt text](assets/rikugan_settings.png)

**Anthropic OAuth:** If you have Claude Code installed and authenticated, Rikugan auto-detects the OAuth token from the macOS Keychain. On other platforms, paste your API key manually or run `claude setup-token`.



## Usage

### Open the panel

IDA Pro: press **Ctrl+Shift+I** or go to **Edit → Plugins → Rikugan**.

Binary Ninja: use **Tools → Rikugan → Open Panel** or click the icon on the sidebar.

### Multi-tab chat

Each tab is an independent conversation with its own message history and context. Use the **+** button to create a new tab, or close tabs you no longer need. Tabs are tied to the current file — opening a different database starts a fresh set of tabs, and returning to a file restores its saved conversations.

### Chat export

Right-click a tab or click the **Export** button to save a conversation as Markdown. Tool calls and results are formatted with language-appropriate syntax highlighting (`c` for decompiled code, `x86asm` for disassembly, `python` for scripts, etc.).

### Script approval

The `execute_python` tool always asks for your permission before running. You see the full Python code with syntax highlighting in a scrollable preview, and can **Allow** or **Deny** each execution. The agent can never run the target binary on your machine.

![alt text](assets/approval_example.png)

### Message queuing

You can send messages while the agent is working. They appear as `[queued]` in the chat and auto-submit when the current turn finishes. Hit **Stop** to cancel the running turn and discard all queued messages.

### Quick actions

IDA Pro exposes these under right-click menus.
Binary Ninja exposes equivalent commands under **Tools → Rikugan** and address-context command menus.

| Action | Description |
|--------|-------------|
| **Send to Rikugan** | Pre-fills the input with the current selection (Ctrl+Shift+A in IDA) |
| **Explain this** | Auto-explains the current function |
| **Rename with Rikugan** | Analyzes and renames with evidence |
| **Deobfuscate with Rikugan** | Systematic deobfuscation |
| **Find vulnerabilities** | Security audit |
| **Suggest types** | Infers types from usage patterns |
| **Annotate function** | Adds comments to decompiled code |
| **Clean microcode / IL** | Identifies and NOPs junk instructions |
| **Xref analysis** | Deep cross-reference tracing |

### Skills

Skills are reusable analysis workflows. Type `/` in the input area to see available skills with autocomplete.

| Skill | Description |
|-------|-------------|
| `/malware-analysis` | Windows PE malware — kill chain, IOC extraction, MITRE ATT&CK mapping |
| `/linux-malware` | ELF malware — packing, persistence, IOC extraction |
| `/deobfuscation` | String decryption, CFF removal, opaque predicates, MBA simplification |
| `/vuln-audit` | Buffer overflows, format strings, integer issues, memory safety |
| `/driver-analysis` | Windows kernel drivers — DriverEntry, dispatch table, IOCTL handlers |
| `/ctf` | Capture-the-flag challenges — find the flag efficiently |
| `/generic-re` | General-purpose binary understanding |
| `/ida-scripting` | IDAPython API reference for writing scripts |
| `/binja-scripting` | Binary Ninja Python API reference for writing scripts |

Create custom skills in:

- IDA: `~/.idapro/rikugan/skills/<slug>/SKILL.md`
- Binary Ninja: `~/.binaryninja/rikugan/skills/<slug>/SKILL.md`

Each skill lives in its own subdirectory.

```
~/.idapro/rikugan/skills/      # or ~/.binaryninja/rikugan/skills/
  my-skill/
    SKILL.md            # required — frontmatter + prompt body
    references/         # optional — .md files appended to the prompt
      api-notes.md
```

Skill format:
```markdown
---
name: My Custom Skill
description: What it does in one line
tags: [analysis, custom]
allowed_tools: [decompile_function, rename_function]
---
Task: <instruction for the agent>

## Approach
...
```

The `allowed_tools` field is optional — when set, the agent can only use those tools while the skill is active.

### MCP Servers

Connect external MCP servers to extend Rikugan with additional tools. Create the config file at:

- IDA: `~/.idapro/rikugan/mcp.json`
- Binary Ninja: `~/.binaryninja/rikugan/mcp.json`

```json
{
  "mcpServers": {
    "binary-ninja": {
      "command": "python",
      "args": ["-m", "binaryninja_mcp"],
      "env": {},
      "enabled": true
    }
  }
}
```

MCP servers are started when the plugin loads. Their tools appear alongside built-in ones with the prefix `mcp_<server>_<tool>` — the agent sees them in the tool list and can call them like any other tool. Set `"enabled": false` to keep a server configured without starting it.

## Tools

56 tools per host, organized by category. 50 tools are shared across both hosts with identical interfaces. Each host adds 6 host-specific tools for its native intermediate representation.

### Shared tools (50)

| Category | Tools |
|----------|-------|
| **Navigation** | `get_cursor_position` `get_current_function` `jump_to` `get_name_at` `get_address_of` |
| **Functions** | `list_functions` `get_function_info` `search_functions` |
| **Strings** | `list_strings` `search_strings` `get_string_at` |
| **Database** | `list_segments` `list_imports` `list_exports` `get_binary_info` `read_bytes` |
| **Disassembly** | `read_disassembly` `read_function_disassembly` `get_instruction_info` |
| **Decompiler** | `decompile_function` `get_pseudocode` `get_decompiler_variables` |
| **Xrefs** | `xrefs_to` `xrefs_from` `function_xrefs` |
| **Annotations** | `rename_function` `rename_variable` `set_comment` `set_function_comment` `rename_address` `set_type` |
| **Types** | `create_struct` `modify_struct` `get_struct_info` `list_structs` `create_enum` `modify_enum` `get_enum_info` `list_enums` `create_typedef` `apply_struct_to_address` `apply_type_to_variable` `set_function_prototype` `import_c_header` `suggest_struct_from_accesses` `propagate_type` `get_type_libraries` `import_type_from_library` |
| **Scripting** | `execute_python` — requires user approval before each execution |

### IDA-only tools (6)

| Category | Tools |
|----------|-------|
| **Microcode** | `get_microcode` `get_microcode_block` `nop_microcode` `install_microcode_optimizer` `remove_microcode_optimizer` `list_microcode_optimizers` |

Uses Hex-Rays MMAT maturity levels. Includes `redecompile_function` to refresh output after microcode patches.

### Binary Ninja-only tools (6)

| Category | Tools |
|----------|-------|
| **IL** | `get_il` `get_il_block` `nop_instructions` `install_il_optimizer` `remove_il_optimizer` `list_il_optimizers` |

Uses native IL levels (`llil`, `mlil`, `hlil`). Includes `redecompile_function` to refresh output after IL patches.


## Conclusion

If you'd asked me last year what I thought about AI doing reverse engineering, I'd probably have said something like "Nah, impossible — it hallucinates, and reverse engineering is not something as simple as writing code." But this year I completely changed my mind when I saw what was achievable. AI is not the ChatGPT from 2023 anymore; it's something entirely different.

For that reason, I decided to invest this year in researching this topic. It's amazing what we can build with agentic coding — it's surreal how quickly I'm learning topics that I simply "didn't have time" to study before.

Rikugan is just one of many projects I've built in the last three months. The first version was built in a single night. Within two days it already supported both IDA and Binary Ninja. Within three days, it was essentially what you see here, with only minor tweaks since.

This is a work in progress with many areas for improvement. I took care to ensure this wouldn't be another AI slop project, but I'm certain there is still room to grow. I hope you use it for good. If you find bugs, have suggestions, or want quality-of-life improvements, please open an issue.

That's all — thanks.
