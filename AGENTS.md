# AGENTS.md (Conversator)
Guidance for agentic coding tools working in this repository.
Scope: repo root (applies to everything unless a nested `AGENTS.md` overrides it).

## Repo Map
- Python voice backend + orchestration: `python/voice/src/conversator_voice/`
- Python tests: `python/voice/tests/`
- Dashboard UI (Vite + React + TS): `python/voice/dashboard-ui/`
- Versioned OpenCode subagent prompts: `conversator/agents/`
- Runtime state (mostly gitignored): `.conversator/`
- Workspace scripts: `scripts/`
- Specs / PRD pack: `plans/detailed/docs/`

## Cursor / Copilot Rules
- Cursor: no `.cursor/rules/` or `.cursorrules` found.
- Copilot: no `.github/copilot-instructions.md` found.
If these appear later, treat them as higher-priority editor/agent rules.

## Agent Defaults (important)
- Prefer minimal, surgical diffs; avoid drive-by refactors.
- Don’t introduce new deps/frameworks unless asked.
- If you touch files in a subdirectory, check for nested `AGENTS.md` rules.
- Don’t commit, push, or open PRs unless explicitly requested.
- Don’t edit or commit runtime state under `.conversator/` unless the task requires it.

## Project Documentation / Core Objectives
- Source of truth lives in `.documentation/`.
- Product goals + core objectives: `.documentation/00-conversator-prd-v1.md`, `.documentation/01-requirements.md`.
- High-level overview: `.documentation/00-overview.md`, `.documentation/02-conversator-overview.md`.
- Architecture + state model: `.documentation/03-architecture.md`, `.documentation/04-task-session-state.md`, `.documentation/event-types.md`.
- Security/permissions + validation phases: `.documentation/08-security-permissions.md`, `.documentation/12-phases-and-validation.md`.
- Workspace layout: `.documentation/11-workspace-layout.md`.

## Quick Start
```bash
./scripts/init-workspace.sh
# OpenCode orchestration layer (Layer 2, default :4158)
./scripts/start-conversator.sh
# Builder layer (Layer 3, default OpenCode server :4096)
# (Optional helper: starts a standard OpenCode server if not already running)
./scripts/start-builders.sh
# Voice + dashboard API (default dashboard port :8080)
cd python/voice
export GOOGLE_API_KEY=...
conversator-voice --source local
# or: python -m conversator_voice --source local
# Dashboard UI (dev)
cd python/voice/dashboard-ui
npm ci
npm run dev
```
Stop helpers:
- `./scripts/stop-conversator.sh`
- `./scripts/stop-builders.sh`

## Build / Lint

### Python (voice backend)
```bash
cd python/voice
pip install -e ".[dev]"
ruff check src/ tests/
ruff check --fix src/ tests/
ruff format src/ tests/
```

### Dashboard UI (Vite + TypeScript)
```bash
cd python/voice/dashboard-ui
npm ci
npm run dev      # http://localhost:5173
npm run build    # tsc + vite build (typecheck gate)
npm run preview
```
Notes:
- Dev proxy is configured in `python/voice/dashboard-ui/vite.config.ts`.
- Production build emits to `python/voice/src/conversator_voice/dashboard/static`.

## Services / Ports (defaults)
- OpenCode orchestration (Layer 2): `http://localhost:4158` (health via `/agent`)
- Builder OpenCode server (Layer 3): `http://localhost:4096` (health via `/agent`)
- Dashboard API + WS server: `http://localhost:8080` (health via `/health`, WS `ws://localhost:8080/ws/events`)
- Vite dev server: `http://localhost:5173` (proxies `/api` + `/ws` to :8080)

## Config / State
- Main config file: `.conversator/config.yaml` (created/managed by `./scripts/init-workspace.sh`).
- Key defaults: `conversator.port=4158`, builder OpenCode `:4096`, dashboard API `:8080`.
- Builder definitions live under `builders:` in the config.
- `.conversator/opencode/` isolates OpenCode config; scripts may symlink auth/config from user `~/.opencode/`.
- OpenCode server API spec is available at `.documentation/opencode_api.json`.
- Treat `.conversator/` as runtime state; don’t commit changes unless explicitly requested.

## Code Style and Conventions

### General
- Keep changes scoped to the request; match surrounding conventions.
- Prefer explicit, actionable error messages.
- Avoid silent failures; ensure errors carry enough context to debug.

### Python (`python/voice/src/conversator_voice/`)
Tooling:
- Ruff is the source of truth (`python/voice/pyproject.toml`): `line-length = 100`, `target-version = py311`, rules `E,F,I,UP`.
Imports:
- 3 blocks with a blank line between: standard library, third-party, local.
- Prefer `ruff check --fix` to keep ordering consistent.
Formatting + naming:
- 4-space indentation; docstrings for modules/classes/public functions.
- `snake_case` functions/vars, `PascalCase` classes/types, `UPPER_CASE` constants.
Types:
- Avoid `Any` except at serialization edges.
- Prefer `Literal[...]` enums and keep values aligned with `python/voice/src/conversator_voice/models.py`.
- Prefer `dataclasses` for plain data containers.
Async + subprocess:
- Prefer `async def` for I/O; avoid blocking calls in the event loop; add explicit timeouts.
- Prefer `subprocess.run(["cmd"], timeout=..., capture_output=True, text=True)`; avoid `shell=True`.
Error handling:
- Don’t swallow exceptions; include context.
- Tool handlers should return structured errors: `ToolResponse(result={"error": "..."})`.
Domain invariants:
- State is event-sourced: append events first, derive state second (`StateStore`).
- Keep `working.md` mutable and only freeze to `handoff.md` + `handoff.json` on explicit confirmation.

### TypeScript / React (`python/voice/dashboard-ui/`)
Tooling:
- TS `strict: true`, `noUnusedLocals/noUnusedParameters` (typecheck gate is `npm run build`).
Formatting + naming:
- 2-space indent, semicolons, single quotes, trailing commas.
- `camelCase` values/functions, `PascalCase` components/types.
Types + API shapes:
- Avoid `any`; use `unknown` and narrow.
- Keep API shapes and helpers centralized in `python/voice/dashboard-ui/src/api/client.ts`.
Networking + state:
- Always check `res.ok` and throw useful errors; prefer shared fetch helpers.
- Prefer hooks + functional components; centralize state in Zustand stores under `python/voice/dashboard-ui/src/stores/`.

## Repo Hygiene (important)
- Don’t commit runtime/derived artifacts under `.conversator/` (esp `.conversator/cache/`, `.conversator/state.sqlite*`, `.conversator/opencode/`, prompt `working.md`).
- Don’t commit secrets (`.env`, API keys, auth tokens).
- Don’t commit `python/voice/dashboard-ui/node_modules/`.
