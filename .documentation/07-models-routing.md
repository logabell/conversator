
# Models, Providers & Routing

## Principles
- Voice model/provider is constrained (Gemini Live) and treated as UX transport.
- All other subagents are **provider-agnostic** and configured via a routing policy.
- Builders are invoked through adapters (OpenCode default).

## Agent roles

### Voice
- Real-time conversation, low latency.
- Must not bear heavy planning or long context.

### Clarifier
- Turns vague intent into structured questions.
- Must minimize questions; ask only when blocking.

### Prompt Refiner / Spec Compiler
- Produces the structured prompt (XML-like) and ExecutionSpec JSON.
- Prefer cheap/fast models with strong formatting discipline.

### Retriever
- Codebase + Beads notes retrieval with strict caps.

### Gatekeeper
- Detects risky actions; requests approvals.

### Summarizer
- Converts builder output into natural conversational updates.

## Routing policy

Inputs to routing:
- task type (docs-only vs code changes vs refactor)
- risk level (security/infra touching)
- cost budget
- speed requirements
- privacy constraints

Outputs:
- which model/provider per subagent
- builder engine choice

## Adapter design
Each builder adapter accepts:
- `handoff.md` (structured prompt)
- `handoff.json` (ExecutionSpec)
- optional retrieval pack

Adapters handle:
- session creation
- status updates
- cancellation
- permission/gate translation

## Example routing config (illustrative)
- Prompt Refiner: cheap formatting-strong model
- Gatekeeper: strong reasoning model
- Builder default: OpenCode session (tool use, repo-native)
