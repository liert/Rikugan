# AGENTS.md — Rikugan Developer Guide

## Project Overview

Rikugan (六眼) is a multi-host reverse-engineering agent plugin that integrates an LLM-powered assistant directly inside **IDA Pro** and **Binary Ninja**. It has its own agentic loop, in-process tool orchestration, streaming UI, multi-tab chat, session persistence, MCP client support, and host-native tool sets.

## Directory Structure

```
rikugan/
├── agent/                    # Agent loop & prompt logic (host-agnostic)
│   ├── loop.py               # AgentLoop: generator-based turn cycle
│   ├── turn.py               # TurnEvent / TurnEventType definitions
│   ├── context_window.py     # Context-window management
│   ├── plan_mode.py          # Plan-mode step orchestration
│   ├── system_prompt.py      # build_system_prompt() dispatcher
│   └── prompts/              # Host-specific system prompts
│       ├── base.py           # Shared prompt sections (discipline, renaming, etc.)
│       ├── ida.py            # IDA Pro base prompt
│       └── binja.py          # Binary Ninja base prompt
│
├── core/                     # Shared infrastructure (host-agnostic)
│   ├── config.py             # RikuganConfig — settings, provider config, paths
│   ├── constants.py          # Constants (CONFIG_DIR_NAME, etc.)
│   ├── errors.py             # Exception hierarchy (ToolError, AgentError, etc.)
│   ├── host.py               # Host context (BV, address, navigate callback)
│   ├── logging.py            # Logging utilities
│   ├── thread_safety.py      # Thread-safety helpers (@idasync, etc.)
│   └── types.py              # Core data types (Message, ToolCall, StreamChunk, etc.)
│
├── ida/                      # IDA Pro host package
│   ├── tools/
│   │   └── registry.py       # IDA create_default_registry() — imports rikugan.tools.*
│   └── ui/
│       ├── panel.py          # IDA PluginForm wrapper
│       ├── actions.py        # IDA UI hooks & context menu actions
│       └── session_controller.py  # IDA SessionController
│
├── binja/                    # Binary Ninja host package
│   ├── tools/
│   │   ├── registry.py       # BN create_default_registry() — imports rikugan.binja.tools.*
│   │   ├── common.py         # BN shared helpers (get_bv, get_function_at, etc.)
│   │   ├── navigation.py     # Navigation tools
│   │   ├── functions.py      # Function listing/search tools
│   │   ├── strings.py        # String tools
│   │   ├── database.py       # Segments, imports, exports, binary info
│   │   ├── disassembly.py    # Disassembly tools
│   │   ├── decompiler.py     # Decompiler/HLIL tools
│   │   ├── xrefs.py          # Cross-reference tools
│   │   ├── annotations.py    # Rename/comment/set_type tools
│   │   ├── types_tools.py    # Struct/enum/typedef tools
│   │   ├── il.py             # IL tools (get_il, nop_instructions, IL optimizers)
│   │   └── scripting.py      # execute_python tool
│   └── ui/
│       ├── panel.py          # BN QWidget panel
│       ├── actions.py        # BN action handlers
│       └── session_controller.py  # BN BinaryNinjaSessionController
│
├── tools/                    # IDA tool implementations
│   ├── base.py               # @tool decorator, ToolDefinition, JSON schema generation
│   ├── registry.py           # Shared ToolRegistry class
│   ├── navigation.py         # IDA navigation tools
│   ├── functions.py          # IDA function tools
│   ├── strings.py            # IDA string tools
│   ├── database.py           # IDA database tools (segments, imports, exports)
│   ├── disassembly.py        # IDA disassembly tools
│   ├── decompiler.py         # IDA decompiler tools (Hex-Rays)
│   ├── xrefs.py              # IDA xref tools
│   ├── annotations.py        # IDA annotation tools (rename, comment, set type)
│   ├── types_tools.py        # IDA type tools (structs, enums, typedefs, TILs)
│   ├── microcode.py          # IDA Hex-Rays microcode tools
│   ├── microcode_format.py   # Microcode formatting helpers
│   ├── microcode_optim.py    # Microcode optimizer framework
│   └── scripting.py          # IDA execute_python tool
│
├── tools_bn/                 # Backward-compat shims → rikugan.binja.tools.*
├── hosts/                    # Backward-compat shims → rikugan.ida.ui.* / rikugan.binja.ui.*
│
├── providers/                # LLM provider integrations (host-agnostic)
│   ├── base.py               # LLMProvider ABC
│   ├── registry.py           # ProviderRegistry
│   ├── anthropic_provider.py # Claude (Anthropic) — supports OAuth auto-detection
│   ├── openai_provider.py    # OpenAI
│   ├── gemini_provider.py    # Google Gemini
│   ├── ollama_provider.py    # Ollama (local)
│   └── openai_compat.py      # OpenAI-compatible endpoints
│
├── mcp/                      # MCP client (host-agnostic)
│   ├── config.py             # MCP server config loader
│   ├── client.py             # MCP protocol client
│   ├── bridge.py             # MCP ↔ ToolRegistry bridge
│   ├── manager.py            # MCPManager — lifecycle management
│   └── protocol.py           # MCP JSON-RPC protocol types
│
├── skills/                   # Skill system (host-agnostic)
│   ├── registry.py           # SkillRegistry — discovery & loading
│   ├── loader.py             # SKILL.md frontmatter parser
│   └── builtins/             # 9 built-in analysis skills
│       ├── malware-analysis/
│       ├── linux-malware/
│       ├── deobfuscation/
│       ├── vuln-audit/
│       ├── driver-analysis/
│       ├── ctf/
│       ├── generic-re/
│       ├── ida-scripting/    # IDAPython API skill with full reference
│       └── binja-scripting/  # Binary Ninja Python API skill with full reference
│
├── state/                    # Session persistence (host-agnostic)
│   ├── session.py            # SessionState — message history, token tracking
│   └── history.py            # SessionHistory — auto-save/restore per file
│
└── ui/                       # Shared UI widgets (Qt, host-agnostic)
    ├── panel_core.py         # PanelCore — multi-tab chat, export, event routing
    ├── session_controller_base.py  # SessionControllerBase — multi-session orchestration
    ├── chat_view.py          # Chat message display widget (queued message support)
    ├── input_area.py         # User input text area with skill autocomplete
    ├── context_bar.py        # Binary context status bar
    ├── message_widgets.py    # Message bubble widgets (tool calls, approval dialogs)
    ├── markdown.py           # Markdown rendering for assistant messages
    ├── plan_view.py          # Plan-mode UI
    ├── settings_dialog.py    # Settings dialog (screen-aware sizing)
    ├── styles.py             # Qt stylesheet constants
    └── qt_compat.py          # Qt compatibility layer (PyQt5/PySide6)
```

Entry points (root directory):
- **IDA Pro**: `rikugan_plugin.py` — `PLUGIN_ENTRY()` → `RikuganPlugin` → `RikuganPlugmod`
- **Binary Ninja**: `rikugan_binaryninja.py` — registers sidebar widget + commands at import time

## How the Agent Loop Works

The agent uses a **generator-based turn cycle** (`rikugan/agent/loop.py`):

```
User message → build system prompt → stream LLM response → intercept tool calls → execute tools → feed results back → repeat
```

1. **User sends a message** — the UI calls `SessionControllerBase.start_agent(user_message)`
2. **System prompt is built** — `build_system_prompt()` selects the host-specific base prompt and appends binary context, current position, available tools, and active skills
3. **AgentLoop.run()** is a generator that yields `TurnEvent` objects to the UI:
   - `TEXT_DELTA` — streaming token from the LLM
   - `TOOL_CALL` — LLM wants to call a tool
   - `TOOL_RESULT` — tool execution result
   - `TURN_COMPLETE` — LLM finished a turn
   - `ERROR` — something went wrong
4. **Tool calls** are intercepted from the LLM stream, dispatched via `ToolRegistry.execute()`, and the results are appended to the conversation as the next turn's context
5. **The loop repeats** until the LLM produces a response with no tool calls, or the user cancels
6. **BackgroundAgentRunner** wraps the generator in a background thread; IDA API calls are marshalled to the main thread via `@idasync`

Plan mode uses the same loop but adds a planning step: the LLM first generates a numbered plan, then executes each step in sequence.

## Multi-Tab Chat & Session Persistence

- Each tab is an independent `SessionState` with its own message history and token tracking
- `SessionControllerBase` manages a dict of `_sessions: Dict[str, SessionState]` keyed by tab ID
- `PanelCore` uses a `QTabWidget` with closable tabs and a "+" button for new tabs
- Sessions are auto-saved per file (IDB/BNDB path) and restored when re-opening the same file
- Opening a different file resets all tabs and attempts to restore that file's saved sessions

## Script Approval

The `execute_python` tool always requires explicit user approval before execution:
- The agent proposes Python code → a syntax-highlighted preview is shown in the chat
- The user clicks **Allow** or **Deny**
- Blocked patterns (subprocess, os.system, etc.) are rejected before reaching the approval step

## Message Queuing

Users can send follow-up messages while the agent is working. Queued messages appear as `[queued]` in the chat and auto-submit when the current turn finishes. Cancelling discards all queued messages.

## How to Add New Tools

### 1. Create a tool function with the `@tool` decorator

```python
from typing import Annotated
from rikugan.tools.base import tool

@tool(category="navigation")
def jump_to(
    address: Annotated[str, "Target address (hex string, e.g. '0x401000')"],
) -> str:
    """Jump to the specified address."""
    ea = parse_addr(address)
    # ...
    return f"Jumped to 0x{ea:x}"
```

The `@tool` decorator:
- Generates a `ToolDefinition` with JSON schema from the function signature
- Uses `typing.Annotated` metadata for parameter descriptions
- Wraps the handler with `@idasync` for thread-safe IDA API access
- Attaches the definition as `func._tool_definition`

Optional `@tool` parameters:
- `category` — grouping (e.g., `"navigation"`, `"decompiler"`, `"microcode"`, `"il"`)
- `requires_decompiler` — marks the tool as needing decompiler/Hex-Rays availability
- `mutating` — marks the tool as modifying the database (used for `execute_python` approval)

### 2. Register in the host's registry

**For IDA** — add the module import to `rikugan/ida/tools/registry.py`:
```python
from rikugan.tools import my_new_module
_TOOL_MODULES = (..., my_new_module)
```

**For Binary Ninja** — add the module import to `rikugan/binja/tools/registry.py`:
```python
from rikugan.binja.tools import my_new_module
_TOOL_MODULES = (..., my_new_module)
```

The registry calls `register_module()` on each module, which discovers all `@tool`-decorated functions.

## How to Add a New Host

1. Create `rikugan/<host>/` with `tools/` and `ui/` sub-packages
2. Implement tool modules under `rikugan/<host>/tools/` — use `from rikugan.tools.base import tool`
3. Create `rikugan/<host>/tools/registry.py` with a `create_default_registry()` factory
4. Subclass `SessionControllerBase` in `rikugan/<host>/ui/session_controller.py`
5. Create a panel widget in `rikugan/<host>/ui/panel.py` — embed the shared `PanelCore` widget
6. Add a host-specific prompt in `rikugan/agent/prompts/<host>.py` and register it in `system_prompt.py`'s `_HOST_PROMPTS` dict
7. Create an entry point script (e.g., `rikugan_<host>.py`) that bootstraps the plugin

## How to Add a New Skill

Skills are Markdown files with YAML frontmatter:

```
rikugan/skills/builtins/<slug>/
  SKILL.md            # Required — frontmatter + prompt body
  references/         # Optional — .md files auto-appended to prompt
    api-notes.md
```

Skill format:
```markdown
---
name: My Skill
description: What it does in one line
tags: [analysis, custom]
allowed_tools: [decompile_function, rename_function]
---
Task: <instruction for the agent>
```

Users can also create custom skills in their host config directory (`~/.idapro/rikugan/skills/` or `~/.binaryninja/rikugan/skills/`).

## Import Conventions

- **Cross-package imports** use absolute paths: `from rikugan.tools.base import tool`
- **Within the same package** use absolute imports: `from rikugan.binja.tools.common import get_bv`
- **IDA tool modules** (`rikugan/tools/*.py`) use relative imports within `rikugan.tools`
- **Host API modules** (ida_*, binaryninja) are imported via `importlib.import_module()` inside `try/except ImportError` blocks to avoid crashes when loaded in the wrong host
- **Backward-compat shims** in `rikugan/tools_bn/` and `rikugan/hosts/` re-export from canonical locations

## System Prompt Structure

System prompts are built from **shared sections** + **host-specific content**:

```
rikugan/agent/prompts/
├── base.py     # Shared sections:
│               #   DISCIPLINE_SECTION  — "Do exactly what was asked"
│               #   RENAMING_SECTION    — Renaming/retyping guidelines
│               #   ANALYSIS_SECTION    — Analysis approach
│               #   SAFETY_SECTION      — Safety guidelines
│               #   TOKEN_EFFICIENCY_SECTION — Prefer search over listing
│               #   CLOSING_SECTION     — Final reminders
├── ida.py      # IDA_BASE_PROMPT: IDA intro + IDA tool usage + shared sections
└── binja.py    # BINJA_BASE_PROMPT: BN intro + BN tool usage + shared sections
```

`build_system_prompt()` in `system_prompt.py` selects the correct base prompt by host name, then appends runtime context (binary info, cursor position, tool list, active skills).

## Key Files

| File | Role |
|------|------|
| `rikugan/agent/loop.py` | Core agent loop — generator-based turn cycle |
| `rikugan/tools/base.py` | `@tool` decorator, `ToolDefinition`, JSON schema generation |
| `rikugan/tools/registry.py` | `ToolRegistry` — registration, dispatch, argument coercion |
| `rikugan/ui/session_controller_base.py` | `SessionControllerBase` — multi-session orchestration |
| `rikugan/ui/panel_core.py` | `PanelCore` — multi-tab chat, export, event routing |
| `rikugan/ui/chat_view.py` | `ChatView` — message display, queued messages |
| `rikugan/ui/message_widgets.py` | Message widgets including approval dialog |
| `rikugan/core/config.py` | `RikuganConfig` — all settings, provider config, host paths |
| `rikugan/core/host.py` | Host context singleton (BinaryView, address, navigate callback) |
| `rikugan/core/thread_safety.py` | `@idasync` decorator for main-thread marshalling |
| `rikugan/providers/base.py` | `LLMProvider` ABC — interface for all LLM providers |
| `rikugan/mcp/manager.py` | `MCPManager` — starts MCP servers, bridges tools into registry |
| `rikugan/skills/registry.py` | `SkillRegistry` — discovers and loads SKILL.md files |
| `rikugan/state/session.py` | `SessionState` — message history, token usage tracking |
| `rikugan/state/history.py` | `SessionHistory` — auto-save/restore per file |
| `rikugan_plugin.py` | IDA Pro plugin entry point |
| `rikugan_binaryninja.py` | Binary Ninja plugin entry point |

## IDA API Notes

IDA tool modules use `importlib.import_module()` for all `ida_*` imports to avoid Shiboken UAF crashes. Key considerations:

- **IDA 9.x** removed `ida_struct` and `ida_enum` — use `ida_typeinf` with `udt_type_data_t`/`udm_t`/`enum_type_data_t`/`edm_t`
- **Segment permissions** use raw bit flags on `seg.perm` (4=R, 2=W, 1=X), not named constants
- **`idautils.Entries()`** yields 4 values: `(index, ordinal, ea, name)`
- **`ida_hexrays.decompile()`** can raise `DecompilationFailure` — always wrap in try/except
- All IDA API calls must run on the main thread — the `@idasync` wrapper handles this automatically
