# AGENTS.md — IRIS Developer Guide

## Project Overview

IRIS (Intelligent Reverse-engineering Integrated System) is a multi-host reverse-engineering agent plugin that integrates an LLM-powered assistant directly inside IDA Pro and Binary Ninja. It has its own agentic loop, in-process tool orchestration, streaming UI, MCP client support, and host-native tool sets.

## Directory Structure

```
iris/
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
│   ├── config.py             # IRISConfig — settings, provider config, paths
│   ├── errors.py             # Exception hierarchy (ToolError, AgentError, etc.)
│   ├── host.py               # Host context (BV, address, navigate callback)
│   ├── logging.py            # Logging utilities
│   ├── thread_safety.py      # Thread-safety helpers (@idasync, etc.)
│   └── types.py              # Core data types (Message, ToolCall, StreamChunk, etc.)
│
├── ida/                      # IDA Pro host package (canonical)
│   ├── tools/
│   │   └── registry.py       # IDA create_default_registry() — imports from iris.tools.*
│   └── ui/
│       ├── panel.py          # IDA PluginForm wrapper
│       ├── actions.py        # IDA UI hooks & context menu integration
│       └── session_controller.py  # IDA SessionController
│
├── binja/                    # Binary Ninja host package (canonical)
│   ├── tools/
│   │   ├── registry.py       # BN create_default_registry() — imports from iris.binja.tools.*
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
├── tools/                    # IDA tool implementations (shared tool interface)
│   ├── base.py               # @tool decorator, ToolDefinition, JSON schema generation
│   ├── registry.py           # Shared ToolRegistry class
│   ├── navigation.py         # IDA navigation tools
│   ├── functions.py          # IDA function tools
│   ├── strings.py            # IDA string tools
│   ├── database.py           # IDA database tools
│   ├── disassembly.py        # IDA disassembly tools
│   ├── decompiler.py         # IDA decompiler tools
│   ├── xrefs.py              # IDA xref tools
│   ├── annotations.py        # IDA annotation tools
│   ├── types_tools.py        # IDA type tools
│   ├── microcode.py          # IDA Hex-Rays microcode tools
│   ├── microcode_format.py   # Microcode formatting helpers
│   ├── microcode_optim.py    # Microcode optimizer framework
│   └── scripting.py          # IDA execute_python tool
│
├── tools_bn/                 # Backward-compat shims → iris.binja.tools.*
├── hosts/                    # Backward-compat shims → iris.ida.ui.* / iris.binja.ui.*
│
├── providers/                # LLM provider integrations (host-agnostic)
│   ├── base.py               # LLMProvider ABC
│   ├── registry.py           # ProviderRegistry
│   ├── anthropic_provider.py # Claude (Anthropic)
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
│   └── builtins/             # 7 built-in analysis skills
│
├── state/                    # Session persistence (host-agnostic)
│   ├── session.py            # SessionState — message history, token tracking
│   └── history.py            # SessionHistory — auto-save/restore
│
└── ui/                       # Shared UI widgets (Qt, host-agnostic)
    ├── panel_core.py         # PanelCore — shared panel logic
    ├── session_controller_base.py  # SessionControllerBase — host-agnostic orchestrator
    ├── chat_view.py          # Chat message display widget
    ├── input_area.py         # User input text area
    ├── context_bar.py        # Binary context status bar
    ├── message_widgets.py    # Individual message bubble widgets
    ├── markdown.py           # Markdown rendering for assistant messages
    ├── plan_view.py          # Plan-mode UI
    ├── settings_dialog.py    # Settings dialog
    ├── styles.py             # Qt stylesheet constants
    └── qt_compat.py          # Qt compatibility layer
```

Entry points:
- **IDA Pro**: `iris_plugin.py` — `PLUGIN_ENTRY()` → `IRISPlugin` → `IRISPlugmod`
- **Binary Ninja**: `iris_binaryninja.py` — registers sidebar + commands at import time

## How the Agent Loop Works

The agent uses a **generator-based turn cycle** (`iris/agent/loop.py`):

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

## How to Add New Tools

### 1. Create a tool function with the `@tool` decorator

```python
from typing import Annotated
from iris.tools.base import tool

@tool(category="navigation", description="Jump to an address in the disassembly view.")
def jump_to(
    address: Annotated[int, "Target address (hex or decimal)"],
) -> str:
    # Implementation here
    return f"Jumped to {hex(address)}"
```

The `@tool` decorator:
- Generates a `ToolDefinition` with JSON schema from the function signature
- Uses `typing.Annotated` metadata for parameter descriptions
- Attaches the definition as `func._tool_definition`

Optional `@tool` parameters:
- `category` — grouping for the tool (e.g., `"navigation"`, `"decompiler"`, `"il"`)
- `requires_decompiler` — marks the tool as needing decompiler availability
- `mutating` — marks the tool as modifying the database

### 2. Register in the host's registry

**For IDA** — add the module import to `iris/ida/tools/registry.py`:
```python
from iris.tools import my_new_module
# ...
_TOOL_MODULES = (..., my_new_module)
```

**For Binary Ninja** — add the module import to `iris/binja/tools/registry.py`:
```python
from iris.binja.tools import my_new_module
# ...
_TOOL_MODULES = (..., my_new_module)
```

The registry calls `register_module()` on each module, which discovers all `@tool`-decorated functions.

## How to Add a New Host

1. Create `iris/<host>/` with `tools/` and `ui/` sub-packages
2. Implement tool modules under `iris/<host>/tools/` — use `from iris.tools.base import tool` for the decorator
3. Create `iris/<host>/tools/registry.py` with a `create_default_registry()` factory
4. Subclass `SessionControllerBase` in `iris/<host>/ui/session_controller.py` — pass your registry factory and host name
5. Create a panel widget in `iris/<host>/ui/panel.py` — embed the shared `PanelCore` widget
6. Add a host-specific prompt in `iris/agent/prompts/<host>.py` and register it in `system_prompt.py`'s `_HOST_PROMPTS` dict
7. Create an entry point script (e.g., `iris_<host>.py`) that bootstraps the plugin

## Import Conventions

- **Cross-package imports** use absolute paths: `from iris.tools.base import tool`
- **Within the same package** (e.g., `iris/binja/tools/`) use absolute imports to avoid confusion: `from iris.binja.tools.common import get_bv`
- **IDA tool modules** (`iris/tools/*.py`) use relative imports within `iris.tools` but absolute for other packages
- **Backward-compat shims** in `iris/tools_bn/`, `iris/hosts/`, and `iris/ui/` re-export from canonical locations

## System Prompt Structure

System prompts are built from **shared sections** + **host-specific content**:

```
iris/agent/prompts/
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
| `iris/agent/loop.py` | Core agent loop — generator-based turn cycle |
| `iris/tools/base.py` | `@tool` decorator, `ToolDefinition`, JSON schema generation |
| `iris/tools/registry.py` | `ToolRegistry` class — registration, dispatch, argument coercion |
| `iris/ui/session_controller_base.py` | `SessionControllerBase` — host-agnostic session orchestration |
| `iris/ui/panel_core.py` | `PanelCore` — shared Qt panel logic (chat view, input, settings) |
| `iris/core/config.py` | `IRISConfig` — all settings, provider config, host paths |
| `iris/core/host.py` | Host context singleton (BinaryView, address, navigate callback) |
| `iris/core/thread_safety.py` | `@idasync` decorator for main-thread marshalling |
| `iris/providers/base.py` | `LLMProvider` ABC — interface for all LLM providers |
| `iris/mcp/manager.py` | `MCPManager` — starts MCP servers, bridges tools into registry |
| `iris/skills/registry.py` | `SkillRegistry` — discovers and loads SKILL.md files |
| `iris/state/session.py` | `SessionState` — message history, token usage tracking |
| `iris_plugin.py` | IDA Pro plugin entry point |
| `iris_binaryninja.py` | Binary Ninja plugin entry point |
