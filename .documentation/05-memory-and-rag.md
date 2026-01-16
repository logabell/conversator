
# Memory, Indexing & RAG (Token Discipline)

## Objective
Deliver long-running helpfulness **without** growing prompt context unbounded.

Conversator uses:
- **tiered memory** (tiny, auditable)
- **pointer-first retrieval** (fetch details only when asked/needed)
- **local disposable indexes** (embeddings and chunk stores rebuilt as needed)

## Tiered memory model

### Tier 1: Atomic memory units (tiny)
Examples:
- “We require confirm-before-run for tests.”
- “This repo uses pnpm, not npm.”
- “Never edit `.env` or secrets; redact before sending to external models.”

Format:
- id
- type: decision | constraint | preference | gotcha | requirement
- text (1–3 sentences)
- tags
- refs (beads_id, files, commits)
- created_at

### Tier 2: Episodic summaries (per task/session)
- 5–12 bullets max
- “what changed”, “what was decided”, “what’s next”
- linked to beads_id + artifacts

### Tier 3: Consolidated project beliefs
- very short “project rules of the road”
- periodically regenerated (compaction step)

## Retrieval policy

### Default injection budgets (guideline)
- Voice loop: <= 250 tokens of memory
- Clarifier/spec compiler: <= 800 tokens of memory + <= 1200 tokens retrieved chunks
- Builder handoff: <= 1200 tokens total prompt + pointers, no large transcript dumps

### Retrieval sources
1. Beads task notes and status
2. Workspace artifacts (handoff.md, diff summary)
3. Codebase search results (file pointers, line ranges)
4. Optional web research (only when requested)

### Ranking strategy
- Hybrid:
  - lexical (BM25 / SQLite FTS)
  - embeddings (local)
  - tags (symbolic)
- Re-rank to a strict cap: max N chunks injected.

## Index storage strategy

### Committed (small & auditable)
- `.conversator/memory/atomic.jsonl`
- `.conversator/memory/consolidated.json`

### Local disposable (rebuildable)
- `.conversator/rag/chunks.sqlite` (chunk metadata + text)
- `.conversator/rag/embeddings/` (vectors by content hash)
- `.conversator/rag/bm25/` (lexical index files)

## Compaction
- On task completion:
  - summarize builder output into episodic summary
  - extract atomic decisions/constraints
- Periodically:
  - consolidate Tier 2 → Tier 3
  - prune stale or superseded entries

## “Just enough” principle
Conversator stores enough to answer:
- “what are we doing?”
- “what finished?”
- “why did we decide X?”
…and uses pointers to fetch deeper details only when asked.
