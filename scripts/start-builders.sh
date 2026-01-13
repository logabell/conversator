#!/bin/bash
# Start OpenCode builder instances for Conversator
# Uses the user's default OpenCode config with opencode/gemini-3-flash model

set -e

PROJECT_ROOT="$(dirname "$(dirname "${BASH_SOURCE[0]}")")"
CACHE_DIR="${PROJECT_ROOT}/.conversator/cache"

mkdir -p "$CACHE_DIR"

echo "Starting OpenCode builder instances..."

# Check if opencode is installed
if ! command -v opencode &> /dev/null; then
    echo "Error: opencode not found. Please install OpenCode first."
    exit 1
fi

# Function to check if port is in use
port_in_use() {
    nc -z localhost "$1" 2>/dev/null
}

# Start opencode-fast on port 8002
if port_in_use 8002; then
    echo "  Port 8002 already in use - opencode-fast may already be running"
else
    echo "Starting opencode-fast on port 8002..."
    opencode serve --port 8002 --hostname 127.0.0.1 \
        2>&1 | tee -a "${CACHE_DIR}/builder-fast.log" &
    echo $! > "${CACHE_DIR}/builder-fast.pid"
fi

# Start opencode-pro on port 8003
if port_in_use 8003; then
    echo "  Port 8003 already in use - opencode-pro may already be running"
else
    echo "Starting opencode-pro on port 8003..."
    opencode serve --port 8003 --hostname 127.0.0.1 \
        2>&1 | tee -a "${CACHE_DIR}/builder-pro.log" &
    echo $! > "${CACHE_DIR}/builder-pro.pid"
fi

# Wait for startup
echo "Waiting for builders to start..."
sleep 3

# Health check
echo ""
echo "Checking builder health..."

check_health() {
    local port=$1
    local name=$2
    if curl -s "http://localhost:${port}/agent" > /dev/null 2>&1; then
        echo "  ${name} (port ${port}): OK"
        return 0
    else
        echo "  ${name} (port ${port}): FAILED"
        return 1
    fi
}

check_health 8002 "opencode-fast" || true
check_health 8003 "opencode-pro" || true

echo ""
echo "Builder logs at:"
echo "  ${CACHE_DIR}/builder-fast.log"
echo "  ${CACHE_DIR}/builder-pro.log"
echo ""
echo "To stop builders:"
echo "  ${PROJECT_ROOT}/scripts/stop-builders.sh"
