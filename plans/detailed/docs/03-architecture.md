
# Architecture

## High-level components

1. **Voice Interface (Gemini Live)**
   - Handles streaming audio and conversational turns.
   - Limited model choice here; treat it as a transport + UX layer.

2. **Conversator Control Plane**
   - Orchestrates subagents
   - Maintains runtime state + inbox
   - Enforces token budgets, gates, cancellation
   - Stores compact memory (pointers + summaries)

3. **Subagent Pool (provider-agnostic)**
   - Clarifier
   - Prompt Refiner / Spec Compiler
   - Retriever (codebase + optional web)
   - Gatekeeper (risk + approvals)
   - Summarizer (builder output → natural voice updates)

4. **Task Graph: Beads**
   - Canonical tasks, dependencies, work history
   - Builders pull from Beads “ready” tasks
   - Evidence is attached as Beads notes/links

5. **Builder Engines**
   - OpenCode sessions (recommended default)
   - Claude Code, other agents via adapters

## Responsibilities by layer

### Conversator Control Plane
- Owns:
  - conversation UX and state
  - model routing for subagents
  - memory policies and retrieval budgets
  - session monitoring
  - inbox/backpressure
- Does not own:
  - canonical work graph
  - full transcripts as memory

### Beads
- Owns:
  - task/dependency graph
  - durable history of what happened
- Does not own:
  - voice UX
  - model routing or memory policies

### Builder engines
- Own:
  - repo edits, tests, diffs, artifacts
- Must:
  - obey gates
  - report progress with structured events
  - attach evidence back to Beads

## Key contracts

### ExecutionSpec (handoff.json)
A structured payload used by any builder adapter:
- goal
- definition_of_done
- constraints
- repo_targets
- required_artifacts
- gates_required
- budgets (time/steps/toolcalls)

### Handoff prompt (handoff.md)
The human-readable prompt optimized for the builder LLM:
- structured XML-like format
- minimal context pointers
- explicit “ask before” steps

### Event stream
Everything meaningful emits events:
- subagent status changes
- builder progress
- gate requests / approvals
- errors and retries

## Diagram (conceptual)

```mermaid
flowchart LR
  User((User Voice)) --> Voice[Gemini Live Voice]
  Voice --> CP[Conversator Control Plane]
  CP --> SA[Subagents: clarify/refine/retrieve/summarize]
  CP --> Beads[(Beads Task Graph)]
  Beads --> Builder[Builder Engine(s)]
  Builder --> Beads
  Builder --> CP
  CP --> Voice
```
