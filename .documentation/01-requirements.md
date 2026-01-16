
# Requirements

## Functional requirements

### Voice + conversation
- Real-time voice loop (Gemini Live constrained for voice stream).
- Interruption handling (“barge-in”), pause detection, and “natural pause” notification surfacing.
- Natural conversation flow focused, no expected commands, but conversations like:
  - “What are we doing now?”
  - “Show inbox”
  - “Pause/cancel current work”
  - “Send final prompt”
  - “Summarize last change”
  - “Find X in the codebase”
  - “Research Y”

### Prompt refinement
- Maintain a single mutable `working.md` prompt artifact per topic/task.
- Refinement is performed by a configurable “Prompt Refiner” subagent.
- Prompt output format is LLM-friendly and **strictly structured** (XML-like recommended).
- When user confirms, create immutable `handoff.md` + `handoff.json` spec.

### Task graph and execution
- Beads is used for:
  - creating tasks
  - linking dependencies
  - tracking status and notes
- Dispatch finalized handoff to a builder engine:
  - OpenCode sessions (recommended default) OR other adapters
- Monitor builder sessions and surface progress via inbox.

### Memory & retrieval
- Maintain tiered memory:
  - Atomic facts/decisions (tiny)
  - Episodic per-task summaries (short)
  - Consolidated “project beliefs” (very short)
- RAG/index artifacts are local/disposable; memory summaries are small and auditable.
- Retrieval must respect hard budgets (token caps).

### Safety gates
- Confirm-before-write and confirm-before-run gates.
- Destructive operations must require explicit user approval.
- Cancellation must halt builder sessions and annotate Beads task.

## Non-functional requirements (NFRs)

### Performance
- Voice loop latency: target < 500ms for turn handoff (best effort).
- Subagent response: target < 5s for “small tasks” (summaries, retrieval).
- RAG retrieval: target < 200ms locally (BM25/SQLite) + optional embedding lookup.

### Reliability
- Crash-safe: recover state from event log + external session status.
- Idempotent dispatch: retries must not duplicate Beads tasks or builder sessions.
- Clear degraded modes: voice provider down → text UI; builder down → queue work.

### Privacy & security
- Secrets redaction for any content sent to external models.
- Prompt-injection resistant tool policy (repo text is untrusted).
- Audit log of reads/writes/commands executed (even if not stored forever).

### Observability
- Structured logs with trace IDs across subagents and builder sessions.
- Metrics: queue depth, success/failure rates, average time-to-handoff.

## Definition of Done (v1)
- UC-1, UC-2, UC-3 demonstrably work end-to-end (see use case doc).
- A user can:
  - talk to create/clarify a task
  - finalize prompt handoff
  - watch builder progress
  - receive summarized results
  - request details on demand
