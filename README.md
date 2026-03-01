# IRIS — Intelligent Reverse-engineering Integrated System

An IDA Pro plugin that integrates a multi-provider LLM agent as a first-class reverse engineering companion. IRIS provides an agentic loop with streaming, 57 purpose-built IDA tools, 7 built-in analysis skills, MCP server integration, and a native Qt chat panel — all accessible through a single hotkey.

## Features

- **57 IDA tools** — navigation, decompiler, disassembly, xrefs, strings, annotations, type engineering, microcode, scripting
- **7 built-in skills** — malware analysis, deobfuscation, vulnerability audit, driver analysis, CTF solving, and more
- **MCP client** — connect external MCP servers, their tools appear alongside built-in ones
- **9 context menu actions** — right-click in disasm/pseudocode for instant analysis
- **5 LLM providers** — Anthropic (Claude), OpenAI, Gemini, Ollama, OpenAI-compatible
- **Message queuing** — send follow-up messages while the agent is working; they auto-submit when the current turn finishes
- **Unlimited tool rounds** — the agent runs until the task is done, not until an arbitrary counter expires
- **Microcode tools** — read, NOP, and install custom optimizers at any Hex-Rays maturity level
- **Session persistence** — auto-save/restore conversations across IDA restarts

## Requirements

- IDA Pro 9.0+ with Hex-Rays decompiler (recommended)
- Python 3.9+
- At least one LLM provider SDK installed

## Installation

### 1. Clone or symlink into your IDA plugins directory

```bash
# Symlink (recommended for development)
ln -s /path/to/IDAPlugins/iris_plugin.py ~/.idapro/plugins/iris_plugin.py
ln -s /path/to/IDAPlugins/iris ~/.idapro/plugins/iris

# Or copy directly
cp iris_plugin.py ~/.idapro/plugins/
cp -r iris ~/.idapro/plugins/
```

### 2. Install a provider SDK

```bash
# Anthropic (Claude) — recommended
pip install anthropic

# OpenAI
pip install openai

# Google Gemini
pip install google-generativeai

# Ollama (local models) — uses the openai package
pip install openai
```

Use the `pip` that corresponds to your IDA Python environment.

### 3. Set your API key

**Environment variable:**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic
export OPENAI_API_KEY="sk-..."          # OpenAI
export GOOGLE_API_KEY="..."             # Gemini
```

**Anthropic OAuth:** If you have Claude Code installed and authenticated, IRIS auto-detects the OAuth token from the macOS Keychain. No configuration needed.

**Settings dialog:** Open IRIS → click Settings → paste your key. Keys are persisted to `~/.idapro/iris/config.json`.

### 4. Verify

Launch IDA and open any binary. You should see:

```
[IRIS] INFO: Plugin loaded (v0.1.0)
```

## Usage

### Open the panel

Press **Ctrl+Shift+I** or go to **Edit → Plugins → IRIS**.

### Chat

Type a message and press **Enter** to send. IRIS streams the response and executes IDA tools as needed.

- **Enter** — send message
- **Shift+Enter** — newline
- **Escape** — cancel the current run (also clears queued messages)

### Message queuing

You can send messages while the agent is working. They appear as `[queued]` in the chat and auto-submit when the current turn finishes. Hit **Stop** to cancel the running turn and discard all queued messages.

### Context menu

Right-click in the disassembly or pseudocode view:

| Action | Views | Behavior |
|--------|-------|----------|
| **Send to IRIS** | disasm, pseudo | Pre-fills input with selection (Ctrl+Shift+A) |
| **Explain this** | disasm, pseudo | Auto-explains the current function |
| **Rename with IRIS** | disasm, pseudo | Analyzes and renames with evidence |
| **Deobfuscate with IRIS** | disasm, pseudo | Systematic deobfuscation |
| **Find vulnerabilities** | disasm, pseudo | Security audit |
| **Suggest types** | disasm, pseudo | Infers types from usage patterns |
| **Annotate function** | pseudo | Adds comments to decompiled code |
| **Clean microcode** | pseudo | Identifies and NOPs junk microcode |
| **Xref analysis** | disasm, pseudo | Deep cross-reference tracing |

### Skills

Skills are reusable analysis workflows. Type `/` in the input area to see available skills with autocomplete.

**Built-in skills:**

| Skill | Description |
|-------|-------------|
| `/malware-analysis` | Windows PE malware — kill chain, IOC extraction, MITRE ATT&CK mapping |
| `/linux-malware` | ELF malware — packing detection, persistence, IOC extraction |
| `/deobfuscation` | String decryption, CFF removal, opaque predicates, MBA simplification, microcode cleaning |
| `/driver-analysis` | Windows kernel drivers — DriverEntry, dispatch table, IOCTL handlers |
| `/vuln-audit` | Buffer overflows, format strings, integer issues, memory safety |
| `/ctf` | Capture-the-flag — find the flag efficiently |
| `/generic-re` | General-purpose binary analysis |

**User skills:** Create custom skills in `~/.iris/skills/<slug>/SKILL.md`. User skills with the same slug override built-in ones.

Skill format:
```markdown
---
name: My Custom Skill
description: What it does in one line
tags: [analysis, custom]
---
Task: <instruction for the agent>

## Approach
...
```

### MCP Servers

Connect external MCP servers to extend IRIS with additional tools. Configure in `~/.iris/mcp.json`:

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

MCP tools appear alongside built-in tools with the prefix `mcp_<server>_<tool>`. The agent sees them in the tool list and can call them like any other tool.

### Settings

Click **Settings** in the panel to configure:

| Setting | Description |
|---------|-------------|
| Provider | `anthropic`, `openai`, `gemini`, `ollama`, `openai_compat` |
| Model | Model ID (e.g. `claude-sonnet-4-20250514`, `gpt-4o`) |
| API Key | Provider API key (or use env vars / OAuth) |
| API Base | Custom endpoint URL for `openai_compat` / `ollama` |
| Temperature | 0.0–2.0 (default 0.2) |
| Max Output Tokens | Per-response token limit (default 16384) |
| Context Window | Model context window size |
| Auto-context | Inject binary info and cursor position into system prompt |
| Auto-save | Persist sessions across restarts |

### Using Ollama (local models)

1. Install and start [Ollama](https://ollama.com)
2. Pull a model: `ollama pull llama3.1`
3. In IRIS settings: provider → `ollama`, model → `llama3.1`
4. No API key required — connects to `http://localhost:11434`

### Using OpenAI-compatible endpoints

For Together, Groq, vLLM, or any OpenAI-compatible API:

1. Provider → `openai_compat`
2. API Base → endpoint URL
3. Set model name and API key as needed

## Tools

57 tools organized by category:

| Category | Tools |
|----------|-------|
| **Navigation** | `get_cursor_position`, `get_current_function`, `jump_to`, `get_name_at`, `get_address_of` |
| **Functions** | `list_functions`, `get_function_info`, `search_functions` |
| **Strings** | `list_strings`, `search_strings`, `get_string_at` |
| **Database** | `list_segments`, `list_imports`, `list_exports`, `get_binary_info`, `read_bytes` |
| **Disassembly** | `read_disassembly`, `read_function_disassembly`, `get_instruction_info` |
| **Decompiler** | `decompile_function`, `get_pseudocode`, `get_decompiler_variables` |
| **Xrefs** | `xrefs_to`, `xrefs_from`, `function_xrefs` |
| **Annotations** | `rename_function`, `rename_variable`, `set_comment`, `set_function_comment`, `rename_address`, `set_type` |
| **Types** | `create_struct`, `modify_struct`, `get_struct_info`, `list_structs`, `create_enum`, `modify_enum`, `get_enum_info`, `list_enums`, `create_typedef`, `apply_struct_to_address`, `apply_type_to_variable`, `set_function_prototype`, `import_c_header`, `suggest_struct_from_accesses`, `propagate_type`, `get_type_libraries`, `import_type_from_library` |
| **Microcode** | `get_microcode`, `get_microcode_block`, `nop_microcode`, `install_microcode_optimizer`, `remove_microcode_optimizer`, `list_microcode_optimizers`, `redecompile_function` |
| **Scripting** | `execute_python` (last resort — the agent prefers built-in tools) |

Decompiler and microcode tools require Hex-Rays. If unavailable, they return an error and all other tools continue to work.

## Project Structure

```
iris_plugin.py                  # Plugin entry point (PLUGIN_ENTRY)
iris/
  constants.py
  core/
    types.py                    # Message, ToolCall, ToolResult, TokenUsage
    errors.py                   # IRISError hierarchy
    thread_safety.py            # @idasync decorator
    config.py                   # JSON-persisted configuration
    logging.py                  # IDA output window logger
  providers/
    base.py                     # LLMProvider ABC
    anthropic_provider.py       # Claude adapter (with OAuth auto-detect)
    openai_provider.py          # GPT adapter
    openai_compat.py            # Generic OpenAI-compatible adapter
    gemini_provider.py          # Gemini adapter
    ollama_provider.py          # Ollama adapter
    registry.py                 # Provider factory
  tools/
    base.py                     # @tool decorator, JSON schema generation
    registry.py                 # Tool registry and dispatch
    navigation.py               # Cursor, jump, name lookup
    functions.py                # Function listing and search
    strings.py                  # String listing and search
    database.py                 # Segments, imports, exports, binary info
    disassembly.py              # Disassembly reading
    decompiler.py               # Hex-Rays pseudocode
    xrefs.py                    # Cross-references
    annotations.py              # Rename, comment, set type
    types_tools.py              # Struct/enum/typedef engineering
    microcode.py                # Hex-Rays microcode read/NOP/optimizer
    scripting.py                # Python execution (last resort)
  skills/
    loader.py                   # SKILL.md parser (frontmatter + body)
    registry.py                 # Skill discovery and resolution
    builtins/                   # 7 built-in skills
      malware-analysis/
      linux-malware/
      deobfuscation/
      driver-analysis/
      vuln-audit/
      ctf/
      generic-re/
  mcp/
    config.py                   # ~/.iris/mcp.json parser
    protocol.py                 # JSON-RPC 2.0 encoding/decoding
    client.py                   # MCP server subprocess manager
    bridge.py                   # MCP tool → IRIS tool adapter
    manager.py                  # Multi-server orchestrator
  agent/
    loop.py                     # Generator-based agentic turn cycle
    turn.py                     # TurnEvent types
    plan_mode.py                # Plan generation and step execution
    checkpoint.py               # Session checkpoint save/restore
    context_window.py           # Token tracking and compaction
    system_prompt.py            # Binary-aware system prompt builder
  state/
    session.py                  # Session state
    conversation.py             # Message serialization
    history.py                  # Session persistence
  ui/
    qt_compat.py                # PySide6/PyQt5 detection
    styles.py                   # Dark theme stylesheet
    panel.py                    # Main dockable panel
    chat_view.py                # Scrollable message area
    input_area.py               # Multi-line input with /skill autocomplete
    context_bar.py              # Address/function/model/token display
    message_widgets.py          # User/assistant/tool call widgets
    plan_view.py                # Plan step display with approve/reject
    settings_dialog.py          # Configuration dialog
    actions.py                  # Context menu integration (9 actions)
tests/
  mocks/ida_mock.py             # Mock IDA API for testing
  test_tools.py
  test_providers.py
  test_agent.py
  test_skills.py
  test_mcp.py
```

## Running Tests

Tests use a mock IDA API layer and run without IDA:

```bash
cd /path/to/IDAPlugins
python3 -m unittest discover -s tests -v
```

## Data Storage

```
~/.idapro/iris/
  config.json                   # Settings
  checkpoints/
    sessions/                   # Auto-saved session history
  iris_debug.log                # Debug log

~/.iris/
  skills/                       # User-defined skills
    my-skill/
      SKILL.md
  mcp.json                      # MCP server configuration
```

## License

MIT
