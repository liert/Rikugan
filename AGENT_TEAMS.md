# Agent Teams — Implementation Plan

## Vision

The orchestrator (main chat agent) dynamically assembles a **team of N agents** tailored to the target file or task. The team size, roles, and specializations are not fixed — the orchestrator decides based on what it observes during an initial triage step. A firmware blob might get 6 agents; a simple CTF challenge might get 3.

---

## 1. Core Concepts

### 1.1 What Already Exists (and maps directly)

| Existing Component | File | Maps To |
|---|---|---|
| `SubagentManager` | `agent/subagent_manager.py` | Spawns/tracks/cancels agents in background threads |
| `SubagentRunner` | `agent/subagent.py` | Isolated `AgentLoop` per agent with its own session |
| `SubagentInfo` | `agent/subagent_manager.py` | Per-agent metadata (status, turns, tokens, parent/child) |
| `TurnEvent` stream | `agent/turn.py` | 18+ event types already flow to UI in real-time |
| `AgentTreeWidget` | `ui/agent_tree.py` | Tree view displaying agents with status/turns/elapsed |
| `SpawnAgentDialog` | `ui/agent_tree.py` | Agent type + perks + max_turns configuration |
| Perks system | `agent/agents/perks.py` | System prompt augmentation per capability |
| A2A types | `agent/a2a/types.py` | `A2ATask`, `A2AEvent`, `ExternalAgentConfig` |
| `SubprocessBridge` | `agent/a2a/subprocess_bridge.py` | External CLI agent execution |
| `ExternalAgentRegistry` | `agent/a2a/registry.py` | Auto-discovers agents on PATH |
| Exploration 4-phase FSM | `agent/exploration_mode.py` | Phase gating, knowledge base, consensus pattern |
| Report Writer agent | `agent/agents/report_writer.py` | Writer role prototype |
| Network Recon agent | `agent/agents/network_recon.py` | Specialized agent type pattern |
| Context compaction | `agent/context_window.py` | Prevents context overflow per agent |

### 1.2 What Needs to Be Built

| New Component | Purpose |
|---|---|
| **`AgentTeam`** | Lifecycle container for a group of cooperating agents |
| **`TeamOrchestrator`** | Phased state machine: triage → plan → analyze → write → review |
| **`MessageBus`** | Shared typed-message channel for intra-team communication |
| **`RoleDefinition`** | Declarative agent role (system prompt, tool subset, focus area) |
| **`RoleLibrary`** | Registry of available roles the orchestrator can pick from |
| **`TeamPlan`** | Structured output of the triage/planning phase |
| **Team UI**  | Group node in `AgentTreeWidget` + team progress panel |

---

## 2. Architecture

```
User: "Reverse engineer this file"
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│  ORCHESTRATOR (main chat AgentLoop)                       │
│                                                          │
│  1. Triage: read file header, size, type                 │
│  2. Decide team composition from RoleLibrary             │
│  3. Emit TeamPlan for user approval (optional)           │
│  4. Spawn AgentTeam via TeamOrchestrator                 │
│  5. Receive final report, present to user                │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│  TeamOrchestrator                                        │
│                                                          │
│  Phase 0: SPAWN                                          │
│  ├─ Create AgentTeam with N SubagentRunners              │
│  ├─ Assign RoleDefinition to each                        │
│  └─ Initialize MessageBus                                │
│                                                          │
│  Phase 1: PLANNING                                       │
│  ├─ All analyst agents post initial observations         │
│  ├─ Rounds of PROPOSAL / AGREE / QUESTION messages       │
│  └─ Gate: consensus or max_rounds reached                │
│                                                          │
│  Phase 2: ANALYSIS (parallel)                            │
│  ├─ Each analyst works their assigned focus area         │
│  ├─ Posts FINDING messages to bus                        │
│  └─ Gate: all analysts done or max_turns reached         │
│                                                          │
│  Phase 3: SYNC                                           │
│  ├─ Agents cross-reference each other's findings         │
│  ├─ Resolve conflicts, fill gaps                         │
│  └─ Produce merged FindingsBundle                        │
│                                                          │
│  Phase 4: WRITING                                        │
│  ├─ Writer agent receives FindingsBundle                 │
│  └─ Produces structured report draft                     │
│                                                          │
│  Phase 5: REVIEW                                         │
│  ├─ Analyst agents review draft, post REVISION messages  │
│  ├─ Writer incorporates feedback                         │
│  └─ Gate: all approve or max_review_rounds reached       │
│                                                          │
│  → Return final report to orchestrator                   │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Data Structures

### 3.1 `RoleDefinition`

**File**: `agent/teams/roles.py`

```python
@dataclass
class RoleDefinition:
    """Declarative definition of an agent role within a team."""

    slug: str                        # e.g. "structure_analyst"
    display_name: str                # e.g. "Structure Analyst"
    category: Literal["analyst", "writer", "reviewer"]
    system_addendum: str             # injected into system prompt
    focus_description: str           # one-line for planning round context
    perks: list[str]                 # perks to activate
    suggested_tools: list[str]       # tool whitelist (empty = all)
    default_max_turns: int = 25
```

### 3.2 `RoleLibrary`

**File**: `agent/teams/roles.py`

A registry of all available roles. The orchestrator queries this to build a team. Ships with built-in roles and supports user-defined roles via `~/.idapro/rikugan/roles/*.yaml`.

Built-in roles (initial set — not limited to these):

| Slug | Category | Focus |
|---|---|---|
| `structure_analyst` | analyst | File format, headers, segments, encoding, magic bytes |
| `logic_analyst` | analyst | Algorithms, control flow, function signatures, call graphs |
| `dataflow_analyst` | analyst | Inputs, outputs, state mutations, serialization |
| `security_analyst` | analyst | Vulnerabilities, error handling, boundary conditions |
| `crypto_analyst` | analyst | Cryptographic primitives, key handling, entropy analysis |
| `network_analyst` | analyst | Network protocols, C2 communication, socket usage |
| `string_analyst` | analyst | String decryption, encoding, obfuscation patterns |
| `report_writer` | writer | Synthesizes findings into structured documentation |
| `peer_reviewer` | reviewer | Cross-checks findings for accuracy and completeness |

### 3.3 `BusMessage`

**File**: `agent/teams/bus.py`

```python
class MessageType(str, Enum):
    OBSERVATION = "observation"    # initial fact about the target
    PROPOSAL    = "proposal"       # "I plan to investigate X"
    AGREE       = "agree"          # "I support agent Y's proposal"
    DISAGREE    = "disagree"       # "That won't work because..."
    QUESTION    = "question"       # directed question to another agent
    ANSWER      = "answer"         # response to a question
    FINDING     = "finding"        # analysis result
    DRAFT       = "draft"          # writer shares a section
    REVISION    = "revision"       # analyst corrects the draft
    CONSENSUS   = "consensus"      # agent signs off
    CONFLICT    = "conflict"       # two findings contradict

@dataclass
class BusMessage:
    id: str
    sender_id: str                 # agent ID
    sender_role: str               # role slug
    type: MessageType
    content: str                   # natural language
    target_agent: str | None       # for directed messages (QUESTION, ANSWER)
    references: list[str]          # IDs of messages this responds to
    metadata: dict[str, Any]       # structured data (addresses, function names, etc.)
    timestamp: float
```

### 3.4 `MessageBus`

**File**: `agent/teams/bus.py`

```python
class MessageBus:
    """Thread-safe shared message channel for intra-team communication."""

    _messages: list[BusMessage]
    _lock: threading.Lock
    _subscribers: dict[str, queue.Queue]  # agent_id → personal inbox

    def post(self, msg: BusMessage) -> None
    def get_history(self, since: float = 0, types: list[MessageType] | None = None) -> list[BusMessage]
    def get_for_agent(self, agent_id: str, limit: int = 50) -> list[BusMessage]
    def has_consensus(self, agent_ids: list[str]) -> bool
    def get_findings(self) -> list[BusMessage]
    def get_conflicts(self) -> list[BusMessage]
    def summary(self, max_tokens: int = 2000) -> str  # compact summary for context injection
```

Key design choices:
- **Thread-safe**: `_lock` protects `_messages`. Agents run in parallel threads.
- **Pull model**: Agents pull messages when they start a new turn, not push-interrupted. This matches the existing `AgentLoop` turn cycle.
- **Summary method**: Returns a token-budgeted digest of recent messages for injection into agent system prompts. Prevents the bus history from blowing up context windows.

### 3.5 `TeamPlan`

**File**: `agent/teams/plan.py`

```python
@dataclass
class TeamPlan:
    """Output of the orchestrator's triage step."""

    target_description: str          # what the file is
    team_roles: list[RoleDefinition] # selected roles
    strategy_notes: str              # orchestrator's reasoning
    estimated_turns: int             # budget estimate
    writer_role: RoleDefinition      # which role compiles the report
```

### 3.6 `AgentTeam`

**File**: `agent/teams/team.py`

```python
@dataclass
class AgentTeam:
    """Container for a group of cooperating agents."""

    id: str
    name: str
    plan: TeamPlan
    bus: MessageBus
    agents: dict[str, TeamAgent]     # agent_id → TeamAgent
    status: TeamStatus               # PLANNING | ANALYZING | SYNCING | WRITING | REVIEWING | DONE | FAILED
    created_at: float
    completed_at: float | None

@dataclass
class TeamAgent:
    """An agent within a team."""

    id: str
    role: RoleDefinition
    runner: SubagentRunner
    info: SubagentInfo               # reuse existing SubagentInfo for UI
    findings: list[BusMessage]       # this agent's FINDING messages
```

### 3.7 `FindingsBundle`

**File**: `agent/teams/plan.py`

```python
@dataclass
class FindingsBundle:
    """Merged findings from all analyst agents, ready for the writer."""

    sections: dict[str, list[BusMessage]]  # role_slug → findings
    conflicts: list[tuple[BusMessage, BusMessage]]  # contradicting findings
    questions_unresolved: list[BusMessage]
    consensus_notes: str                    # from planning round
    target_description: str
```

---

## 4. TeamOrchestrator — The State Machine

**File**: `agent/teams/orchestrator.py`

### 4.1 Phase Diagram

```
TRIAGE ──→ SPAWN ──→ PLANNING ──→ ANALYSIS ──→ SYNC ──→ WRITING ──→ REVIEW ──→ DONE
                         │              │                    │           │
                         │              │                    │           │
                    (max rounds)   (max turns)          (max turns)  (max rounds)
                         │              │                    │           │
                         ▼              ▼                    ▼           ▼
                      ANALYSIS      SYNC (forced)        REVIEW      DONE (forced)
```

### 4.2 Phase Details

#### Phase 0: TRIAGE (runs in orchestrator, not in team)

The main chat agent performs quick triage before spawning any team:

1. Read file header (magic bytes, size, architecture)
2. Query `RoleLibrary` for suggested roles based on file type
3. Construct a `TeamPlan`
4. Optionally present plan to user for approval

This is a **pseudo-tool** in the main `AgentLoop`: `spawn_team`. The orchestrator calls it with the file and its triage observations. The pseudo-tool creates the `TeamOrchestrator` and kicks off Phase 1.

```python
# Pseudo-tool schema injected when teams are enabled
{
    "name": "spawn_team",
    "description": "Spawn a team of specialized agents to analyze the target.",
    "parameters": {
        "target": "str — file path or description",
        "roles": "list[str] — role slugs to include",
        "strategy": "str — high-level approach notes",
        "max_planning_rounds": "int — default 3",
        "max_review_rounds": "int — default 2"
    }
}
```

#### Phase 1: PLANNING (collaborative, sequential rounds)

```
for round in range(max_planning_rounds):
    for agent in analyst_agents:
        # Inject bus history into agent's next turn
        bus_context = bus.summary(max_tokens=1500)
        agent_prompt = f"""
        [TEAM PLANNING — Round {round+1}]
        You are {agent.role.display_name}.

        Messages from other team members:
        {bus_context}

        Based on the target file and your specialization:
        1. Share your initial observations
        2. Propose your analysis plan
        3. Ask questions of other agents if needed
        4. If you agree with the current plan, say CONSENSUS

        Use the team_message tool to post to the team.
        """
        # Run one turn of the agent
        run_single_turn(agent, agent_prompt)

    if bus.has_consensus(analyst_agent_ids):
        break
```

**Implementation note**: This is *sequential within a round* but conceptually each agent sees all prior messages. We run agents one at a time within a round because they need to read each other's messages. Rounds are the parallelism boundary — within a round, order doesn't matter conceptually, but practically we serialize to avoid race conditions on the bus.

**Alternative**: For speed, we could run all agents in parallel within a round, then have a "digest" step where each agent reads the new messages. This doubles the turns but halves wall-clock time. Worth making configurable.

#### Phase 2: ANALYSIS (parallel)

```
# All analyst agents run in parallel
threads = []
for agent in analyst_agents:
    findings_context = bus.summary(max_tokens=1000)
    task = f"""
    [TEAM ANALYSIS — {agent.role.display_name}]

    Agreed plan from planning round:
    {plan_summary}

    Your assignment: {agent.role.focus_description}

    Other agents are analyzing in parallel. When you discover something,
    use team_message(type="finding", ...) to share it.

    Focus on your area. You have {agent.role.default_max_turns} turns.
    """
    thread = spawn_agent_thread(agent, task)
    threads.append(thread)

# Wait for all to complete (with timeout)
wait_all(threads, timeout=max_analysis_timeout)
```

Each agent runs its own `SubagentRunner.run_task()` in a background thread (exactly as `SubagentManager.spawn()` already does). The only addition is that each agent has access to a `team_message` pseudo-tool that posts to the bus.

#### Phase 3: SYNC

A single "sync round" where agents read each other's findings and can:
- Flag conflicts between findings
- Ask follow-up questions
- Fill gaps they noticed in other agents' coverage

```
for agent in analyst_agents:
    all_findings = bus.get_findings()
    task = f"""
    [TEAM SYNC]

    All findings from the team:
    {format_findings(all_findings)}

    Review the findings. For each issue:
    - If you see a conflict with your findings, post a CONFLICT message
    - If something is missing from your area, post an additional FINDING
    - If you have a question for another agent, post a QUESTION
    - If everything looks good, post CONSENSUS
    """
    run_single_turn(agent, task)
```

#### Phase 4: WRITING

Build a `FindingsBundle` from the bus and hand it to the writer agent:

```
bundle = FindingsBundle(
    sections={agent.role.slug: agent.findings for agent in analyst_agents},
    conflicts=bus.get_conflicts(),
    questions_unresolved=[m for m in bus.get_history(types=[QUESTION]) if not has_answer(m)],
    consensus_notes=planning_round_summary,
    target_description=team.plan.target_description,
)

writer_task = f"""
[TEAM WRITING]

You are the Report Writer. Compile these findings into a comprehensive report.

{bundle.to_prompt()}

Produce:
1. Executive summary
2. File structure / format overview
3. Function-by-function breakdown (or section-by-section for non-code)
4. Data flow analysis
5. Security assessment (if applicable)
6. Appendix: per-agent raw notes

Use team_message(type="draft", ...) to share each section as you write it.
"""
writer_summary = run_agent_to_completion(writer_agent, writer_task)
```

#### Phase 5: REVIEW

```
for round in range(max_review_rounds):
    draft = get_latest_draft()

    for agent in analyst_agents:
        task = f"""
        [TEAM REVIEW — Round {round+1}]

        Review this draft from the Writer:
        {draft}

        Check the section relevant to your expertise ({agent.role.focus_description}).
        - If accurate, post CONSENSUS
        - If corrections needed, post REVISION with specific fixes
        """
        run_single_turn(agent, task)

    if bus.has_consensus(analyst_agent_ids):
        break

    # Writer incorporates revisions
    revisions = bus.get_history(types=[REVISION], since=round_start)
    writer_task = f"Incorporate these revisions:\n{format_revisions(revisions)}"
    run_single_turn(writer_agent, writer_task)
```

---

## 5. Integration Points

### 5.1 `team_message` Pseudo-Tool

Injected into agent tool lists when they are part of a team. Handled inline in `_execute_tool_calls()`, same pattern as `exploration_report`.

```python
{
    "name": "team_message",
    "description": "Post a message to the team message bus.",
    "parameters": {
        "type": "str — observation|proposal|agree|disagree|question|answer|finding|draft|revision|consensus|conflict",
        "content": "str — the message content",
        "target_agent": "str|null — role slug of the target (for questions/answers)",
        "metadata": "dict — optional structured data (addresses, function names, etc.)"
    }
}
```

### 5.2 `spawn_team` Pseudo-Tool

**Only injected into the tool list when team mode is active** (checkbox on or `/team` command used). Never available during normal solo operation. This prevents the agent from ever unilaterally deciding to spawn a team.

When the agent calls `spawn_team`, the UI intercepts it and shows the `TeamSetupDialog` for user confirmation. The team does not start until the user clicks [Launch Team].

```python
# Pseudo-tool schema — only present when team mode is active
{
    "name": "spawn_team",
    "description": "Spawn a team of agents to collaboratively analyze the target. "
                   "The user will see a confirmation dialog before the team launches.",
    "parameters": {
        "target": "str — file/task description from triage",
        "roles": "list[str] — role slugs from RoleLibrary",
        "strategy": "str — high-level approach notes",
        "max_planning_rounds": "int — default 3",
        "max_review_rounds": "int — default 2"
    }
}
```

The pseudo-tool handler in `_execute_tool_calls()`:

```python
if tool_name == "spawn_team":
    # Don't start the team yet — emit a UI approval request
    yield TurnEvent.team_setup_request(
        roles=args["roles"],
        strategy=args.get("strategy", ""),
        target=args.get("target", ""),
    )
    # Block until user confirms or cancels via TeamSetupDialog
    approval = self._user_answer_queue.get()  # "launch" or "cancel"
    if approval == "cancel":
        yield TurnEvent.text_delta("Team launch cancelled.")
        continue
    # User confirmed (possibly with modified roles) — proceed
    confirmed_roles = approval.get("roles", args["roles"])
    orchestrator = TeamOrchestrator(...)
    yield from orchestrator.run()
    continue
```

### 5.3 Event Flow

New `TurnEventType` values for team operations:

| Event Type | Description |
|---|---|
| `TEAM_SPAWNED` | Team created with N agents |
| `TEAM_PHASE_CHANGE` | Phase transition (PLANNING → ANALYSIS, etc.) |
| `TEAM_BUS_MESSAGE` | New message on the bus (for UI display) |
| `TEAM_AGENT_DONE` | One agent in the team completed |
| `TEAM_SYNC_CONFLICT` | Conflict detected between findings |
| `TEAM_REPORT_DRAFT` | Writer produced a draft section |
| `TEAM_COMPLETED` | Team finished, report ready |

These flow through the existing `TurnEvent` → `Queue` → UI poll pipeline.

### 5.4 Two Activation Modes

Teams are **never** auto-spawned by the agent. Activation is always explicit, either via UI or command.

#### Mode A: "Use Teams" Checkbox (UI-driven)

A persistent **"Use Teams"** checkbox sits in the input area, next to the Send button (or in the action buttons area). When checked:

1. The next message the user sends gets routed through team mode.
2. The orchestrator does quick triage (read header, identify file type).
3. The orchestrator picks roles from `RoleLibrary` based on what it sees.
4. A `TeamSetupDialog` pops up showing the proposed team with checkboxes — the user can adjust before confirming.
5. On confirm → fork tab, swap to `TeamChatView`, team starts.

If the checkbox is off, the agent works solo as usual. The checkbox state persists per session (saved in `SessionState.metadata["team_mode"]`).

```python
# In InputArea or action buttons area:
self._team_check = QCheckBox("Use Teams")
self._team_check.setStyleSheet("color: #d4d4d4; font-size: 11px;")
self._team_check.setToolTip("Route the next task to a team of specialized agents")
```

#### Mode B: `/team` Command (explicit)

The user types `/team <task>` in the input area. This:

1. Skips the checkbox entirely — it's an explicit request.
2. Orchestrator does triage, proposes roles.
3. `TeamSetupDialog` pops up for confirmation (same as Mode A).
4. On confirm → fork + swap + start.

```
User: /team Analyze this firmware for vulnerabilities
       → [TeamSetupDialog pops up with proposed roles]
       → [User confirms or adjusts]
       → [Team starts]
```

#### Mode C: "Team" Button (manual setup)

The **"Team" button** in the action buttons stack opens `TeamSetupDialog` directly, without any triage. The user manually picks roles and types a task description. This is the "I know what I want" path.

#### What the Agent Never Does

- The agent **never** calls `spawn_team` on its own initiative. The `spawn_team` pseudo-tool is only callable when team mode is active (checkbox on or `/team` command used).
- If the user asks "reverse engineer this" with the checkbox off, the agent works solo.
- The system prompt for the orchestrator includes team awareness only when team mode is active:

```
## Team Mode (active)

The user has enabled team mode. You should:
1. Perform quick triage on the target (read_bytes at offset 0, length 256, check size)
2. Decide which roles are needed from the available set:
   {role_library.list_descriptions()}

Guidelines for team composition:
- Simple CTF / small binary: 2-3 analysts + 1 writer
- Firmware blob: structure + logic + dataflow + security + writer (5)
- Malware sample: structure + logic + network + crypto + security + writer (6)
- Large codebase: structure + logic + dataflow + writer (4) per module
- Quick triage: 1 analyst + 1 writer (2)

After triage, call spawn_team with your role selection.
The user will see a confirmation dialog before the team launches.
```

When team mode is not active, this section is absent from the system prompt entirely, and the `spawn_team` pseudo-tool is not injected into the tool list.

---

## 6. File Organization

```
rikugan/agent/teams/
├── __init__.py
├── orchestrator.py       # TeamOrchestrator state machine
├── team.py               # AgentTeam, TeamAgent, TeamStatus
├── bus.py                # MessageBus, BusMessage, MessageType
├── roles.py              # RoleDefinition, RoleLibrary
├── plan.py               # TeamPlan, FindingsBundle
└── builtins/             # Built-in role definitions
    ├── structure.yaml
    ├── logic.yaml
    ├── dataflow.yaml
    ├── security.yaml
    ├── crypto.yaml
    ├── network.yaml
    ├── strings.yaml
    ├── writer.yaml
    └── reviewer.yaml
```

---

## 7. Token Budget Model

This is the critical constraint. Each agent consumes tokens independently.

### 7.1 Per-Agent Budget

| Component | Estimated Tokens |
|---|---|
| System prompt (base + role addendum) | ~2,000 |
| File context (headers, key sections) | ~1,000-4,000 |
| Bus messages (summary, capped) | ~1,500 |
| Tool results (per turn, compacted) | ~2,000 |
| Agent reasoning + tool calls | ~1,000/turn |

At 25 turns per agent: ~30K-40K tokens per analyst agent.

### 7.2 Team Budget (example: 4 analysts + 1 writer)

| Phase | Tokens (estimated) |
|---|---|
| Planning (3 rounds × 4 agents × ~2K) | ~24K |
| Analysis (4 agents × 30K) | ~120K |
| Sync (4 agents × ~5K) | ~20K |
| Writing (1 agent × ~40K) | ~40K |
| Review (2 rounds × 4 agents × ~3K + writer ~5K) | ~29K |
| **Total** | **~233K** |

### 7.3 Cost Controls

- **Bus summary cap**: `MessageBus.summary(max_tokens=N)` prevents history from exploding
- **Context compaction**: Each agent uses existing `ContextWindowManager`
- **Finding dedup**: The SYNC phase can merge duplicate findings before handing to the writer
- **Early termination**: If an analyst finishes early (no more findings), it can exit before `max_turns`
- **Configurable team size**: User can override the orchestrator's suggestions

---

## 8. UI — Group Chat Model

The team experience is **not** a side panel or a separate bus viewer. It is the chat itself, transformed into a group conversation. When the user activates team mode, the chat becomes a multi-participant room where agents are "people" talking to each other — and the user is one of those people.

### 8.1 Activation Flow

Teams are always user-initiated (see Section 5.4). There are three entry points, all leading to the same `TeamSetupDialog` confirmation step before anything happens.

#### Path A: "Use Teams" Checkbox

```
┌──────────────────────────────────────────────────────────────────┐
│  Normal Chat                                                      │
│                                                                    │
│  ┌───────────────────────────────────────────────────────┐        │
│  │  Type a message...                [☑ Use Teams] [Send]│        │
│  └───────────────────────────────────────────────────────┘        │
│                                                                    │
│  User checks "Use Teams", then types:                             │
│  "Reverse engineer this firmware blob"  → [Send]                  │
│                                                                    │
│  Rikugan does quick triage (reads header, checks size)            │
│  Rikugan calls spawn_team → triggers TeamSetupDialog              │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Team Setup                                                  │  │
│  │                                                              │  │
│  │  Target: firmware.bin (48KB, ARM Cortex-M)                   │  │
│  │                                                              │  │
│  │  Proposed team:                                              │  │
│  │  ☑ Structure Analyst    ☑ Logic Analyst                      │  │
│  │  ☑ Data Flow Analyst    ☑ Security Analyst                   │  │
│  │  ☐ Crypto Analyst       ☐ Network Analyst                    │  │
│  │  ☐ String Analyst       ☑ Report Writer                      │  │
│  │                                                              │  │
│  │  Est. budget: ~233K tokens                                   │  │
│  │                                                              │  │
│  │                        [Cancel]  [Launch Team]                │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  User clicks [Launch Team]                                        │
│  → Fork current tab → "Session 1"                                │
│  → Current tab transforms → "Team: Firmware RE"                  │
│  → Group chat begins                                              │
└──────────────────────────────────────────────────────────────────┘
```

#### Path B: `/team` Command

```
User types: /team Analyze this firmware for vulnerabilities
  → Same triage + TeamSetupDialog flow
  → Checkbox state doesn't matter — explicit command overrides
```

#### Path C: "Team" Button (manual)

```
User clicks [Team] button in action buttons
  → TeamSetupDialog opens immediately (no triage — user picks roles manually)
  → User types task description in the dialog
  → [Launch Team] → fork + swap + start
```

#### What Happens on Launch

When the user confirms in `TeamSetupDialog`:

1. The current session is **forked** into a new tab (preserving the original 1:1 chat via `_ctrl.fork_session()`). This is the "old context" preserved.
2. The current tab's `ChatView` is **replaced** with a `TeamChatView` — a group-chat variant.
3. The tab label changes to the team name (e.g., "Team: Firmware RE").
4. A header bar appears showing the team roster and current phase.
5. The "Use Teams" checkbox auto-unchecks (one-shot: team was launched, don't re-trigger on the next message).

### 8.2 `TeamChatView` — The Group Chat Widget

**File**: `ui/team_chat_view.py`

`TeamChatView` extends `ChatView` but replaces the message rendering model. Instead of a single "You" and "Rikugan", there are N participants, each with a name, color, and avatar indicator.

```
┌──────────────────────────────────────────────────────────────────────┐
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Team: Firmware RE          Phase: ANALYSIS ●●●○○    [Stop]  │   │
│  │ 🔍 Structure  🔍 Logic  🔍 DataFlow  🔍 Security  📝 Writer │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─ System ────────────────────────────────────────────────────────┐ │
│  │ Team assembled. 5 agents are now planning their approach.      │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ Structure Analyst ─────────────────────────────────────────────┐ │
│  │ File is 48KB, starts with ARM vector table at 0x0.             │ │
│  │ I see 3 LOAD segments: .text, .rodata, .data.                  │ │
│  │ I'll map the full memory layout and tag permissions.            │ │
│  │                                              [PROPOSAL] 0:12  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ Security Analyst ──────────────────────────────────────────────┐ │
│  │ I see strings suggesting UART and a firmware update routine.   │ │
│  │ @DataFlow — can you flag anything touching external input?     │ │
│  │                                              [QUESTION] 0:14  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ Data Flow Analyst ─────────────────────────────────────────────┐ │
│  │ @Security — Yes, UART_Rx at 0x08001200 feeds directly into    │ │
│  │ a handler with no length check. Tagging it.                    │ │
│  │                                               [ANSWER] 0:15  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ You ───────────────────────────────────────────────────────────┐ │
│  │ Focus on the OTA update path — that's the highest risk.        │ │
│  │                                              [queued] 0:18    │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─ Logic Analyst ─────────────────────────────────────────────────┐ │
│  │ Noted. I'll prioritize tracing the OTA handler call graph.     │ │
│  │ Found: OTA_Process at 0x08002400, called from UART IRQ.        │ │
│  │                                              [FINDING] 0:20  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │  Type a message to the team...                    [Send]      │   │
│  └───────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### 8.3 Message Widget: `TeamMessageWidget`

**File**: `ui/team_message_widgets.py`

Each agent's message is rendered with:

| Element | Description |
|---|---|
| **Role label** | Agent's display name, colored per-role |
| **Color bar** | Left border in the agent's assigned color |
| **Content** | Markdown-rendered message body |
| **Type badge** | Small tag: `[FINDING]`, `[PROPOSAL]`, `[QUESTION]`, `[CONSENSUS]`, etc. |
| **Timestamp** | Relative time since team start |
| **@ mentions** | Clickable role names that highlight the target agent |

```python
class TeamMessageWidget(QFrame):
    """A single message in the team group chat."""

    def __init__(
        self,
        sender_name: str,          # "Structure Analyst"
        sender_color: str,         # "#4ec9b0"
        content: str,              # markdown text
        message_type: str,         # "finding", "proposal", "question", etc.
        timestamp: float,          # seconds since team start
        target_agent: str | None,  # "@Security" mention
        is_user: bool = False,     # True if this is a human message
        parent: QWidget = None,
    ):
```

Color palette for roles (deterministic, no collisions with N <= 10):

```python
ROLE_COLORS: list[str] = [
    "#4ec9b0",   # teal — structure
    "#569cd6",   # blue — logic
    "#c586c0",   # purple — dataflow
    "#f44747",   # red — security
    "#d7ba7d",   # gold — crypto
    "#ce9178",   # orange — network
    "#b5cea8",   # green — strings
    "#dcdcaa",   # yellow — writer
    "#9cdcfe",   # light blue — reviewer
    "#808080",   # gray — overflow
]
```

### 8.4 Team Header Bar

**File**: `ui/team_header.py`

A fixed bar above the chat showing team state at a glance:

```python
class TeamHeaderBar(QFrame):
    """Persistent bar showing team roster and phase progress."""

    # Displays:
    # - Team name
    # - Current phase (with visual phase dots: ●●●○○)
    # - Agent roster as colored chips with status indicators:
    #     ● running  ✓ done  ✗ failed  ○ pending
    # - [Stop Team] button
    # - Elapsed time
    # - Total tokens used
```

Phase dots map to the orchestrator phases:

```
●●●●●  PLANNING
●●●●○  ANALYSIS
●●●○○  SYNC
●●○○○  WRITING
●○○○○  REVIEW
```

Agent chips are clickable — clicking one scrolls to that agent's most recent message in the chat.

### 8.5 User Participation — Message Queue

The user types messages into the same input area. Their messages go to the `MessageBus` as `BusMessage` with `sender_role = "user"` and `type = USER_DIRECTIVE`.

```python
class MessageType(str, Enum):
    # ... existing types ...
    USER_DIRECTIVE = "user_directive"  # human intervention
```

How agents see user messages:

- User messages are **high priority** in the bus summary. They always appear at the top of the injected context, prefixed with `[USER DIRECTIVE]`.
- On the next turn of each agent, the bus summary includes the user's message. Agents are instructed to acknowledge and respond to user directives.
- If the user's message is directed (`@Security focus on the OTA path`), only the targeted agent sees it as high priority. Others see it as informational.

The user's message appears in the group chat immediately as a `TeamMessageWidget` with `is_user=True`, styled distinctly (same "You" teal color as normal chat, but with a `[directive]` badge).

If the team is mid-turn (agents are running), the message is **queued** — shown with a dashed border (reusing the existing `QueuedMessageWidget` visual language) and injected into the bus. Agents will pick it up on their next turn.

### 8.6 Tab Lifecycle

```
Normal state:
┌───────────────┐
│  New Chat     │    ← single tab, normal ChatView
└───────────────┘

After team activation:
┌───────────────┬────────────────────┐
│  Session 1    │  Team: Firmware RE │    ← fork + team chat
└───────────────┴────────────────────┘

After team completes:
┌───────────────┬────────────────────┐
│  Session 1    │  Team: Firmware RE │    ← team tab shows final report
└───────────────┴────────────────────┘
                        │
                        ▼
            User can switch back to Session 1
            (original context preserved) and
            continue 1:1 chat with Rikugan
```

When the team completes:

1. The `TeamChatView` shows the final report as the last message from the Writer agent.
2. A **"Return to Chat"** button appears in the header, which switches to the forked tab.
3. The forked tab's agent automatically receives a summary: "Team analysis complete. Here are the findings: [compact summary]."
4. The team tab stays around for reference (scroll up to read the full group conversation).

### 8.7 Tool Activity in Group Chat

When agents use RE tools (decompile, read_bytes, etc.), the tool calls appear **inline** in the group chat under that agent's name, using the existing `ToolCallWidget` / `ToolGroupWidget` collapse logic:

```
┌─ Logic Analyst ────────────────────────────────────────────────┐
│  Tracing the OTA handler call graph from 0x08002400.          │
│                                                                │
│  ▶ decompile_function("OTA_Process")                          │
│  ▶ xrefs_to(0x08002400)                                       │
│  ▶ decompile_function("UART_IRQHandler")                      │
│  ── 3 tool calls completed ──                                  │
│                                                                │
│  OTA_Process receives a buffer from UART, validates a 4-byte  │
│  magic header, then memcpy's the payload to flash at 0x0800_  │
│  8000. No signature verification.                              │
│                                              [FINDING] 1:42   │
└────────────────────────────────────────────────────────────────┘
```

Tool calls are collapsed by default (same `_TOOL_GROUP_MIN_CALLS` threshold = 2). The user can expand to see full arguments and results. This keeps the group chat readable while preserving full transparency.

### 8.8 `TeamChatView` Implementation Notes

`TeamChatView` is a new class that **replaces** `ChatView` on the tab, not a subclass. It shares infrastructure:

```python
class TeamChatView(QScrollArea):
    """Group chat view for team collaboration."""

    user_message_submitted = Signal(str)  # user typed a message

    def __init__(self, team: AgentTeam, parent: QWidget = None):
        super().__init__(parent)
        self._team = team
        self._header = TeamHeaderBar(team)
        self._message_widgets: dict[str, TeamMessageWidget] = {}  # bus_msg_id → widget

        # Agent color assignments
        self._agent_colors: dict[str, str] = {}
        for i, (agent_id, agent) in enumerate(team.agents.items()):
            self._agent_colors[agent_id] = ROLE_COLORS[i % len(ROLE_COLORS)]

    def handle_team_event(self, event: TurnEvent) -> None:
        """Process team-specific TurnEvents."""
        if event.type == TurnEventType.TEAM_BUS_MESSAGE:
            self._add_bus_message(event)
        elif event.type == TurnEventType.TEAM_PHASE_CHANGE:
            self._header.set_phase(event.metadata["to_phase"])
            self._insert_phase_divider(event)
        elif event.type == TurnEventType.TEAM_AGENT_DONE:
            self._header.mark_agent_done(event.metadata["agent_id"])
        # Tool events are handled per-agent, same as ChatView
        elif event.type in (TurnEventType.TOOL_CALL_START, ...):
            self._handle_agent_tool_event(event)

    def _add_bus_message(self, event: TurnEvent) -> None:
        """Render a BusMessage as a TeamMessageWidget in the chat."""
        meta = event.metadata
        widget = TeamMessageWidget(
            sender_name=meta["sender_name"],
            sender_color=self._agent_colors.get(meta["sender_id"], "#808080"),
            content=meta["content"],
            message_type=meta["type"],
            timestamp=meta["timestamp"],
            target_agent=meta.get("target_agent"),
        )
        self._insert_widget(widget)
        self._scroll_to_bottom()
```

### 8.9 Phase Dividers

When the orchestrator transitions phases, a visual divider appears in the chat:

```
──────────── Phase: ANALYSIS ─────────────
   4 agents working in parallel
──────────────────────────────────────────
```

```python
class PhaseDividerWidget(QFrame):
    """Horizontal divider marking a phase transition in the team chat."""

    def __init__(self, phase_name: str, description: str, parent=None):
        # Centered label with horizontal lines on both sides
        # Same visual language as ExplorationPhaseWidget but wider
```

### 8.10 `SpawnAgentDialog` → `TeamSetupDialog`

The manual entry point. Opened by clicking the "Team" button:

```
┌──────────────────────────────────────────────────────────────┐
│  Team Setup                                                   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Mode:  ○ Auto (orchestrator decides)                        │
│         ● Manual (pick roles)                                │
│                                                              │
│  Available Roles:                                            │
│  ☑ Structure Analyst    ☑ Logic Analyst                      │
│  ☑ Data Flow Analyst    ☑ Security Analyst                   │
│  ☐ Crypto Analyst       ☐ Network Analyst                    │
│  ☐ String Analyst       ☑ Report Writer                      │
│                                                              │
│  Estimated budget: ~233K tokens ($0.47)                      │
│                                                              │
│               [Cancel]  [Launch Team]                         │
└──────────────────────────────────────────────────────────────┘
```

### 8.11 Agent Tree Enhancement (Tools Panel)

The `AgentTreeWidget` in the Tools panel becomes the **control center** for team operations. While the group chat is the conversation surface, the tree is the monitoring and management surface.

Current `AgentTreeWidget` shows flat agents. With teams, add a **collapsible group node**:

```
▼ Team: Firmware RE (3/5 active)              [Kill All]
    ├── ● Structure Analyst     ✓ done    12 turns   34s    [Inject]
    ├── ● Logic Analyst         ⟳ turn 8   ...       28s    [Kill]
    ├── ● Data Flow Analyst     ⟳ turn 6   ...       22s    [Kill]
    ├── ● Security Analyst      ⟳ turn 4   ...       15s    [Kill]
    └── ● Report Writer         ○ pending  —          —
  ──────────────────────────────────────────────────────
  agent-7 (custom)              ✓ done    5 turns    12s
  agent-8 (network_recon)       ⟳ turn 3   ...       8s
```

Implementation uses the existing `parent_id` / `children` fields on `SubagentInfo`:

- The team itself is registered as a virtual `SubagentInfo` with `agent_type="team"`.
- Each team agent has `parent_id` set to the team's ID.
- `setRootIsDecorated(True)` enables the expand/collapse arrows.
- The team node shows aggregate status: "3/5 active", "4/5 done", "COMPLETED", etc.
- **Kill All** button on the team node cancels all running agents.
- **Inject** button on completed agents injects their summary into the current chat tab.

Clicking an agent in the tree scrolls the team chat to that agent's latest message.

The tree also gets a new filter option: `["All Agents", "General", "Bulk Rename", "Teams"]`.

### 8.12 Bus Viewer Panel (Tools Panel — New Tab)

A dedicated **Bus tab** in the Tools panel showing the raw message bus in real-time. This is the "developer view" of what's happening — the group chat shows the conversation, but the bus viewer shows the structured protocol messages with full metadata.

**File**: `ui/bus_viewer.py`

```
┌──────────────────────────────────────────────────────────────────┐
│  Message Bus                                 [Phase: ANALYSIS]   │
│  Filter: [All ▾]  [Show metadata ☐]  [Auto-scroll ☑]           │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  0:12  [PROPOSAL]  Structure Analyst                             │
│        "I'll map the full memory layout and tag permissions."    │
│                                                                  │
│  0:13  [AGREE]     Logic Analyst → Structure Analyst             │
│        "Sounds good. I'll wait for your section table."          │
│                                                                  │
│  0:14  [QUESTION]  Security Analyst → Data Flow Analyst          │
│        "What feeds into the memcpy at 0x401234?"                │
│        metadata: {address: "0x401234", severity: "high"}         │
│                                                                  │
│  0:15  [ANSWER]    Data Flow Analyst → Security Analyst          │
│        "User input via recv() at 0x401100, no bounds check"     │
│        refs: [msg-014]                                           │
│                                                                  │
│  0:18  [USER_DIRECTIVE]  You                                     │
│        "Focus on the OTA update path"                            │
│                                                                  │
│  0:20  [FINDING]   Logic Analyst                                 │
│        "OTA_Process at 0x08002400, called from UART IRQ"        │
│        metadata: {address: "0x08002400", function: "OTA_Process"}│
│                                                                  │
│  0:25  [CONFLICT]  Security Analyst                              │
│        "RE-1 says auth_check is NOP'd, but I see it's called"  │
│        refs: [msg-018, msg-022]                                  │
│                                                                  │
│  0:30  [CONSENSUS] Structure Analyst                             │
│        "My analysis is complete."                                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

```python
class BusViewerWidget(QWidget):
    """Real-time message bus viewer for the Tools panel."""

    def __init__(self, parent: QWidget = None):
        # ...
        self._filter_combo: QComboBox  # All, Findings only, Questions, Conflicts, User
        self._metadata_check: QCheckBox  # show/hide metadata
        self._auto_scroll: QCheckBox
        self._message_list: QVBoxLayout  # scrollable list of BusMessageEntryWidgets

    def on_bus_message(self, msg: BusMessage) -> None:
        """Called when a new message is posted to the bus."""
        entry = BusMessageEntryWidget(msg)
        if not self._matches_filter(msg):
            entry.setHidden(True)
        self._message_list.addWidget(entry)
        if self._auto_scroll.isChecked():
            self._scroll_to_bottom()
```

Message type color coding (matches the group chat colors):

```python
BUS_TYPE_COLORS: dict[str, str] = {
    "observation":    "#808080",  # gray
    "proposal":       "#569cd6",  # blue
    "agree":          "#4ec9b0",  # teal
    "disagree":       "#f44747",  # red
    "question":       "#dcdcaa",  # yellow
    "answer":         "#9cdcfe",  # light blue
    "finding":        "#4ec9b0",  # teal (bold)
    "draft":          "#c586c0",  # purple
    "revision":       "#ce9178",  # orange
    "consensus":      "#6a9955",  # green
    "conflict":       "#f44747",  # red (bold)
    "user_directive": "#4ec9b0",  # teal (user color)
}
```

The Bus tab is added to the `ToolsPanel` alongside Renamer, Agents, and A2A:

```python
# In ToolsPanel.__init__():
self._bus_viewer = BusViewerWidget()
self.addTab(self._bus_viewer, "Bus")
# Tab only becomes visible when a team is active
self._bus_viewer_tab_index = self.indexOf(self._bus_viewer)
self.setTabVisible(self._bus_viewer_tab_index, False)
```

### 8.13 Three Views, One Bus

All three UI surfaces show the same underlying `MessageBus`, just at different levels of detail:

```
┌──────────────────────────────────────────────────────────────────┐
│                        MessageBus                                │
│                    (single source of truth)                      │
└───────┬──────────────────┬──────────────────┬────────────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
  ┌──────────┐     ┌──────────────┐    ┌──────────────┐
  │ Group    │     │ Agent Tree   │    │ Bus Viewer   │
  │ Chat     │     │ (Tools)      │    │ (Tools)      │
  │          │     │              │    │              │
  │ Natural  │     │ Agent status │    │ Raw protocol │
  │ language │     │ overview +   │    │ messages +   │
  │ messages │     │ management   │    │ metadata +   │
  │ + tools  │     │ controls     │    │ filtering    │
  └──────────┘     └──────────────┘    └──────────────┘
   Primary UX       Monitoring          Debugging
```

### 8.14 Summary: What Gets Built (UI)

| Component | File | Type |
|---|---|---|
| `TeamChatView` | `ui/team_chat_view.py` | New — group chat scroll area |
| `TeamMessageWidget` | `ui/team_message_widgets.py` | New — per-agent message bubble |
| `TeamHeaderBar` | `ui/team_header.py` | New — roster + phase bar |
| `PhaseDividerWidget` | `ui/team_message_widgets.py` | New — phase transition marker |
| `TeamSetupDialog` | `ui/team_setup_dialog.py` | New — role picker dialog |
| `TeamToolGroupWidget` | `ui/team_message_widgets.py` | New — tool calls scoped to agent |
| `BusViewerWidget` | `ui/bus_viewer.py` | New — raw bus protocol viewer |
| `BusMessageEntryWidget` | `ui/bus_viewer.py` | New — single bus message display |
| `AgentTreeWidget` updates | `ui/agent_tree.py` | Modified — collapsible group nodes |
| `ToolsPanel` updates | `ui/tools_panel.py` | Modified — Bus tab |
| `RikuganPanelCore` updates | `ui/panel_core.py` | Modified — team button, checkbox, tab fork, view swap |

---

## 9. Implementation Order

### Phase A: Foundation (bus + roles + team container)

1. **`agent/teams/bus.py`** — `MessageBus`, `BusMessage`, `MessageType`
   - Thread-safe message store
   - `summary()` with token budget
   - `has_consensus()` check
   - Unit tests

2. **`agent/teams/roles.py`** — `RoleDefinition`, `RoleLibrary`
   - Dataclass + YAML loader
   - Built-in role definitions (YAML files)
   - `suggest_roles(file_type, file_size)` helper

3. **`agent/teams/team.py`** — `AgentTeam`, `TeamAgent`, `TeamStatus`
   - Container dataclass
   - Status lifecycle enum

4. **`agent/teams/plan.py`** — `TeamPlan`, `FindingsBundle`
   - `FindingsBundle.to_prompt()` for writer injection

### Phase B: Orchestrator state machine

5. **`agent/teams/orchestrator.py`** — `TeamOrchestrator`
   - Phase enum and transitions
   - `run()` generator yielding `TurnEvent`s
   - Planning round loop
   - Parallel analysis dispatch (via `SubagentManager`)
   - Sync round
   - Writer dispatch
   - Review loop
   - Timeout and error handling

6. **`team_message` pseudo-tool** — in `agent/loop.py`
   - Inject schema when agent is part of a team
   - Route to `MessageBus.post()`
   - Yield `TEAM_BUS_MESSAGE` event

7. **`spawn_team` pseudo-tool** — in `agent/loop.py`
   - Triage prompt in system prompt
   - Create `TeamOrchestrator`, run it
   - Forward events to parent queue
   - Return final report as tool result

### Phase C: Integration

8. **New `TurnEventType` values** — in `agent/turn.py`
   - Add team event types
   - Factory methods on `TurnEvent`

9. **`SubagentManager` extension** — spawn_team path
   - `spawn_team()` method that creates a `TeamOrchestrator`
   - Track team agents as children of a virtual group node

10. **System prompt additions** — in `agent/system_prompt.py`
    - Team spawning guidelines
    - Role library descriptions
    - Budget awareness

### Phase D: UI — Group Chat

11. **`TeamMessageWidget` + `PhaseDividerWidget`** — in `ui/team_message_widgets.py`
    - Per-agent colored message bubble with role label, type badge, timestamp
    - `@mention` rendering for directed messages
    - Phase divider with centered label and horizontal rules
    - Tool call embedding (reuse `ToolCallWidget` / `ToolGroupWidget`)

12. **`TeamHeaderBar`** — in `ui/team_header.py`
    - Agent roster chips (colored, with status indicators)
    - Phase progress dots (●●●○○)
    - Stop Team button, elapsed time, token count
    - Click-to-scroll: chip click → scroll to agent's last message

13. **`TeamChatView`** — in `ui/team_chat_view.py`
    - Extends `QScrollArea` (same base as `ChatView`)
    - Handles `TEAM_BUS_MESSAGE`, `TEAM_PHASE_CHANGE`, `TEAM_AGENT_DONE` events
    - Routes tool events to per-agent inline display
    - User message submission → `MessageBus.post()` as `USER_DIRECTIVE`
    - Auto-scroll with "scroll lock" (same `_is_near_bottom()` logic)

14. **`TeamSetupDialog`** — in `ui/team_setup_dialog.py`
    - Auto/Manual mode toggle
    - Role checkbox grid from `RoleLibrary`
    - Budget estimate display
    - Opens from new "Team" button in action buttons

15. **`RikuganPanelCore` integration** — in `ui/panel_core.py`
    - "Use Teams" checkbox in input area (persisted in `SessionState.metadata`)
    - "Team" button in action button stack (opens `TeamSetupDialog` directly)
    - `/team` command detection in `_on_submit()` → same flow as checkbox
    - On `TEAM_SETUP_REQUEST` event: show `TeamSetupDialog`, wait for user confirmation
    - On confirm: fork tab → swap `ChatView` for `TeamChatView` → rename tab → auto-uncheck
    - On team complete: "Return to Chat" button → switch to forked tab
    - Poll `TEAM_*` events and route to `TeamChatView.handle_team_event()`

### Phase E: UI — Monitoring Panels

16. **`AgentTreeWidget` group nodes** — in `ui/agent_tree.py`
    - Enable `setRootIsDecorated(True)` for collapsible parent nodes
    - Virtual team parent node from `SubagentInfo(agent_type="team")`
    - Aggregate status text, "Kill All" button, "Inject" per agent
    - New filter: "Teams"
    - Click-to-scroll: tree item click → scroll `TeamChatView` to agent's message

17. **`BusViewerWidget`** — in `ui/bus_viewer.py`
    - New tab in `ToolsPanel` (hidden until team active)
    - Filter combo: All / Findings / Questions / Conflicts / User
    - Show metadata toggle
    - Auto-scroll toggle
    - Color-coded `BusMessageEntryWidget` per message type
    - Tab visibility controlled by `RikuganPanelCore` on team start/stop

### Phase F: Polish

18. **Built-in roles** — YAML definitions in `agent/teams/builtins/`
    - Tune system prompts per role
    - Test with different file types

19. **User-defined roles** — load from `~/.idapro/rikugan/roles/`
    - Same format as built-in
    - Discovery at startup

16. **Token budget tracking** — per-team aggregate display
    - Total tokens across all agents
    - Cost estimate (provider-dependent)

---

## 10. Agent Communication Protocol

### 10.1 How Agents See the Bus

Each agent gets bus messages injected at the start of each turn as a system addendum:

```
[TEAM MESSAGES — last 10 messages]
[FINDING by Structure Analyst] ELF 64-bit, 3 LOAD segments...
[QUESTION by Security Analyst → Data Flow Analyst] What feeds into memcpy at 0x401234?
[FINDING by Logic Analyst] Main function has 3 branches...
```

This is pulled via `bus.summary(max_tokens=1500)` and appended to the agent's system prompt. The agent never sees the raw bus object — it's always a formatted text injection.

### 10.2 How Agents Post to the Bus

Via the `team_message` pseudo-tool:

```json
{
    "name": "team_message",
    "type": "finding",
    "content": "The function at 0x401234 uses an unbounded memcpy from user input",
    "metadata": {"address": "0x401234", "severity": "high"}
}
```

### 10.3 Consensus Protocol

An agent posts `CONSENSUS` when it has nothing more to add in the current phase. The `TeamOrchestrator` checks `bus.has_consensus(agent_ids)` at the end of each round:

```python
def has_consensus(self, agent_ids: list[str]) -> bool:
    """True if all specified agents have posted CONSENSUS since the last non-consensus message."""
    consensus_senders = set()
    for msg in reversed(self._messages):
        if msg.type == MessageType.CONSENSUS and msg.sender_id in agent_ids:
            consensus_senders.add(msg.sender_id)
        elif msg.sender_id in agent_ids and msg.type != MessageType.CONSENSUS:
            # A non-consensus message after a consensus means they revoked it
            break
    return consensus_senders == set(agent_ids)
```

---

## 11. Handling Edge Cases

### 11.1 Agent Failure

If one agent fails (crashes, exceeds turns, provider error):

- The `TeamOrchestrator` logs the failure
- Other agents continue — the team is resilient to single-agent failure
- The writer notes the gap in the report ("Security analysis unavailable — agent failed")
- The team can still complete with partial results

### 11.2 Infinite Disagreement

If the planning round never reaches consensus:

- Hard cap at `max_planning_rounds` (default 3)
- After the cap, the orchestrator extracts the "majority plan" from proposals
- Posts a synthetic `CONSENSUS` message: "Planning round ended by timeout. Proceeding with majority plan."

### 11.3 Conflicting Findings

If two agents disagree on a fact (e.g., RE-1 says "function X is a parser" and RE-2 says "function X is an encoder"):

- The SYNC phase explicitly surfaces conflicts
- Agents can post `CONFLICT` messages referencing both findings
- The writer includes both interpretations with a note: "Agents disagreed on this point"
- Optionally, the orchestrator can spawn a tiebreaker turn where the conflicting agents discuss

### 11.4 Context Window Overflow

Each agent has its own `SessionState` and `ContextWindowManager`. But the bus summary can grow:

- `bus.summary()` is always token-budgeted
- Old messages are summarized, not included verbatim
- Agents only see recent + relevant messages, not the full history

### 11.5 Large Files

For binaries >1MB, no agent can hold the full file in context:

- The triage step identifies key regions (headers, entry points, interesting sections)
- Each agent gets a focused excerpt relevant to their role
- Agents use tools (`read_bytes`, `decompile_function`, etc.) to pull additional data on demand
- This already works — agents never get the full file in context today

---

## 12. Configuration

### 12.1 `RikuganConfig` Additions

```python
# Team settings
team_enabled: bool = True
team_max_agents: int = 8                    # hard cap
team_max_planning_rounds: int = 3
team_max_review_rounds: int = 2
team_analysis_timeout: float = 600.0        # seconds
team_planning_parallel: bool = False        # parallel planning rounds
team_auto_approve: bool = False             # skip user approval of team plan
team_bus_summary_tokens: int = 1500         # max tokens for bus summary injection
```

### 12.2 Per-Role Config (YAML)

```yaml
slug: security_analyst
display_name: Security Analyst
category: analyst
focus_description: >
  Vulnerabilities, error handling, boundary conditions,
  input validation, authentication, and cryptographic weaknesses.
perks:
  - deep_decompilation
  - string_harvesting
suggested_tools:
  - decompile_function
  - read_disassembly
  - xrefs_to
  - xrefs_from
  - list_imports
  - search_strings
  - read_bytes
default_max_turns: 25
system_addendum: |
  You are the Security Analyst on a reverse engineering team.

  Your focus:
  - Buffer overflows, format string bugs, integer overflows
  - Missing input validation on external data
  - Authentication/authorization bypasses
  - Cryptographic weaknesses (hardcoded keys, weak algorithms)
  - Error handling that leaks information

  When you find a vulnerability, rate its severity (critical/high/medium/low)
  and explain the exploitation path.
```

---

## 13. Testing Strategy

### 13.1 Unit Tests

- `MessageBus`: thread safety, consensus detection, summary generation
- `RoleLibrary`: YAML loading, built-in registration, `suggest_roles()`
- `TeamOrchestrator`: phase transitions, timeout handling, error recovery
- `FindingsBundle`: prompt generation, conflict detection

### 13.2 Integration Tests

- Spawn a 3-agent team against a known test binary
- Verify all phases complete
- Check that the writer received findings from all analysts
- Verify bus messages are correctly routed

### 13.3 Eval Cases

- **Simple ELF** (small CTF binary): Verify orchestrator picks 2-3 agents
- **Firmware blob** (ARM Cortex-M): Verify 5+ agents with structure focus
- **Malware sample** (PE with C2): Verify network + crypto analysts selected
- **Obfuscated binary**: Verify string analyst included
- Compare team output quality vs. single-agent analysis
