# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Conversator is a **voice-first orchestration layer** for hands-free software development. It converts vague spoken requests into structured prompts, dispatches work to builder engines (OpenCode, Claude Code), and tracks parallel tasks through Beads (task graph).

**Current State**: Planning/specification phase - no implementation code yet.

## Architecture

Three-layer architecture:
1. **Layer 1 (Voice)**: Gemini Live API - handles real-time voice, function calling to Layer 2
2. **Layer 2 (Orchestration)**: OpenCode HTTP API + subagents (Clarifier, Prompt Refiner, Retriever, Summarizer) - model-flexible
3. **Layer 3 (Execution)**: Claude Code SDK + Beads - deep planning (Opus) and building (Sonnet)

Key components:
- **Beads**: Canonical work graph (tasks, dependencies, history)
- **Conversator Control Plane**: Voice UX, model routing, memory discipline, session monitoring
- **Builder Engines**: Execute handoff prompts, report progress via events

## Workspace Structure

```
.conversator/
  state.sqlite           # event log + derived state
  mappings.json          # beads_id <-> conversator_task_id <-> session_id
  inbox.jsonl            # notification queue
  prompts/<topic>/
    working.md           # mutable prompt during conversation
    handoff.md           # frozen prompt (XML-like structure)
    handoff.json         # ExecutionSpec
  memory/
    atomic.jsonl         # small, auditable committed memory
    episodic/            # per-task summaries
  rag/                   # local disposable indexes
```

## Key Conventions

- **Prompt refinement**: Single mutable `working.md` file, freeze to `handoff.*` only on user confirmation
- **Memory discipline**: Store pointers, not prose; RAG indexes are disposable
- **Evidence attachment**: Link artifacts back to Beads tasks
- **Gates**: Confirm before write/run/destructive operations
- **Token budgets**: Voice layer ~900 tokens, subagents ~4K tokens each

## Implementation Order

1. Workspace layout (`docs/11-workspace-layout.md`)
2. Event-sourced state (`docs/04-task-session-state.md`)
3. Prompt refinement loop (`docs/06-workflows.md`)
4. Beads integration (Phase 3)
5. Builder adapter (Phase 4)
6. Memory budgets (`docs/05-memory-and-rag.md`)
7. UX polish and gates (`docs/10-ui-ux.md`)

## Spec Documentation

All specifications are in `plans/detailed/docs/`:
- `00-overview.md` - Goals and non-goals
- `03-architecture.md` - Layer responsibilities and contracts
- `04-task-session-state.md` - Event-sourced state model
- `05-memory-and-rag.md` - Tiered memory, retrieval budgets
- `06-workflows.md` - End-to-end workflows with mermaid diagrams
- `07-models-routing.md` - Model/provider flexibility
- `11-workspace-layout.md` - On-disk structure
- `12-phases-and-validation.md` - Implementation phases with proofs-of-done

Templates in `plans/detailed/templates/`:
- `prompt-xml-template.md` - Structure for handoff.md files
- `event-types.md` - Event definitions

## Technology Stack (Planned)

- **Voice**: Gemini Live API (chosen for cost at ~$9/6hr vs OpenAI $37/6hr)
- **Orchestration**: OpenCode HTTP API (model flexibility, native subagents)
- **Execution**: Claude Code SDK (Max subscription for cost-effective Opus/Sonnet access)
- **Task Queue**: Beads (DAG dependencies, `bd ready` for ready tasks)
- **Storage**: SQLite (events, derived state), JSONL (inbox, atomic memory)
- **RAG**: SQLite FTS or local BM25, optional embeddings
