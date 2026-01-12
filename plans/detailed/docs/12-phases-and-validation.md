
# Phases & Validation Plan

This breaks the project into phases with concrete proofs-of-done.

## Phase 0 — Repo skeleton & config
**Objectives**
- Create workspace layout
- Define config schema for:
  - models/providers per subagent
  - routing policy
  - budgets and gates

**Proofs / tests**
- Config loads and validates.
- Workspace bootstraps `.conversator/` structure.
- Smoke test: create a dummy task and write `working.md`.

## Phase 1 — Voice loop + control plane MVP
**Objectives**
- Voice loop connected (Gemini Live)
- Basic commands: status, inbox, cancel
- Event log + derived state

**Proofs / tests**
- Can speak “create task X” and system creates ConversatorTask.
- Crash/restart: state restores and continues.

## Phase 2 — Prompt refinement pipeline
**Objectives**
- Prompt Refiner subagent writes `working.md` in-place.
- Clarifier asks minimal questions.
- Freeze to `handoff.*` on “send it”.

**Proofs / tests**
- UC‑1 end-to-end: vague request → handoff artifacts created.
- Gate tags appear correctly in `handoff.json`.

## Phase 3 — Beads integration
**Objectives**
- Create/link Beads tasks from handoff.
- Attach pointers to handoff artifacts in Beads notes.

**Proofs / tests**
- A Beads task appears with correct metadata.
- Dependencies can be added and shown as “ready”.

## Phase 4 — Builder adapter (OpenCode default)
**Objectives**
- Dispatch Beads-ready tasks to OpenCode sessions.
- Monitor session status + emit events.
- Support cancellation and gate requests.

**Proofs / tests**
- Builder session starts from handoff prompt.
- Status updates feed inbox.
- Cancellation aborts session and annotates Beads.

## Phase 5 — Memory + retrieval + token budgets
**Objectives**
- Tiered memory store working.
- Retrieval caps enforced per agent.
- Pointer-first responses.

**Proofs / tests**
- UC‑3 works: “what are we doing” answers from compact state.
- “show details” fetches artifacts and expands.

## Phase 6 — Inbox/backpressure + UX polish
**Objectives**
- Natural pause detection and batched update surfacing
- Quiet mode
- Awaiting-approval list

**Proofs / tests**
- UC‑2 works: parallel tasks with non-annoying updates.

## Phase 7 — Hardening (security + observability)
**Objectives**
- Secrets redaction
- Audit logging
- Metrics and trace IDs

**Proofs / tests**
- Attempt to read `.env` is blocked/redacted.
- Logs show full action chain for a task.
