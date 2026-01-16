
# Dependencies & Implementation Notes

## Core runtime (suggested)
- Language/runtime: choose one of:
  - Node.js/TypeScript (fast iteration, good CLI + HTTP)
  - Python (rapid prototyping, strong local tooling)
  - Rust (performance + single binary, more work upfront)

## Required integrations
- Gemini Live (voice)
- Beads CLI / library integration
- Builder engine adapter (OpenCode recommended default)
- VoxType github repo for linux wayland sst support

## Local storage
- SQLite for:
  - event log
  - derived state
  - chunk metadata (optional)
- JSONL for:
  - inbox
  - atomic memory

## Indexing/RAG
- SQLite FTS or local BM25 index
- Optional embeddings:
  - store vectors by content hash
  - rebuildable cache

## Packaging
- Single CLI:
  - `conversator start`
  - `conversator status`
  - `conversator inbox`
- Optional daemon mode for background monitoring
