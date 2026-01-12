
# Personas & Use Cases

## Target user
- Developers and technical operators who run long interactive coding sessions.
- Power users who want voice to reduce friction and keep flow.

## Use cases (primary)

### UC‑1: Vague Problem → Detailed Plan → Finalized Handoff
**Scenario**
User speaks a vague request (“add SSO”, “fix latency”, “refactor storage”).

**Success criteria**
- Conversator asks only essential clarifying questions.
- Produces `working.md` prompt artifact that is refined in conversation.
- On “send it”, produces:
  - `handoff.md` (structured prompt)
  - `handoff.json` (ExecutionSpec)
  - a Beads task referencing those artifacts.

**Acceptance tests**
- The final handoff includes:
  - goal
  - definition of done
  - constraints
  - repo targets and expected artifacts
  - gates

### UC‑2: Parallel Planning & Building
**Scenario**
Multiple tasks are in-flight: planning for one, building for another.

**Success criteria**
- Conversator maintains an inbox of updates.
- Updates are surfaced at natural pauses, not mid-thought.
- Backpressure rules prevent notification spam.
- User can query: “What finished?” and get a batched summary.

**Acceptance tests**
- Run two builder sessions in parallel:
  - show combined progress
  - no more than one interruption per pause window
  - inbox retains full details

### UC‑3: Status Check & Context Recall
**Scenario**
User asks: “what are we doing over here?” or “why did we choose X?”

**Success criteria**
- Conversator responds from compact memory (pointers + tiny summaries).
- If user asks for details, Conversator fetches artifacts/Beads notes and expands.

**Acceptance tests**
- A “why” query returns:
  - decision summary
  - pointer(s) to Beads/task/artifacts
- A follow-up “show details” pulls exact artifact content.

## Secondary use cases (nice-to-have)
- UC‑4: “Go research X” (web) and incorporate findings into prompt refinement.
- UC‑5: “Find X in our codebase” (repo search) and propose targets.
