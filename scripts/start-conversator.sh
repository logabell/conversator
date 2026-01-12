#!/bin/bash
# Start Conversator OpenCode subagents
# This runs OpenCode as the orchestration layer for prompt refinement
#
# Instance Isolation:
# - Uses OPENCODE_CONFIG_DIR to isolate from user's .opencode/
# - Agents are copied from versioned conversator/agents/ to runtime
# - User's own OpenCode setup remains completely untouched
#
# OpenCode HTTP Serve API endpoints:
# - POST /session                - Create new session
# - GET  /session/{id}           - Get session details
# - POST /session/{id}/message   - Send message (sync)
# - POST /session/{id}/prompt_async - Send message (async)
# - GET  /event                  - SSE real-time events
# - GET  /agent                  - List available agents

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load config
CONFIG_FILE="${PROJECT_ROOT}/.conversator/config.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file not found at $CONFIG_FILE"
    echo "Run scripts/init-workspace.sh first"
    exit 1
fi

# Version-controlled agent source
AGENTS_SOURCE="${PROJECT_ROOT}/conversator/agents"
if [ ! -d "$AGENTS_SOURCE" ]; then
    echo "Error: Agent source not found at $AGENTS_SOURCE"
    echo "Expected: conversator/agents/*.md"
    exit 1
fi

# Isolated OpenCode config directory (separate from user's .opencode/)
OPENCODE_CONFIG_DIR="${PROJECT_ROOT}/.conversator/opencode"
export OPENCODE_CONFIG_DIR

# Default port for OpenCode HTTP serve (4096 is OpenCode's default)
PORT="${CONVERSATOR_PORT:-4096}"

echo "Starting Conversator orchestration layer..."
echo "  Port: $PORT"
echo "  Config dir: $OPENCODE_CONFIG_DIR (isolated from user's .opencode/)"
echo "  Agent source: $AGENTS_SOURCE"

# Ensure runtime directories exist
mkdir -p "$OPENCODE_CONFIG_DIR/agent"
mkdir -p "${PROJECT_ROOT}/.conversator/cache"

# Sync version-controlled agents to runtime location
echo "Syncing agents..."
cp "$AGENTS_SOURCE"/*.md "$OPENCODE_CONFIG_DIR/agent/"
echo "  Synced: $(ls "$OPENCODE_CONFIG_DIR/agent/" | tr '\n' ' ')"

# Start OpenCode HTTP serve mode
# OpenCode will use OPENCODE_CONFIG_DIR for its config and agents
cd "$PROJECT_ROOT"
opencode serve \
    --port "$PORT" \
    --hostname 127.0.0.1 \
    2>&1 | tee -a "${PROJECT_ROOT}/.conversator/cache/conversator.log" &

OPENCODE_PID=$!
echo "OpenCode started with PID: $OPENCODE_PID"
echo "$OPENCODE_PID" > "${PROJECT_ROOT}/.conversator/cache/conversator.pid"

# Wait for server to be ready
echo "Waiting for server to be ready..."
for i in {1..30}; do
    # Check /agent endpoint to verify server is responding
    if curl -s "http://localhost:$PORT/agent" > /dev/null 2>&1; then
        echo ""
        echo "Conversator ready at http://localhost:$PORT"
        echo ""
        echo "Available endpoints:"
        echo "  POST /session              - Create new session"
        echo "  POST /session/{id}/message - Send message"
        echo "  GET  /event                - SSE events"
        echo "  GET  /agent                - List agents"
        echo ""
        echo "Isolation:"
        echo "  - Conversator uses: $OPENCODE_CONFIG_DIR"
        echo "  - User's .opencode/ is untouched"
        exit 0
    fi
    sleep 1
done

echo "Warning: Server may not be fully ready yet"
echo "Check logs at .conversator/cache/conversator.log"
