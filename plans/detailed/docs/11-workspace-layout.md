
# Workspace Layout & File Storage

## Goals
- Keep state local and crash-safe
- Keep committed artifacts small and auditable
- Keep RAG/index artifacts disposable
- Store pointers everywhere (avoid token bloat)

## Recommended on-disk structure

```text
.beads/                         # Beads canonical tasks/deps/history
.conversator/
  state.sqlite                  # event log + derived state
  mappings.json                 # beads_id <-> conversator_task_id <-> session_id
  inbox.jsonl                   # notification queue
  recent.json                   # recent completions
  awaiting_review.json          # pending approvals/reviews
  prompts/
    <topic_or_task>/
      working.md                # mutable prompt while conversing
      handoff.md                # frozen prompt
      handoff.json              # ExecutionSpec
      retrieval_pack.json       # optional
      artifacts/                # diff summaries, logs, snapshots
  memory/
    atomic.jsonl                # small, auditable
    episodic/                   # per-task summaries (small)
    consolidated.json           # very small
  rag/                          # local disposable
    chunks.sqlite
    embeddings/
    bm25/
  checkpoints/
    <topic>/
      working.latest.bak        # last-known-good backup
```

## Referencing rules

- Conversator stores pointers (paths/ids) in its runtime state.
- Beads tasks contain:
  - concise summary
  - links to `handoff.*`
  - links to artifacts produced by builders
- Builder outputs:
  - write diff summary into `artifacts/`
  - attach pointers back to Beads

## Artifact naming conventions
- `handoff.md` and `handoff.json` are the canonical “execution contract”.
- Builder artifacts include timestamp + short slug:
  - `diff-summary-2026-01-12T2103Z.md`
  - `test-output-2026-01-12T2106Z.txt`
