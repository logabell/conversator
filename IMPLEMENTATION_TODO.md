# Conversator Implementation TODO

**Last Updated**: 2026-01-13
**Current Phase**: 1-2 (Voice Loop + Prompt Refinement)

---

## Implementation Status Overview

| Phase | Focus | Status | Progress |
|-------|-------|--------|----------|
| 0 | Repo skeleton & config | DONE | 100% |
| 1 | Voice loop + control plane MVP | DONE | 95% |
| 2 | Prompt refinement pipeline | PARTIAL | 60% |
| 3 | Beads integration | NOT STARTED | 0% |
| 4 | Builder adapter (OpenCode) | PARTIAL | 50% |
| 5 | Memory + retrieval + token budgets | NOT STARTED | 5% |
| 6 | Inbox/backpressure + UX polish | PARTIAL | 30% |
| 7 | Hardening (security + observability) | NOT STARTED | 5% |

---

## HIGH PRIORITY - Blocking Issues

### 1. Complete Prompt Refinement Pipeline (Phase 2)
**Status**: Working.md handling exists, but refinement flow incomplete

- [ ] Wire clarifier subagent to voice layer for multi-turn refinement
- [ ] Implement `handoff.md` freeze on user confirmation ("send it")
- [ ] Generate `handoff.json` (ExecutionSpec) from finalized prompts
- [ ] Add gate tags to handoff.json for approval requirements
- [ ] Test end-to-end: vague request -> clarification -> handoff artifacts

**Files**: `python/voice/src/conversator_voice/prompt_manager.py`, `handlers.py`

### 2. Beads Integration (Phase 3)
**Status**: Model fields exist (`beads_id`) but no CLI integration

- [ ] Install/configure Beads CLI in development environment
- [ ] Implement `beads_client.py` for task CRUD operations
- [ ] Wire `create_beads_task()` to handoff workflow
- [ ] Implement `bd ready` polling for dispatching ready tasks
- [ ] Add dependency tracking (blocks/blocked-by relationships)
- [ ] Attach artifact pointers to Beads task notes
- [ ] Update state mappings: `beads_id <-> conversator_task_id`

**Spec**: `plans/detailed/docs/04-task-session-state.md`

### 3. Fix OpenCode Port Configuration
**Status**: Hardcoded to port 4096

- [ ] Make OpenCode port configurable in `config.yaml`
- [ ] Add port conflict detection on startup
- [ ] Consider dynamic port allocation for multi-session support

**Files**: `python/voice/src/conversator_voice/main.py:76-77`, `opencode_client.py`

---

## MEDIUM PRIORITY - Core Functionality

### 4. Builder Adapter Completion (Phase 4)
**Status**: OpenCode client works, dispatch basic

- [ ] Implement Claude Code SDK builder (abstraction exists, SDK not wired)
- [ ] Add builder selection logic based on task type/config
- [ ] Implement cancellation flow (cancel running builder session)
- [ ] Handle builder errors gracefully with retry logic
- [ ] Emit proper status events for dashboard updates
- [ ] Test gate request flow (builder requests user approval)

**Files**: `python/voice/src/conversator_voice/builder_client.py`, `builder_manager.py`

### 5. Gate System Implementation
**Status**: `awaiting_gate` state exists but not wired

- [ ] Define gate types: `confirm-before-write`, `confirm-before-run`, `confirm-destructive`
- [ ] Implement gate extraction from handoff.json
- [ ] Add gate approval flow in dashboard (approve/reject buttons)
- [ ] Add voice approval command: "approve" / "reject"
- [ ] Track gate decisions in state store
- [ ] Resume builder after gate approval

**Spec**: `plans/detailed/docs/10-ui-ux.md`

### 6. Memory & RAG System (Phase 5)
**Status**: Directory structure exists, no implementation

- [ ] Implement `memory/atomic.jsonl` for committed memory items
- [ ] Create episodic summary generator for completed tasks
- [ ] Add keyword extraction and indexing
- [ ] Implement retrieval with token budget caps
- [ ] Add SQLite FTS for local search (defer embeddings to later)
- [ ] Wire `lookup_context()` tool to retrieval system
- [ ] Enforce pointer-first responses (return refs, not full content)

**Spec**: `plans/detailed/docs/05-memory-and-rag.md`

### 7. Token Budget Enforcement
**Status**: Budget values defined in config, not enforced

- [ ] Add token counter utility
- [ ] Enforce voice layer budget (~900 tokens)
- [ ] Enforce subagent budget (~4K tokens each)
- [ ] Implement context truncation when over budget
- [ ] Add budget monitoring to dashboard

**Config**: `.conversator/config.yaml` - `budgets` section

---

## LOWER PRIORITY - Polish & UX

### 8. Inbox/Backpressure System (Phase 6)
**Status**: Inbox model exists, delivery logic incomplete

- [ ] Implement notification priority queue
- [ ] Add natural pause detection (VAD-based)
- [ ] Implement batched update surfacing
- [ ] Add quiet mode toggle
- [ ] Create "awaiting approval" list in dashboard
- [ ] Test with parallel builders generating notifications

**Spec**: `plans/detailed/docs/10-ui-ux.md`

### 9. Dashboard Improvements
**Status**: Functional but needs polish

- [ ] Add offline/reconnection handling UX
- [ ] Implement gate approval panel
- [ ] Add Beads task visualization (dependency graph)
- [ ] Show token usage metrics
- [ ] Add session history/playback
- [ ] Improve mobile responsiveness

**Files**: `python/voice/dashboard-ui/src/components/panels/`

### 10. Voice Transcript Persistence
**Status**: Currently in-memory only

- [ ] Decide: persist transcripts or discard after session?
- [ ] If persist: add to episodic memory after session
- [ ] If discard: document decision and add session summary instead

---

## HARDENING - Phase 7

### 11. Security
- [ ] Implement secrets redaction (detect .env patterns, API keys)
- [ ] Add file read allowlists (per-repo or global)
- [ ] Audit logging for sensitive operations
- [ ] Review all tool permissions

**Spec**: `plans/detailed/docs/08-security-permissions.md`

### 12. Observability
- [ ] Add structured logging with trace IDs
- [ ] Implement metrics (request counts, latencies, errors)
- [ ] Add session audit log (all tool calls with timestamps)
- [ ] Create health check endpoint

**Spec**: `plans/detailed/docs/09-reliability-observability.md`

### 13. Error Recovery
- [ ] Handle Gemini API disconnects gracefully
- [ ] Implement OpenCode process restart on crash
- [ ] Add session checkpoint/restore on process restart
- [ ] Test state recovery after crash (event replay)

---

## TECH DEBT / CLEANUP

### 14. Configuration Cleanup
- [ ] Remove hardcoded port assumptions
- [ ] Validate config schema on startup
- [ ] Add config migration for breaking changes
- [ ] Document all config options

### 15. Test Coverage
- [ ] Add test coverage reporting
- [ ] Write integration tests for Beads workflow
- [ ] Add stress tests for long sessions
- [ ] Test concurrent builder scenarios

### 16. Documentation Updates
- [x] Update CLAUDE.md with current status
- [x] Mark overview/ docs as superseded
- [x] Update open questions with resolutions
- [ ] Add architecture diagram to README
- [ ] Document dashboard API endpoints
- [ ] Create developer setup guide

---

## Open Decisions Needed

1. **Voice transcript persistence**: Persist or discard? Impacts memory budget.
2. **Multi-project orchestration**: How to handle cross-repo workspaces?
3. **Approval patterns**: Single approval vs "approve all" for repeated gates?
4. **Memory compaction timing**: On task completion or timed intervals?

See `plans/detailed/docs/14-open-questions.md` for full list.

---

## Next Steps (Recommended Order)

1. **Fix OpenCode port config** - Quick win, unblocks multi-session testing
2. **Complete prompt refinement** - Needed before Beads integration makes sense
3. **Beads integration** - Core workflow dependency
4. **Gate system** - Required for safe builder execution
5. **Memory/RAG basics** - Needed for long sessions

---

## Files Changed in This Review

- `CLAUDE.md` - Updated status from "planning" to "Phase 1-2"
- `plans/detailed/docs/14-open-questions.md` - Marked resolved questions
- `plans/overview/README.md` - Added note that these are superseded
- `IMPLEMENTATION_TODO.md` - Created (this file)
