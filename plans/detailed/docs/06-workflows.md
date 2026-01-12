
# Workflows

## Master workflow (voice → handoff → build → summarize)

```mermaid
sequenceDiagram
  participant U as User (Voice)
  participant V as Voice (Gemini Live)
  participant C as Conversator
  participant P as Prompt Refiner Subagent
  participant B as Beads
  participant E as Builder Engine

  U->>V: Describe goal (vague)
  V->>C: Transcript/intent
  C->>P: Create/update working prompt (working.md)
  P-->>C: working.md updated + short delta summary
  C->>V: Ask essential questions (if any)
  U->>V: Answer
  V->>C: Answers
  C->>P: Refine working.md
  P-->>C: working.md updated
  U->>V: "Send it"
  V->>C: Confirm
  C->>C: Freeze working -> handoff.md + handoff.json
  C->>B: Create/link Beads task + attach handoff pointers
  B->>E: Builder pulls ready task
  E-->>B: Progress notes + artifacts
  E-->>C: Status events
  C->>V: Natural-pause update + offer details
```

## Prompt refinement loop

- Single mutable prompt file: `working.md`
- Each refinement overwrites file in place.
- Conversator shows **brief delta** to user (not full file).
- Freeze to handoff only when user confirms.

## Parallel planning & building

- Conversator can refine prompt A while builder works on task B.
- Conversator maintains:
  - inbox queue (batched updates)
  - “awaiting review/approval” list
  - “recently completed” list

## Status recall flow

```mermaid
flowchart TD
  Q[User asks: what are we doing?] --> C[Conversator]
  C --> S[Load compact state + memory]
  S --> A[Answer with 5-10 bullets + pointers]
  A -->|User asks details| F[Fetch artifacts/Beads notes]
  F --> D[Show expanded details]
```

## Research flow (optional)
- User asks: “Go research X”
- Conversator dispatches Researcher subagent
- Researcher returns:
  - key findings (bullets)
  - citations/links
  - recommended prompt adjustments
- Prompt Refiner incorporates findings into `working.md`
