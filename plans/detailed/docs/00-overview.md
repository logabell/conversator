
# Overview

## What is Conversator?

Conversator is a **voice-first control plane** for long-running software work that:
- converts vague spoken requests into **structured, execution-ready prompts**
- dispatches work to one or more **builder engines** (e.g., OpenCode, Claude Code, others)
- tracks parallel work through **Beads** (task graph + durable history)
- maintains **token-lean memory** (pointers + summaries) and retrieves details on demand

Conversator is **not** a code agent that “does everything itself.” It is the orchestration layer that:
- runs subagents (clarifier/spec compiler/retriever/summarizer) to craft the final handoff prompt
- maintains an inbox/backpressure system for status updates
- enforces safety gates (confirm-before-write/run) and cancellation

## Goals

1. **Voice-first planning**: start with speech, end with an execution spec that builders can follow.
2. **Model/provider flexibility**: swap subagent models over time via config.
3. **Token discipline**: minimize context usage through tiered memory + pointer-first retrieval.
4. **Parallelism with good UX**: run multiple background tasks; notify at natural pauses.
5. **Durable work tracking**: use Beads as the canonical task/dependency system.

## Non-goals (v1)

- Being a full IDE replacement.
- Replacing Beads with another task DB.
- Perfect “autonomous coding” without user oversight gates.
- Storing full transcripts as “memory” by default.

## Key differentiators

- Prompt refinement loop: **conversation → working prompt → finalized handoff**.
- Clear separation of concerns:
  - Conversator: control plane + memory + UX
  - Beads: work graph
  - Builders: repo edits + tests
- Built-in backpressure/inbox to prevent interruption fatigue.
