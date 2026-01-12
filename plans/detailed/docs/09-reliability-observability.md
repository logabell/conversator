
# Reliability & Observability

## Reliability patterns
- Event-sourced state for deterministic recovery
- Idempotent dispatch tokens to prevent duplicates
- Provider timeouts and retries with backoff
- Degraded modes:
  - voice down → text control
  - builder down → queue and notify
  - retrieval down → answer from compact memory only

## Retry policies (guideline)
- Subagents:
  - 1–2 retries max
  - exponential backoff
- Builder dispatch:
  - never auto-retry a write/run operation without user approval
  - safe to retry status polling

## Observability

### Structured logs
- Every action has:
  - trace_id
  - task_id
  - beads_id
  - session_id (if any)
  - agent_name + model/provider

### Metrics
- time-to-handoff
- build success rate
- average interruptions per hour
- inbox size and latency to acknowledge
- token usage per layer
- retrieval chunk counts

### Tracing
- Link subagent calls to builder execution and final artifacts.

## Health checks
- voice connection status
- beads CLI availability
- builder adapter connectivity
- local index integrity
