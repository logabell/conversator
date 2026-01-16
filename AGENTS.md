# AGENTS.md (Conversator)

Guidance for agentic coding tools working in this repository.
Scope: repo root (applies to everything unless a nested `AGENTS.md` overrides it).

## Repo Map

- Python voice backend + orchestration: `python/voice/src/conversator_voice/`
- Python tests: `python/voice/tests/`
- Dashboard UI (Vite + React + TS): `python/voice/dashboard-ui/`
- Versioned OpenCode subagent prompts: `conversator/agents/`
- Runtime state (mostly gitignored): `.conversator/`
- Specs / PRD pack: `plans/detailed/docs/`

## Cursor / Copilot Rules

- Cursor: no `.cursor/rules/` or `.cursorrules` found.
- Copilot: no `.github/copilot-instructions.md` found.

If these appear later, treat them as higher-priority editor/agent rules.

## Build / Lint / Test

### Python (voice backend)

```bash
cd python/voice

# Dev install (includes pytest/ruff)
pip install -e ".[dev]"

# Lint + import sorting (ruff)
ruff check src/ tests/
ruff check --fix src/ tests/

# Format (ruff formatter)
ruff format src/ tests/

# Tests
pytest -q

# Single file
pytest -q tests/test_prompt_manager.py

# Single test (node id)
pytest -q tests/test_prompt_manager.py::TestPromptManager::test_freeze_to_handoff_creates_both_files

# Filter
pytest -q -k prompt_manager

# Skip slow tests
pytest -q -m "not slow"
```

External/integration tests:

- OpenCode integration: needs OpenCode server at `http://localhost:4096`.
  - Start: `./scripts/start-conversator.sh`
  - Run: `cd python/voice && pytest -v tests/test_opencode_integration.py`
  - Skip: `SKIP_OPENCODE_TESTS=1`
- Gemini Live: needs `GOOGLE_API_KEY`.
  - Run: `cd python/voice && export GOOGLE_API_KEY=... && pytest -v tests/test_gemini_live.py`
- E2E workflow: needs `GOOGLE_API_KEY` and (typically) OpenCode.
  - Run: `cd python/voice && export GOOGLE_API_KEY=... && pytest -v tests/test_e2e_workflow.py`

### Dashboard UI (Vite + TypeScript)

```bash
cd python/voice/dashboard-ui

npm ci
npm run dev      # http://localhost:5173
npm run build    # tsc + vite build
npm run preview
```

Notes:
- Dev proxy routes `/api` and `/ws` to `http://localhost:8080` (`python/voice/dashboard-ui/vite.config.ts`).
- Production build emits to `python/voice/src/conversator_voice/dashboard/static`.

## Code Style and Conventions

### General

- Prefer minimal, surgical diffs; keep changes scoped to the request.
- Keep runtime state and generated artifacts out of commits.
- When in doubt, follow nearby patterns in the same package.

### Python (`python/voice/src/conversator_voice/`)

Language + tooling:
- Python `>=3.11` (`str | None`, `list[str]`, `dict[str, Any]`).
- Lint/format with `ruff` (`line-length = 100`, `target-version = py311`, rules `E,F,I,UP`).

Imports:
- 3 blocks with a blank line between: standard library, third-party, local.
- Use absolute imports within the package (`from conversator_voice...`) or relative (`from .foo import Bar`) consistently within a file.

Formatting + naming:
- 4-space indentation; docstrings for modules/classes/public functions.
- Naming: `snake_case` for functions/vars, `PascalCase` for classes, `UPPER_CASE` for constants.
- Prefer `Path` over stringly paths; keep filesystem writes explicit and localized.

Typing:
- Avoid `Any` at boundaries when possible; prefer `unknown`-like patterns via narrowing (e.g., `dict[str, Any]` only at serialization edges).
- Use `Literal[...]` for stringly enums (see `TaskStatus`, `EventType` in `models.py`).
- Prefer `dataclasses` for plain data containers (common pattern in `models.py`).

Async + subprocess:
- Use `async def` for network/file I/O; avoid blocking calls in the event loop.
- Prefer `subprocess.run(["cmd", "arg"], timeout=..., capture_output=True, text=True)`.
- Avoid `shell=True` unless absolutely necessary; if used, validate/sanitize inputs.

Error handling:
- Tool handlers should return structured errors: `ToolResponse(result={"error": "..."})`.
- Don’t swallow exceptions silently; if a failure is non-fatal, explain why and keep enough context to debug.

Domain invariants (keep aligned):
- State is event-sourced: append events first, derive state second (`StateStore`).
- Keep status/event strings aligned with `models.py` Literals.
- Prompt refinement uses a single mutable `working.md` and freezes to `handoff.md` + `handoff.json` on explicit user confirmation.

Tests:
- Use `pytest` + `pytest-asyncio`; async tests typically use `@pytest.mark.asyncio`.
- Prefer small, deterministic unit tests; mark slow/external tests with `@pytest.mark.slow` and guard with env-based skips.

### TypeScript / React (`python/voice/dashboard-ui/`)

Tooling:
- TypeScript is `strict: true` with `noUnusedLocals/noUnusedParameters`.
- No dedicated lint script; `npm run build` is the typecheck gate.

Formatting + naming:
- Match existing formatting: semicolons, single quotes, trailing commas, 2-space indent.
- Naming: `camelCase` for values/functions, `PascalCase` for components/types.

Types + data safety:
- Avoid `any`; use `unknown` for untrusted data and narrow it.
- Keep API types centralized (see `python/voice/dashboard-ui/src/api/client.ts`).

Networking + errors:
- Use the fetch helpers in `python/voice/dashboard-ui/src/api/client.ts`.
- Always check `res.ok` and throw a useful `Error` on failure.

State + React patterns:
- Prefer functional components + hooks.
- Centralize state updates in the Zustand store (`python/voice/dashboard-ui/src/stores/`).

## Repo Hygiene (important)

- `.conversator/` is primarily runtime state; most of it is gitignored.
  - Avoid committing: `.conversator/cache/`, `.conversator/state.sqlite*`, `.conversator/opencode/`, prompt `working.md` files.
- Do not commit secrets (`.env`, API keys, auth tokens).
- `python/voice/dashboard-ui/node_modules/` should not be committed (if it shows up in `git status`, do not add it).