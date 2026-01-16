# Conversator: Project Overview

## One-Liner

**Conversator is a voice-first orchestration layer that transforms casual spoken requests into refined prompts, dispatches them to AI coding agents, and maintains continuous development flow—all hands-free.**

---

## The Core Idea

You speak naturally about what you need. Conversator asks clarifying questions, builds a high-quality prompt through conversation, sends it to the right agent, monitors progress, and keeps you productive while waiting. It's the voice interface between your brain and your AI coding assistants.

```
YOU (speaking): "the auth thing is broken again"
         │
         ▼
    CONVERSATOR
    "Is this the JWT refresh issue? What's happening exactly?"
         │
         ▼
    [Iterative conversation refines the request]
         │
         ▼
    REFINED PROMPT → BUILDER AGENT → CODE CHANGES
         │
         ▼
    "Done. Fixed the race condition. Want details?"
```

---

## Three-Layer Architecture

### Layer 1: Voice Interface (Gemini Live API)

**What it does:** Real-time voice conversation with the user.

- Native speech-to-speech (no transcription step)
- Built-in voice activity detection and interruption handling
- Function calling to dispatch tasks to Layer 2
- Unlimited session length via context compression
- Minimal context (~900 tokens) for fast responses

**Model:** `gemini-2.5-flash-native-audio`  
**Cost:** ~$0.025/minute of active conversation

### Layer 2: Orchestration (OpenCode + Subagents)

**What it does:** Prompt refinement, context management, agent coordination.

- Receives function calls from voice layer
- Spawns specialized subagents for different tasks
- Manages memory bank (index, summaries, RAG)
- Monitors builder agents in Layer 3
- Generates summaries for voice delivery

**Models:** Gemini 3 Flash (planning), Gemini Flash-Lite (summarizing)  
**Interface:** OpenCode HTTP API

### Layer 3: Execution (Claude Code SDK + Beads)

**What it does:** Deep planning and code implementation.

- Heavy model (Opus 4.5) for comprehensive planning
- Fast model (Sonnet 4.5) for building
- DAG-based task queue (Beads) for dependencies
- Full codebase access and modification

**Models:** Opus 4.5 (planning), Sonnet 4.5 (building)  
**Task Queue:** Beads

---

## Layer 2 Subagents

| Subagent | Model | Purpose |
|----------|-------|---------|
| **Planner** | Gemini 3 Flash | Iteratively refines vague requests into detailed prompts through Q&A |
| **Summarizer** | Gemini Flash-Lite | Condenses long outputs into 2-3 sentence voice-appropriate summaries |
| **Context Reader** | Gemini 3 Flash | Retrieves relevant context from codebase and history via RAG |
| **Status Monitor** | None (in-memory) | Tracks all running agents, instant status queries |

**Subagent Permissions (Conversator Layer):**
- ✅ Read codebase files
- ✅ Read/write `.conversator/**` workspace
- ❌ Execute bash commands
- ❌ Modify source code directly

---

## Layer 3 Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| **Deep Planner** | Opus 4.5 | Produces comprehensive plans with follow-up questions |
| **Builder** | Sonnet 4.5 | Implements code changes based on finalized plans |
| **Test Agent** | Haiku/Flash | Validates changes by running tests |

**Builder Permissions:**
- ✅ Full codebase access
- ✅ Execute bash commands
- ✅ Modify source code
- ✅ Run tests

---

## Key Workflow

### Planning Pipeline

1. **User speaks casually** → "fix the auth thing"
2. **Voice layer dispatches** → Calls `start_planning("auth issue")`
3. **Planner subagent activates** → Reads relevant code, asks clarifying questions
4. **Iterative refinement** → 3-5 Q&A turns build detailed prompt
5. **User confirms** → "send it to deep planner"
6. **Deep planner (Opus)** → Produces full plan + follow-up questions
7. **Questions delivered** → Voice asks user for answers
8. **Plan finalized** → Beads task created
9. **Builder executes** → Implements changes
10. **Notification delivered** → "Done. 3 files changed."

### Parallel Operations

- Plan Task B while Task A builds
- Multiple builders running simultaneously
- Notifications queued, delivered at natural pauses
- Scratchpad captures ideas during dead time

---

## Memory Management

### Three-Tier Architecture

```
TIER 1: INDEX (Always in RAM, ~2K tokens)
├── Keyword → file mapping
├── File → one-line summary
├── Agent status registry
└── Pending notifications

TIER 2: SUMMARIES (On-demand, ~10K tokens)
├── 3-5 sentence file abstracts
├── Decision log with context
└── Session summaries

TIER 3: FULL CONTENT (Disk/RAG)
├── Complete plan files
├── Codebase embeddings
└── Historical transcripts
```

**Key Principle:** Know what's in a file without reading it. Tier 1 provides instant lookup; only load full content when explicitly needed.

---

## Technology Choices

### Why Gemini Live over OpenAI Realtime?

| Factor | Gemini Live | OpenAI Realtime |
|--------|-------------|-----------------|
| 6-hour session cost | ~$9 | ~$37 |
| Session length | Unlimited* | Unlimited |
| Function calling | ✅ | ✅ |
| MCP support | ✅ | ❌ |

*With compression enabled

**Winner:** Gemini Live (4x cheaper for long sessions)

### Why OpenCode over Claude Code for Orchestration?

| Factor | OpenCode | Claude Code |
|--------|----------|-------------|
| Interface | HTTP API | Subprocess stdin/stdout |
| Model flexibility | Any provider | Anthropic only |
| Subagent system | Native YAML | Hooks/MCP |
| Community | Open source | Anthropic-maintained |

**Winner:** OpenCode (cleaner API, model flexibility)

### Why Claude Code SDK for Execution?

- Max subscription provides cost-effective Opus 4.5 access
- "Plan mode" enables read-only analysis
- SDK provides programmatic control
- Same subscription covers building (Sonnet 4.5)

### Why Beads for Task Queue?

- DAG-based dependency tracking
- `bd ready` returns only unblocked tasks
- Lightweight (single Go binary)
- MCP server available

---

## Development Environment

### Primary Target: Linux Wayland

- **OS:** Arch Linux / CachyOS
- **Display:** Wayland (GNOME)
- **Audio:** PipeWire (via sounddevice or custom)
- **Voice Input:** Voxtype-style push-to-talk or continuous

### Voxtype Reference

Voxtype is a Rust-based push-to-talk tool for Wayland with whisper.cpp integration. Conversator can learn from its approach:
- PipeWire audio capture
- Wayland-native (wtype for text output)
- Local Whisper for transcription fallback

### Audio Architecture

```
┌──────────────────────────────────────────────┐
│              AUDIO SOURCES                   │
├──────────────────────────────────────────────┤
│  Desktop Mic  │  Discord  │  Twilio (later)  │
│  (PipeWire)   │  (voice)  │  (phone)         │
└───────────────────────────────────────────────
         │
         ▼
┌──────────────────────────────────────────────┐
│         AUDIO NORMALIZER                     │
│         16kHz, mono, PCM                     │
└──────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────┐
│         GEMINI LIVE API                      │
│         (or Whisper fallback)                │
└──────────────────────────────────────────────┘
```

---

## OpenCode Subagent Creation

### Reference: oh-my-opencode Pattern

OpenCode supports custom subagents via YAML configuration. Similar to oh-my-opencode patterns:

```yaml
# .conversator/agents/planner.yaml
name: conversator-planner
description: Refines vague requests into detailed prompts

model: google/gemini-3-flash
mode: primary

system_prompt: |
  You are a planning assistant. Your job is to:
  1. Understand the user's intent
  2. Read relevant code files
  3. Ask clarifying questions (max 2-3 per turn)
  4. Build a detailed prompt in .conversator/plans/drafts/
  5. Signal "READY_FOR_DEEP_PLANNING: <filename>" when complete

tools:
  read: true
  glob: true
  grep: true
  write:
    allow: [".conversator/**"]
    deny: ["**"]

permissions:
  bash:
    deny: ["*"]
```

### Subagent Spawning

```python
# Orchestrator spawns subagent via OpenCode HTTP API
async def start_planner(topic: str, description: str):
    session = await opencode.create_session(agent="planner")
    
    async for event in opencode.chat(session.id, message=description):
        if "READY_FOR_DEEP_PLANNING" in event.content:
            plan_file = extract_filename(event.content)
            return plan_file
        elif event.type == "question":
            # Route question back to voice layer
            yield {"type": "question", "content": event.content}
```

---

## Middleware: Voice ↔ Agent Task Handling

### Input Flow (Voice → Agents)

```
User speaks
    │
    ▼
Gemini Live processes
    │
    ▼
Function call generated (e.g., start_planning)
    │
    ▼
Orchestrator receives call
    │
    ├──► Instant actions (get_status) → Return immediately
    │
    └──► Async actions (dispatch_plan) → Spawn agent, return estimate
```

### Output Flow (Agents → Voice)

```
Agent produces output
    │
    ▼
Summarizer condenses (if needed)
    │
    ▼
Notification Manager queues
    │
    ▼
Priority check:
    │
    ├──► Error → Interrupt immediately
    │
    ├──► Completion → Queue for natural pause
    │
    └──► Info → Low priority queue
    │
    ▼
Voice layer speaks at appropriate moment
```

### Middleware Responsibilities

1. **Route function calls** to appropriate handlers
2. **Track agent state** in status registry
3. **Queue notifications** with priority
4. **Manage conversation context** for voice layer
5. **Handle errors** gracefully
6. **Fill dead time** with productive suggestions

---

## Agent Implementation Flexibility

### Supported Execution Backends

| Backend | Use Case | Integration |
|---------|----------|-------------|
| **Claude Code SDK** | Max subscription, Opus/Sonnet | Python subprocess |
| **OpenCode Build** | Model flexibility, HTTP API | REST API |
| **Custom Agent** | Specialized tasks | MCP or direct API |

### Swappable Architecture

```python
class AgentDispatcher:
    def __init__(self, config):
        self.backends = {
            "claude": ClaudeCodeBackend(config),
            "opencode": OpenCodeBackend(config),
            "custom": CustomBackend(config),
        }
    
    async def dispatch(self, plan_path: str, backend: str = "claude"):
        agent = self.backends[backend]
        return await agent.execute(plan_path)
```

**Key Principle:** The orchestration layer doesn't care which agent executes—it just needs plan in, result out.

---

## File Structure

```
project/
├── .conversator/
│   ├── config.yaml              # Global configuration
│   ├── agents/                  # Subagent definitions
│   │   ├── planner.yaml
│   │   ├── summarizer.yaml
│   │   └── context-reader.yaml
│   ├── memory/                  # Three-tier memory
│   │   ├── index.yaml           # Tier 1: Keywords, summaries
│   │   └── embeddings/          # Tier 3: RAG vectors
│   ├── plans/                   # Planning artifacts
│   │   ├── drafts/              # Being refined
│   │   ├── ready/               # Awaiting deep planning
│   │   ├── active/              # Being executed
│   │   └── completed/           # Historical
│   ├── context/                 # Project context
│   │   ├── decisions-log.md
│   │   └── session-history/
│   └── scratchpad/              # Quick capture
│       ├── checklist.md
│       └── ideas.md
├── .beads/                      # Task queue
├── .opencode/                   # OpenCode config
└── src/                         # Codebase
```

---

## Summary Bullets

### What Conversator Is
- Voice-first orchestration layer for AI coding agents
- Transforms casual speech into refined prompts
- Manages multiple agents in parallel
- Maintains context across long sessions (5-8 hours)
- Keeps developer productive during wait times

### Core Workflow
- Speak → Clarify → Refine → Plan → Build → Notify
- Parallel planning while builders work
- Smart notifications at natural conversation pauses
- Memory bank for instant context recall

### Three Layers
- **Layer 1 (Voice):** Gemini Live API, minimal context, function dispatch
- **Layer 2 (Orchestration):** OpenCode subagents, memory management, coordination
- **Layer 3 (Execution):** Claude Code SDK, heavy planning, code implementation

### Key Technology Choices
- Gemini Live (4x cheaper than OpenAI for long sessions)
- OpenCode HTTP API (model flexibility, clean interface)
- Claude Code SDK (Max subscription, Opus 4.5 access)
- Beads (DAG task dependencies)

### Development Environment
- Linux Wayland (Arch/CachyOS, GNOME)
- PipeWire audio
- Voxtype-style voice input

### What Makes It Different
- Voice-native, not voice-as-afterthought
- Iterative prompt refinement through conversation
- Multi-agent orchestration with parallel execution
- Three-tier memory for instant context at scale
- Designed for 5-8 hour continuous sessions
