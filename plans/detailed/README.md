
# Conversator — Spec & PRD Pack (v2)

**Generated:** 2026-01-12  
**Source input:** `conversator-prd-v1.md` (uploaded) + follow-on design decisions in this chat.

This folder is the **implementation-ready** breakdown of Conversator into modular markdown files:
- Overview & product framing
- Architecture & layer responsibilities
- Task/session state model (event-sourced)
- Memory/RAG & anti-token-bloat design
- Workflows (voice → prompt refinement → Beads → builder → feedback)
- Model routing & provider flexibility
- Reliability/recovery, observability
- Security & permissions
- UI/UX (voice behaviors, inbox/backpressure, gates)
- Workspace structure & file formats
- Phase plan with acceptance tests / proofs-of-done
- Package dependencies & implementation notes

## Document Map

1. `docs/00-overview.md` — High-level overview & goals
2. `docs/01-requirements.md` — Functional + non-functional requirements
3. `docs/02-personas-use-cases.md` — Personas, use cases, acceptance criteria
4. `docs/03-architecture.md` — Full architecture + layer contracts
5. `docs/04-task-session-state.md` — Task/session model, events, recovery
6. `docs/05-memory-and-rag.md` — Tiered memory, indexing, retrieval budgets
7. `docs/06-workflows.md` — End-to-end workflows + mermaid diagrams
8. `docs/07-models-routing.md` — Model/provider flexibility and routing policy
9. `docs/08-security-permissions.md` — Permissions, secrets hygiene, prompt-injection defense
10. `docs/09-reliability-observability.md` — Retries, timeouts, metrics, logging
11. `docs/10-ui-ux.md` — Voice UX, inbox/backpressure, gates, cancellations
12. `docs/11-workspace-layout.md` — On-disk structure, artifact storage, references
13. `docs/12-phases-and-validation.md` — Phased plan + tests/proofs-of-done
14. `docs/13-dependencies.md` — Packages, services, build/deploy notes
15. `docs/14-open-questions.md` — Decisions to finalize later
16. `templates/` — Canonical file templates (prompt XML, ExecutionSpec JSON, events)

## Conventions

- **Beads is the canonical work graph** (tasks/deps/history).
- **Conversator is the control plane** (voice UX, routing, memory discipline, session monitoring).
- **Prompt refinement happens in-place** in a *single* `working.md`.
- Only **finalized handoffs** become Beads tasks / builder executions.
- RAG indexes/embeddings are **local & disposable**; committed memory is **tiny & auditable**.
