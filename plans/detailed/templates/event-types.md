
# Event Types (Canonical)

## Task lifecycle
- TaskCreated
- WorkingPromptUpdated
- QuestionsRaised
- UserAnswered
- HandoffFrozen
- BeadsTaskLinked
- BuilderDispatched
- BuilderStatusChanged
- GateRequested
- GateApproved
- GateDenied
- BuildCompleted
- BuildFailed
- TaskCanceled

## Inbox severity mapping
- info: normal progress
- success: completed milestones
- warning: non-blocking issues, retries
- error: failed operations
- blocking: requires user action (gate, missing info)

## Minimal event payloads
- Always include:
  - task_id
  - time
  - type
  - refs: beads_id, session_id, artifact paths (if relevant)
