#!/bin/bash
# Start an OpenCode builder instance (Layer 3) for Conversator.
#
# This starts a standard OpenCode server using the user's default OpenCode config
# (no OPENCODE_CONFIG_DIR). This is intentionally separate from Conversator's
# Layer 2 orchestration instance (which runs on its own port + config).
#
# Defaults:
# - Builder port: 4096 (OpenCode default)
# - Working directory: repo root (override with BUILDER_DIR)

set -e

PROJECT_ROOT="$(dirname "$(dirname "${BASH_SOURCE[0]}")")"
CACHE_DIR="${PROJECT_ROOT}/.conversator/cache"

mkdir -p "$CACHE_DIR"

# Check if opencode is installed
if ! command -v opencode &> /dev/null; then
    echo "Error: opencode not found. Please install OpenCode first."
    exit 1
fi

# Function to check if port is in use
port_in_use() {
    nc -z localhost "$1" 2>/dev/null
}

PORT="${BUILDER_PORT:-4096}"
WORKDIR="${BUILDER_DIR:-$PROJECT_ROOT}"

echo "Starting OpenCode builder instance..."
echo "  Port: $PORT"
echo "  Working dir: $WORKDIR"

if port_in_use "$PORT"; then
    echo "  Port $PORT already in use - builder may already be running"
    echo "  If this is your normal OpenCode instance, that's fine."
    exit 0
fi

# Start OpenCode server in the requested directory
opencode serve --port "$PORT" --hostname 127.0.0.1 \
    --cors http://localhost:5173 \
    2>&1 | tee -a "${CACHE_DIR}/builder.log" &

BUILDER_PID=$!
echo "$BUILDER_PID" > "${CACHE_DIR}/builder.pid"
echo "OpenCode builder started with PID: $BUILDER_PID"

# Wait for startup
echo "Waiting for builder to start..."
for i in {1..30}; do
    if curl -s "http://localhost:${PORT}/agent" > /dev/null 2>&1; then
        echo "Builder ready at http://localhost:${PORT}"
        exit 0
    fi
    sleep 1
done

echo "Warning: Builder may not be fully ready yet"
echo "Check logs at ${CACHE_DIR}/builder.log"
