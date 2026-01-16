
# Task & Session State Model

## Design principle
- **Beads is the canonical task graph**
- **Conversator is the canonical runtime/session controller**
- Conversator state is **event-sourced** (append-only events + derived current state)

## Entities

### ConversatorTask
Represents a runtime unit of work inside Conversator (often maps 1:1 to a Beads task).

Fields (minimum):
- conversator_task_id (uuid)
- beads_id (string, optional until created)
- title
- status: draft | refining | ready_to_handoff | handed_off | running | awaiting_gate | awaiting_user | done | failed | canceled
- priority
- created_at, updated_at
- working_prompt_path
- handoff_prompt_path (set when frozen)
- builder_session_id (optional)
- last_event_id (for fast resume)

### BuilderSession
Represents an execution session with OpenCode/Claude Code/etc.
- builder_session_id
- provider (opencode | claude_code | etc)
- status: created | running | paused | waiting_permission | completed | failed | aborted
- started_at, ended_at
- artifacts: diff_summary_path, test_output_path, etc.

### InboxItem
- inbox_id
- severity: info | success | warning | error | blocking
- summary (1 sentence)
- refs (beads_id, paths, session_id)
- created_at
- acknowledged_at (optional)

## Event sourcing

### TaskEvent (append-only)
- event_id (monotonic)
- time
- type
- task_id
- payload (json)

Example types:
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

## Recovery & reconciliation

On startup:
1. Load last snapshot/derived state from local DB.
2. Replay events after snapshot to rebuild current state.
3. Query builder backends for live session status; reconcile differences.
4. Rebuild inbox if needed (or keep persisted inbox).

## Idempotency rules

- Handoff freeze produces a deterministic handoff artifact path (based on task_id).
- Dispatch stores a `dispatch_token` event; re-dispatch is blocked unless explicitly requested.
- Linking Beads tasks must be idempotent: if beads_id already set, do not create a new task.

## Cancellation rules

- Cancellation sets task state to `cancel_requested` immediately.
- Adapter calls provider abort (e.g., OpenCode abort endpoint).
- Emit TaskCanceled and annotate Beads with the reason and timestamp.
