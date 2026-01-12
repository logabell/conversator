
# UI/UX (Voice-first)

## Voice interaction principles
- Don’t interrupt mid-thought.
- Surface updates at natural pauses.
- Keep spoken updates short; offer details on request.

## Inbox and backpressure
- Inbox stores “what happened” events.
- Backpressure rules:
  - batch updates per pause window
  - defer low priority while user is actively speaking
  - escalate blocking items immediately

## Core voice commands
- “What are we doing now?”
- “Show inbox”
- “Summarize the last completed task”
- “Cancel current build”
- “Pause background work”
- “Send it” (freeze and handoff)
- “Open details for <task>”
- “Find <symbol/file> in the codebase”
- “Research <topic>”

## Gates UX
- When a gate triggers, Conversator asks:
  - “Builder wants to write files X/Y. Approve?”
  - “Builder wants to run: `pnpm test`. Approve?”
- Responses:
  - “Approve”
  - “Approve once”
  - “Deny”
  - “Deny and explain”

## Summaries
- Any completed build should be summarized as:
  - what changed
  - why
  - how to verify
  - how to rollback
  - what’s next
